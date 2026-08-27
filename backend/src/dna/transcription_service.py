"""Transcription service for managing Vexa subscriptions and segment processing."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from dna.events import EventPublisher, EventType, get_event_publisher
from dna.in_review_timeline import version_in_review_at
from dna.models.playlist_metadata import PlaylistMetadataUpdate
from dna.models.stored_segment import StoredSegmentCreate
from dna.storage_providers.storage_provider_base import (
    StorageProviderBase,
    get_storage_provider,
)
from dna.transcription_providers.transcription_provider_base import (
    TranscriptionProviderBase,
    get_transcription_provider,
)

logger = logging.getLogger(__name__)

_service: "TranscriptionService | None" = None


class TranscriptionService:
    """Service for managing transcription subscriptions and processing segments."""

    def __init__(
        self,
        transcription_provider: TranscriptionProviderBase | None = None,
        storage_provider: StorageProviderBase | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        self.transcription_provider = transcription_provider
        self.storage_provider = storage_provider
        self.event_publisher = event_publisher
        self._subscribed_meetings: set[str] = set()
        self._meeting_to_playlist: dict[str, int] = {}
        # Playlists already reported as discarding their segments. Segments arrive in a steady
        # stream, so warning per batch buried the message in its own repetition — thirty identical
        # lines say no more than one, and make the log harder to read than silence would.
        self._warned_not_saving: set[int] = set()

    async def init_providers(self) -> None:
        """Initialize providers if not already set."""
        logger.info("Initializing transcription service providers...")
        if self.transcription_provider is None:
            self.transcription_provider = get_transcription_provider()
        if self.storage_provider is None:
            self.storage_provider = get_storage_provider()
        if self.event_publisher is None:
            self.event_publisher = get_event_publisher()
        logger.info("Transcription service providers initialized")

    async def resubscribe_to_active_meetings(self) -> None:
        """Resubscribe to any active meetings on startup for recovery."""
        if self.transcription_provider is None or self.storage_provider is None:
            logger.error("Providers not initialized, cannot resubscribe")
            return

        logger.info("Checking for active meetings to resubscribe...")

        try:
            active_bots = await self.transcription_provider.get_active_bots()
            if not active_bots:
                logger.info("No active meetings found")
                return

            logger.info(
                "Found %d active bot(s), attempting to resubscribe", len(active_bots)
            )

            for bot in active_bots:
                platform = bot.get("platform", "")
                native_meeting_id = bot.get("native_meeting_id", "")
                status = bot.get("status", "")

                if not platform or not native_meeting_id:
                    logger.warning(
                        "Skipping bot with missing platform/meeting_id: %s", bot
                    )
                    continue

                if status in ("completed", "failed", "stopped"):
                    logger.debug(
                        "Skipping inactive bot %s:%s (status: %s)",
                        platform,
                        native_meeting_id,
                        status,
                    )
                    continue

                # Resolve by the VEXA meeting id, which names one meeting. The room name does not:
                # it is reused across playlists, so looking a live meeting up by it returns an
                # arbitrary one of them — and everything downstream then acts on the wrong
                # playlist. Observed doing exactly that: a meeting on one playlist was recovered
                # as another, and the completion handler cleared the in-review mark belonging to a
                # playlist whose own meeting had ended hours earlier.
                vexa_id = bot.get("id") or bot.get("meeting_id")
                metadata = None
                if vexa_id is not None:
                    metadata = await self.storage_provider.get_playlist_metadata_by_vexa_meeting_id(
                        vexa_id
                    )
                if metadata is None:
                    # No Vexa id, or no playlist claims it. Falling back to the room name is a
                    # guess, so say so rather than letting a wrong answer look like a right one.
                    metadata = (
                        await self.storage_provider.get_playlist_metadata_by_meeting_id(
                            native_meeting_id
                        )
                    )
                    if metadata is not None:
                        logger.warning(
                            "Meeting %s (vexa id %s) matched no playlist directly; falling back "
                            "to the room name and guessing playlist %s — segments and cleanup "
                            "for this meeting may belong elsewhere",
                            native_meeting_id,
                            vexa_id,
                            metadata.playlist_id,
                        )
                if metadata is None:
                    logger.warning(
                        "No playlist metadata found for meeting %s, skipping",
                        native_meeting_id,
                    )
                    continue

                meeting_key = f"{platform}:{native_meeting_id}"
                self._meeting_to_playlist[meeting_key] = metadata.playlist_id

                internal_meeting_id = (
                    metadata.vexa_meeting_id or bot.get("meeting_id") or bot.get("id")
                )
                if internal_meeting_id is not None:
                    self.transcription_provider.register_meeting_id_mapping(
                        internal_meeting_id, platform, native_meeting_id
                    )

                logger.info(
                    "Resubscribing to meeting %s (playlist_id: %s, vexa_id: %s, status: %s)",
                    meeting_key,
                    metadata.playlist_id,
                    internal_meeting_id,
                    status,
                )

                try:
                    await self.transcription_provider.subscribe_to_meeting(
                        platform=platform,
                        meeting_id=native_meeting_id,
                        on_event=self._on_vexa_event,
                    )
                    self._subscribed_meetings.add(meeting_key)
                    logger.info("Successfully resubscribed to meeting: %s", meeting_key)

                    if self.event_publisher:
                        await self.event_publisher.publish(
                            EventType.BOT_STATUS_CHANGED,
                            {
                                "platform": platform,
                                "meeting_id": native_meeting_id,
                                "playlist_id": metadata.playlist_id,
                                "status": status,
                                "recovered": True,
                            },
                        )
                        logger.info(
                            "Published recovery status for meeting %s: %s",
                            meeting_key,
                            status,
                        )
                except Exception as e:
                    logger.exception(
                        "Failed to resubscribe to meeting %s: %s", meeting_key, e
                    )

        except Exception as e:
            logger.exception("Error during resubscription: %s", e)

    async def _on_vexa_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle events from Vexa and forward to event publisher."""
        if self.event_publisher is None:
            logger.error("Event publisher not initialized")
            return

        if event_type == "transcript.updated":
            # The service persists confirmed segments + broadcasts the flat
            # `{type:"transcript", ...}` shape directly from
            # `on_transcription_updated`. No need to also emit
            # TRANSCRIPTION_UPDATED through the publisher — nothing
            # subscribes to it and frontends only consume the flat envelope.
            await self.on_transcription_updated(payload)
        elif event_type == "bot.status_changed":
            await self.event_publisher.publish(
                EventType.BOT_STATUS_CHANGED,
                payload,
            )
            status = payload.get("status", "").lower()
            if status in ("completed", "failed", "stopped"):
                await self.event_publisher.publish(
                    (
                        EventType.TRANSCRIPTION_COMPLETED
                        if status == "completed"
                        else EventType.TRANSCRIPTION_ERROR
                    ),
                    payload,
                )
                await self.on_transcription_completed(payload)
        else:
            logger.warning("Unknown Vexa event type: %s", event_type)

    async def subscribe_to_meeting(
        self, platform: str, meeting_id: str, playlist_id: int
    ) -> None:
        """Subscribe to Vexa updates for a meeting."""
        if self.transcription_provider is None:
            logger.error("Transcription provider not initialized")
            return

        meeting_key = f"{platform}:{meeting_id}"
        if meeting_key in self._subscribed_meetings:
            logger.info("Already subscribed to meeting: %s", meeting_key)
            return

        self._meeting_to_playlist[meeting_key] = playlist_id

        logger.info(
            "Subscribing to Vexa updates for meeting: %s (playlist_id: %s)",
            meeting_key,
            playlist_id,
        )

        try:
            await self.transcription_provider.subscribe_to_meeting(
                platform=platform,
                meeting_id=meeting_id,
                on_event=self._on_vexa_event,
            )
            self._subscribed_meetings.add(meeting_key)
            logger.info("Successfully subscribed to meeting: %s", meeting_key)
        except Exception as e:
            logger.exception("Failed to subscribe to meeting %s: %s", meeting_key, e)

    async def on_transcription_updated(self, payload: dict[str, Any]) -> None:
        """Passthrough: upsert Vexa's confirmed segments by their stable
        `segment_id`, then forward the raw `{type:"transcript", confirmed,
        pending, speaker, playlist_id, version_id, ts}` message to DNA WS
        clients — the frontend TranscriptManager consumes it directly.
        """
        if self.storage_provider is None or self.event_publisher is None:
            logger.error("Providers not initialized")
            return

        platform = payload.get("platform", "")
        meeting_id = payload.get("meeting_id", "")
        speaker = payload.get("speaker")
        confirmed: list[dict[str, Any]] = payload.get("confirmed", []) or []
        pending: list[dict[str, Any]] = payload.get("pending", []) or []
        ts = payload.get("ts")

        meeting_key = f"{platform}:{meeting_id}"
        playlist_id = self._meeting_to_playlist.get(meeting_key)
        if playlist_id is None:
            logger.warning(
                "No playlist_id found for meeting %s, cannot save segments",
                meeting_key,
            )
            return

        metadata = await self.storage_provider.get_playlist_metadata(playlist_id)
        if metadata is None or metadata.in_review is None:
            # Everything upstream is working — the bot is in the meeting and Vexa is transcribing
            # — and every segment is being thrown away because there is no version to attach it
            # to. Announce it once, to the UI as well as the log: the failure is invisible from
            # the outside, which is what made it cost a whole meeting on 2026-08-21.
            if playlist_id not in self._warned_not_saving:
                self._warned_not_saving.add(playlist_id)
                logger.warning(
                    "Playlist %s: DISCARDING segments — no version is in review. The bot and "
                    "transcription are working; nothing is being kept. Mark a version in review "
                    "to start storing them (earlier speech is not backfilled).",
                    playlist_id,
                )
                await self.event_publisher.publish(
                    EventType.BOT_STATUS_CHANGED,
                    {
                        "platform": platform,
                        "meeting_id": meeting_id,
                        "playlist_id": playlist_id,
                        "saving_segments": False,
                        "warnings": ["no_version_in_review"],
                    },
                )
            return
        # Saving again — let a later lapse warn afresh rather than staying quiet because of one
        # long-past complaint.
        self._warned_not_saving.discard(playlist_id)

        if metadata.transcription_paused:
            logger.debug(
                "Transcription paused for playlist %s, skipping segment storage",
                playlist_id,
            )
            return

        resumed_at = metadata.transcription_resumed_at

        for seg in confirmed:
            segment_id = seg.get("segment_id")
            absolute_start_time = seg.get("absolute_start_time")
            text = (seg.get("text") or "").strip()
            if not segment_id or not absolute_start_time or not text:
                continue

            if resumed_at is not None:
                try:
                    segment_time = datetime.fromisoformat(
                        absolute_start_time.replace("Z", "+00:00")
                    )
                    resumed_at_aware = (
                        resumed_at
                        if resumed_at.tzinfo is not None
                        else resumed_at.replace(tzinfo=timezone.utc)
                    )
                    if segment_time < resumed_at_aware:
                        continue
                except ValueError:
                    pass

            # Which version was in review WHEN THESE WORDS WERE SAID, not when they arrived.
            # Vexa confirms a segment five to seven seconds after the speech ends, so reading the
            # current mark here filed everything said just before a reviewer moved on under the
            # shot they moved to — on a controlled test, two of three shots had their own version
            # number attributed to the following shot.
            version_id = version_in_review_at(
                metadata.in_review_history,
                absolute_start_time,
                fallback=metadata.in_review,
            )
            if version_id is None:
                # Spoken before anything was marked. The same silence as the no-mark case above,
                # and worth the same complaint: it is invisible from outside.
                if playlist_id not in self._warned_not_saving:
                    self._warned_not_saving.add(playlist_id)
                    logger.warning(
                        "Playlist %s: discarding a segment spoken at %s — no version was in "
                        "review at that moment. Earlier speech is not backfilled.",
                        playlist_id,
                        absolute_start_time,
                    )
                continue

            segment_create = StoredSegmentCreate(
                segment_id=segment_id,
                text=text,
                speaker=seg.get("speaker") or speaker,
                language=seg.get("language"),
                start_time=seg.get("start_time"),
                end_time=seg.get("end_time"),
                completed=True,
                absolute_start_time=absolute_start_time,
                absolute_end_time=seg.get("absolute_end_time", ""),
                vexa_updated_at=seg.get("updated_at"),
            )

            try:
                await self.storage_provider.upsert_segment(
                    playlist_id=playlist_id,
                    version_id=version_id,
                    segment_id=segment_id,
                    data=segment_create,
                )
            except Exception:
                logger.exception("Failed to upsert segment %s", segment_id)

        # Broadcast the raw Vexa shape with DNA envelope fields.
        # Frontend TranscriptManager.handleMessage() consumes this directly.
        #
        # The CURRENT mark, deliberately, and not the per-segment attribution above: this is the
        # live pane, and it shows the version the reviewer is looking at now. A batch can resolve
        # to more than one version once late arrivals are attributed by speech time, and a single
        # envelope cannot say so — what is stored is the record, and the pane reconciles with it
        # on the next fetch.
        await self.event_publisher.ws_manager.broadcast(
            {
                "type": "transcript",
                "speaker": speaker,
                "confirmed": confirmed,
                "pending": pending,
                "playlist_id": playlist_id,
                "version_id": metadata.in_review,
                "ts": ts,
            }
        )

    async def _clear_in_review(self, playlist_id: Optional[int]) -> None:
        """Unset the in-review mark now the meeting it belonged to has ended.

        Best-effort on purpose: the meeting IS over, and failing to tidy up afterwards must not
        raise through the completion handler and skip the unsubscribes that follow it. The cost of
        missing one is the stale-mark behaviour this exists to fix, which is visible; the cost of
        raising here is a leaked subscription, which is not.
        """
        if playlist_id is None or self.storage_provider is None:
            return
        try:
            await self.storage_provider.upsert_playlist_metadata(
                playlist_id, PlaylistMetadataUpdate(clear_in_review=True)
            )
            logger.info(
                "Playlist %s: meeting ended — cleared the in-review mark so the next session "
                "states its own",
                playlist_id,
            )
        except Exception as e:
            logger.warning(
                "Playlist %s: could not clear the in-review mark (%s) — the next meeting may "
                "attribute segments to this one's version until it is set again",
                playlist_id,
                e,
            )

    async def on_transcription_completed(self, payload: dict[str, Any]) -> None:
        """Handle transcription completion."""
        logger.info("Transcription completed: %s", payload)

        platform = payload.get("platform")
        meeting_id = payload.get("meeting_id")

        if platform and meeting_id:
            meeting_key = f"{platform}:{meeting_id}"

            # BEFORE the mapping below is discarded — it is how the playlist is known.
            #
            # The in-review mark says where arriving segments belong. Once the meeting is over it
            # belongs to nothing, and leaving it set means the NEXT meeting on this playlist
            # attributes its opening remarks to a version from the last one, silently and with
            # every indicator reporting health. Clearing it also re-arms the dispatch warning, so
            # a new session states which version it is about rather than inheriting an answer.
            await self._clear_in_review(self._meeting_to_playlist.get(meeting_key))

            if meeting_key in self._subscribed_meetings:
                self._subscribed_meetings.discard(meeting_key)
                logger.info(
                    "Removed subscription for completed meeting: %s", meeting_key
                )

            if meeting_key in self._meeting_to_playlist:
                del self._meeting_to_playlist[meeting_key]
                logger.info(
                    "Removed playlist mapping for completed meeting: %s", meeting_key
                )

            if self.transcription_provider:
                try:
                    await self.transcription_provider.unsubscribe_from_meeting(
                        platform=platform, meeting_id=meeting_id
                    )
                    logger.info(
                        "Unsubscribed from Vexa for completed meeting: %s", meeting_key
                    )
                except Exception as e:
                    logger.warning("Failed to unsubscribe from Vexa: %s", e)

    async def close(self) -> None:
        """Clean up resources."""
        logger.info("Closing transcription service...")
        if self.transcription_provider:
            await self.transcription_provider.close()
        self._subscribed_meetings.clear()
        self._meeting_to_playlist.clear()
        logger.info("Transcription service closed")


def get_transcription_service() -> TranscriptionService:
    """Get the singleton TranscriptionService instance."""
    global _service
    if _service is None:
        _service = TranscriptionService()
    return _service


def reset_transcription_service() -> None:
    """Reset the singleton for testing purposes."""
    global _service
    _service = None
