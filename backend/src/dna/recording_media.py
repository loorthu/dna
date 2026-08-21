"""Recording media relay — hand a playlist's recording out part-by-part, and let it be archived.

WHY A RELAY AND NOT A REDIRECT: in the airgapped deployment the browser never reaches Vexa, and
neither does anything else on the prod side except through DNA. So DNA is the only path by which
the archiving collector can see the media, and the Vexa API key must never leave this process.

WHY PARTS AND NOT THE MASTER: the master only exists once the meeting is over, and pulling several
hundred MB in one shot across the airgap link at the end is exactly the transfer most likely to
fail. The bot uploads the recording in parts as it produces them, so a consumer can mirror it
DURING the meeting, verifying each part as it lands, and finish moments after the meeting does.

DNA stores no copy of its own. The parts stream through: Vexa holds them until the collector
confirms a durable archive, and only then may the upstream copy be deleted.

Addressed by PLAYLIST, not by Vexa ids: the collector knows about playlists, and the mapping to a
recording is this module's job — resolved lazily, because the bot is often still uploading when
transcription completes, so an eager resolution at that moment usually finds nothing.
"""

import logging
from typing import Any, Optional

from dna.models.playlist_metadata import PlaylistMetadataUpdate

logger = logging.getLogger(__name__)


class RecordingNotFound(Exception):
    """No recording is linked to this playlist (yet, or ever)."""


class ArchiveNotConfirmed(Exception):
    """Refusing to delete: no durable archive has been recorded for this recording."""


class ArchiveRecordingMismatch(Exception):
    """The archive being recorded came from a different recording than this playlist resolves to."""


class RecordingMediaService:
    """Resolve a playlist's recording and relay its parts.

    Collaborators are injected so the whole flow is drivable offline: a fake transcription
    provider and a fake storage provider are enough to exercise every branch.
    """

    def __init__(self, transcription_provider: Any, storage_provider: Any):
        self.provider = transcription_provider
        self.storage = storage_provider

    async def resolve(self, playlist_id: int) -> dict[str, Any]:
        """The playlist's recording ids, resolving and caching them on first use.

        Raises ``RecordingNotFound`` when the playlist has no meeting, or the meeting has no video
        recording yet. Callers treat that as "not ready", not as an error.
        """
        metadata = await self.storage.get_playlist_metadata(playlist_id)
        if metadata is None:
            raise RecordingNotFound(f"No metadata for playlist {playlist_id}")

        recording_id = metadata.vexa_recording_id
        media_file_id = metadata.recording_media_file_id
        # The cache is only good for the meeting it was resolved against. A playlist whose
        # collection never finished keeps its link (nothing purged it), so a SECOND meeting would
        # otherwise be served the first meeting's recording — and, once archived under the new
        # meeting's id, the second recording would never be collected at all.
        if (
            recording_id is not None
            and metadata.recording_link_meeting_id is not None
            and metadata.recording_link_meeting_id != metadata.vexa_meeting_id
        ):
            logger.info(
                "Playlist %s: recording link was resolved for meeting %s but the playlist is now "
                "on meeting %s — re-resolving",
                playlist_id,
                metadata.recording_link_meeting_id,
                metadata.vexa_meeting_id,
            )
            recording_id = None
            media_file_id = None
        if recording_id is not None and media_file_id is not None:
            return {
                "recording_id": recording_id,
                "media_file_id": media_file_id,
                "start_time_utc": metadata.recording_start_time_utc,
                "duration_seconds": metadata.recording_duration_seconds,
                "network_path": metadata.recording_network_path,
                "sha256": metadata.recording_sha256,
            }

        # LAZY resolution. Doing this eagerly when transcription completes usually finds nothing:
        # the bot is still flushing its last parts at that moment. Resolving on first read means
        # the answer is looked up when someone actually wants the media.
        if metadata.vexa_meeting_id is None:
            raise RecordingNotFound(f"Playlist {playlist_id} has no Vexa meeting")

        recordings = await self.provider.list_recordings(metadata.vexa_meeting_id)
        video = next(
            (
                r
                for r in recordings
                if any(m.get("type") == "video" for m in r.get("media_files", []))
            ),
            None,
        )
        if video is None:
            raise RecordingNotFound(
                f"No video recording for playlist {playlist_id} yet"
            )

        recording_id = video["id"]
        # The master call is also the finalize-on-read trigger, and it is what reports the
        # recorder's own start clock — the anchor the cut list needs.
        master = await self.provider.get_recording_master(
            recording_id, media_type="video"
        )
        media_file_id = master.get("media_file_id")
        if media_file_id is None:
            raise RecordingNotFound(f"Recording {recording_id} has no video media file")

        await self.storage.upsert_playlist_metadata(
            playlist_id,
            PlaylistMetadataUpdate(
                vexa_recording_id=recording_id,
                recording_media_file_id=media_file_id,
                recording_link_meeting_id=metadata.vexa_meeting_id,
                recording_start_time_utc=master.get("start_time_utc"),
                recording_duration_seconds=master.get("duration_seconds"),
            ),
        )
        logger.info(
            "Linked playlist %s to recording %s (media file %s)",
            playlist_id,
            recording_id,
            media_file_id,
        )
        return {
            "recording_id": recording_id,
            "media_file_id": media_file_id,
            "start_time_utc": master.get("start_time_utc"),
            "duration_seconds": master.get("duration_seconds"),
            "network_path": None,
            "sha256": None,
        }

    async def list_chunks(self, playlist_id: int, after: int = -1) -> dict[str, Any]:
        """The parts index, addressed by playlist. Poll with ``after`` to get only what is new."""
        ids = await self.resolve(playlist_id)
        index = await self.provider.list_recording_chunks(
            ids["recording_id"], ids["media_file_id"], after_seq=after
        )
        index["playlist_id"] = playlist_id
        # Carried alongside the parts so a consumer never has to make a second call to learn
        # where the media starts in wall-clock terms.
        index.setdefault("start_time_utc", ids["start_time_utc"])
        index.setdefault("duration_seconds", ids["duration_seconds"])
        return index

    async def get_chunk(
        self, playlist_id: int, chunk_seq: int
    ) -> tuple[bytes, Optional[str]]:
        """One part's bytes and its advertised hash, relayed verbatim."""
        ids = await self.resolve(playlist_id)
        return await self.provider.get_recording_chunk(
            ids["recording_id"], ids["media_file_id"], chunk_seq
        )

    async def get_audio(self, playlist_id: int) -> tuple[bytes, dict[str, Any]]:
        """The assembled AUDIO master, whole, with its own wall-clock anchor.

        Audio is relayed whole rather than part-by-part, unlike video. It is a small fraction of
        the video's size, and it is wanted at exactly one moment — when the collector muxes the
        two streams together, after the meeting has ended — so the argument for mirroring it
        during the session does not apply.

        The anchor is the reason this returns metadata alongside the bytes. The streams do NOT
        start together: the bot starts video first by design, so audio begins some way in, and
        the mux has to pad by the difference. Both anchors come from the bot's own clock, so the
        difference is exact rather than skew-prone.

        Deliberately NOT folded into ``list_chunks``: reading a master is finalize-on-read, which
        reassembles it from every part. On a ~10s poll that would rebuild the audio master for
        the whole meeting, over and over.
        """
        ids = await self.resolve(playlist_id)
        master = await self.provider.get_recording_master(
            ids["recording_id"], media_type="audio"
        )
        audio_media_file_id = master.get("media_file_id")
        if audio_media_file_id is None:
            raise RecordingNotFound(
                f"Recording {ids['recording_id']} has no audio media file"
            )
        data = await self.provider.get_recording_media_raw(
            ids["recording_id"], audio_media_file_id, media_type="audio"
        )
        return data, {
            "media_file_id": audio_media_file_id,
            "start_time_utc": master.get("start_time_utc"),
            "duration_seconds": master.get("duration_seconds"),
            "video_start_time_utc": ids["start_time_utc"],
        }

    async def record_archive(
        self,
        playlist_id: int,
        network_path: str,
        sha256: str,
        recording_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Record that the media is durably archived somewhere DNA does not own.

        This is the fact that later permits deleting the upstream copy, so it is written before
        any deletion is possible — never inferred from one.

        ``recording_id`` is the caller's claim about WHICH recording it mirrored. It is optional
        for older callers, but when given it must match what this playlist currently resolves to:
        a disagreement means the collector and DNA are looking at different recordings, and
        recording the archive anyway would mark the wrong meeting as collected.
        """
        metadata = await self.storage.get_playlist_metadata(playlist_id)
        ids = await self.resolve(playlist_id)
        if recording_id is not None and recording_id != ids["recording_id"]:
            raise ArchiveRecordingMismatch(
                f"Playlist {playlist_id} resolves to recording {ids['recording_id']}, but the "
                f"archive was collected from recording {recording_id}; refusing to record it"
            )

        # Re-read the master for its FINAL length. The stored duration was written when the
        # recording was first resolved — which, with the collector running continuously, is
        # seconds into the meeting — so it describes however much had uploaded by then rather
        # than the meeting. Archiving is the moment it stops moving: the collector only gets
        # here once the index reports the upload complete, so this is the length of the file
        # that was just archived. Costs one call, once per recording.
        final = await self.provider.get_recording_master(
            ids["recording_id"], media_type="video"
        )
        duration = final.get("duration_seconds")
        start = final.get("start_time_utc")

        await self.storage.upsert_playlist_metadata(
            playlist_id,
            PlaylistMetadataUpdate(
                recording_network_path=network_path,
                recording_sha256=sha256,
                archived_recording_id=ids["recording_id"],
                archived_meeting_id=metadata.vexa_meeting_id if metadata else None,
                # `None` means "leave unchanged" to the upsert, so a master that cannot report
                # these keeps whatever was already known rather than blanking it.
                # `None` means "leave unchanged" to the upsert, so a master that cannot report
                # these keeps whatever was already known rather than blanking it.
                recording_duration_seconds=duration,
                recording_start_time_utc=start,
            ),
        )
        if duration is not None and ids.get("duration_seconds") != duration:
            logger.info(
                "Playlist %s: final duration %.1fs (was %s at first resolve)",
                playlist_id,
                duration,
                ids.get("duration_seconds"),
            )
        logger.info(
            "Playlist %s recording archived at %s (sha256 %s…)",
            playlist_id,
            network_path,
            sha256[:12],
        )
        return {
            "playlist_id": playlist_id,
            "recording_id": ids["recording_id"],
            "network_path": network_path,
            "sha256": sha256,
        }

    async def delete_upstream(self, playlist_id: int) -> dict[str, Any]:
        """Purge the upstream copy — ONLY once an archive has been recorded.

        The guard is the point. The archived copy is the only other one, so deleting without
        confirmation would destroy the recording outright. Enforced here rather than trusted to
        the caller, so a bug in the collector cannot cost the media.
        """
        ids = await self.resolve(playlist_id)
        if not ids.get("network_path") or not ids.get("sha256"):
            raise ArchiveNotConfirmed(
                f"Playlist {playlist_id} has no recorded archive; refusing to delete the "
                f"upstream copy (POST the archive path and sha256 first)"
            )
        result = await self.provider.delete_recording(ids["recording_id"])
        await self.storage.upsert_playlist_metadata(
            playlist_id,
            # A flag, not None assignment: the upsert treats None as "leave unchanged", so the
            # ids would survive and keep pointing at a recording that no longer exists.
            PlaylistMetadataUpdate(clear_recording_link=True),
        )
        logger.info(
            "Purged upstream recording %s for playlist %s (archived at %s)",
            ids["recording_id"],
            playlist_id,
            ids["network_path"],
        )
        return {
            "playlist_id": playlist_id,
            "recording_id": ids["recording_id"],
            "archived_at": ids["network_path"],
            **result,
        }
