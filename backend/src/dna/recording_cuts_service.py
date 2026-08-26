"""The cut list for a playlist's meeting recording: what to play, and where the shots are.

The player asks this one question and gets everything it needs — where the media is, where the
recording's zero is, and per version the spans of it that discussed that version. Building the
spans is a pure replay of stored-segment timestamps (`video_segment_publish`); this module is the
part that has to look things up and, more importantly, decide what to say when there is nothing to
play yet.

WHY THE STATUS ENUM CARRIES THE WEIGHT. Five situations produce an empty cut list, and they want
five different things from the person looking at the screen:

    no_meeting    no bot has ever run on this playlist   — nothing has happened yet
    no_recording  a meeting ran with recording off       — nothing is coming; stop waiting
    pending       it is being recorded right now         — come back when the meeting ends
    archiving     recorded, the collector has not finished — come back in a minute
    no_segments   recorded and archived, but this playlist has no transcript
                                                          — the meeting happened, nothing was said
                                                            against these versions

Collapsing those into "no cuts" makes them all render as a blank box, and a blank box is
indistinguishable from a bug. Reporting which one it is costs one enum and saves the person
guessing whether the system is broken or simply not finished.

`no_meeting` is split out from `no_recording` because it is the state every playlist is in before
its bot is dispatched — which is when the panel first asks. Answering "this meeting was not
recorded" there tells someone who is about to record a meeting that their recording will not
happen, and it is the only one of the five that stops being true while the tab is open.
"""

import logging
import os
from typing import Any, Optional

from dna.recording_media import RecordingMediaService, RecordingNotFound
from dna.video_segment_publish import build_video_cuts_payload, resolve_recording_t0

logger = logging.getLogger(__name__)


def recording_playback_enabled() -> bool:
    return os.getenv("DNA_ENABLE_RECORDING_PLAYBACK", "false").lower() == "true"


def media_url_for(network_path: Optional[str]) -> Optional[str]:
    """The URL nginx serves the archived file at, or None if there is no file.

    nginx aliases `/recordings/` onto RECORDING_NETWORK_PATH, so the URL is the basename under
    that prefix — the browser never learns the share's real path, and never needs to: it plays a
    plain <video src> off this origin, which is what makes native Range seeking work.
    """
    if not network_path:
        return None
    return f"/recordings/{os.path.basename(network_path)}"


class RecordingCutsService:
    """Assemble the playback answer for one playlist."""

    def __init__(self, transcription_provider: Any, storage_provider: Any):
        self.provider = transcription_provider
        self.storage = storage_provider

    async def build(self, playlist_id: int) -> dict[str, Any]:
        metadata = await self.storage.get_playlist_metadata(playlist_id)
        if metadata is None or metadata.vexa_meeting_id is None:
            # No bot has run here. Distinct from "not recorded": this is the state the playlist is
            # in every time the panel first opens, and it stops being true the moment a bot is
            # dispatched — so it must not read as a verdict on a meeting that has not happened.
            return self._empty("no_meeting", playlist_id)

        # Recording was turned off for this meeting, so the answer is known without asking
        # anything: there is no media, and there is no point deciding between "still recording"
        # and "still archiving" for a recording that was never started.
        if metadata.recording_enabled is False:
            return self._empty("no_recording", playlist_id)

        network_path = metadata.recording_network_path
        if not network_path:
            # No archive yet. Whether that is "still recording" or "waiting on the collector"
            # is answered by the upstream recording: it exists and is incomplete while the bot
            # is still uploading, and complete once the collector's turn has come.
            return self._empty(await self._unarchived_status(playlist_id), playlist_id)

        segments = await self.storage.get_segments_for_playlist(playlist_id)
        if not segments:
            return self._empty(
                "no_segments",
                playlist_id,
                media_url=media_url_for(network_path),
                duration_seconds=metadata.recording_duration_seconds,
            )

        try:
            t0, t0_source = resolve_recording_t0(
                vexa_start_time_utc=metadata.recording_start_time_utc,
                offset_seconds=float(os.getenv("RECORDING_T0_OFFSET_SECONDS", "0")),
            )
        except ValueError:
            # Archived media with no usable anchor. Every offset would be a guess, and a cut list
            # built on a guessed zero is wrong in a way that looks right, so the media is offered
            # without cuts rather than with invented ones.
            logger.warning(
                "Playlist %s: archived recording has no start time — serving media without cuts",
                playlist_id,
            )
            return self._empty(
                "no_segments",
                playlist_id,
                media_url=media_url_for(network_path),
                duration_seconds=metadata.recording_duration_seconds,
            )

        by_version: dict[int, list] = {}
        for segment in segments:
            by_version.setdefault(segment.version_id, []).append(segment)

        cut_lists = build_video_cuts_payload(
            by_version,
            recording_t0=t0,
            recording_duration_seconds=metadata.recording_duration_seconds or 0.0,
        )

        return {
            "playlist_id": playlist_id,
            "status": "ready",
            "media_url": media_url_for(network_path),
            "duration_seconds": metadata.recording_duration_seconds,
            "recording_t0": t0.isoformat(),
            "recording_t0_source": t0_source,
            "versions": [
                {
                    "version_id": cut_list.version_id,
                    "body_hash": cut_list.body_hash,
                    "cuts": [
                        {
                            "video_in_seconds": cut.video_in_seconds,
                            "video_out_seconds": cut.video_out_seconds,
                            "transcript_segment_ids": cut.transcript_segment_ids,
                        }
                        for cut in cut_list.cuts
                    ],
                }
                for cut_list in cut_lists
            ],
        }

    async def _unarchived_status(self, playlist_id: int) -> str:
        """`pending` while the recording is still being made, `archiving` once it is not.

        Asked of the upstream index rather than inferred from the meeting's status, because the
        bot keeps uploading for a short while after it leaves — the recording is the thing that
        knows whether it is finished.
        """
        media = RecordingMediaService(self.provider, self.storage)
        try:
            index = await media.list_chunks(playlist_id, after=-1)
        except RecordingNotFound:
            return "no_recording"
        # Upstream unreachable is not evidence that a recording never existed: saying
        # `no_recording` would tell the viewer to stop waiting for something still on its way.
        except Exception as e:
            logger.warning(
                "Playlist %s: could not read the chunk index (%s); reporting archiving",
                playlist_id,
                e,
            )
            return "archiving"
        return "archiving" if index.get("complete") else "pending"

    @staticmethod
    def _empty(
        status: str,
        playlist_id: int,
        *,
        media_url: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        return {
            "playlist_id": playlist_id,
            "status": status,
            "media_url": media_url,
            "duration_seconds": duration_seconds,
            "recording_t0": None,
            "recording_t0_source": None,
            "versions": [],
        }
