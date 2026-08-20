"""Transcription Provider Base.

Abstract base class for transcription providers and factory function.
"""

import os
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from dna.models.stored_segment import StoredSegment

if TYPE_CHECKING:
    from dna.models.transcription import (
        BotSession,
        BotStatus,
        Platform,
        Transcript,
    )

EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class TranscriptionProviderBase:
    """Abstract base class for transcription providers."""

    @staticmethod
    def build_transcript_text(segments: list[StoredSegment]) -> str:
        """Format stored segments as newline-separated ``Speaker: text`` lines."""
        if not segments:
            return "No transcript available."
        lines: list[str] = []
        for segment in segments:
            speaker = segment.speaker or "Unknown"
            lines.append(f"{speaker}: {segment.text}")
        return "\n".join(lines)

    async def dispatch_bot(
        self,
        platform: "Platform",
        meeting_id: str,
        playlist_id: int,
        passcode: Optional[str] = None,
        bot_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> "BotSession":
        """Dispatch a bot to join a meeting and start transcription."""
        raise NotImplementedError()

    async def stop_bot(self, platform: "Platform", meeting_id: str) -> bool:
        """Stop a bot that is currently in a meeting."""
        raise NotImplementedError()

    async def get_bot_status(
        self, platform: "Platform", meeting_id: str
    ) -> "BotStatus":
        """Get the current status of a bot."""
        raise NotImplementedError()

    async def get_transcript(
        self, platform: "Platform", meeting_id: str
    ) -> "Transcript":
        """Get the full transcript for a meeting."""
        raise NotImplementedError()

    async def subscribe_to_meeting(
        self,
        platform: str,
        meeting_id: str,
        on_event: EventCallback,
    ) -> None:
        """Subscribe to real-time updates for a meeting."""
        raise NotImplementedError()

    async def unsubscribe_from_meeting(
        self,
        platform: str,
        meeting_id: str,
    ) -> None:
        """Unsubscribe from a meeting's updates."""
        raise NotImplementedError()

    async def get_active_bots(self) -> list[dict[str, Any]]:
        """Get list of active bots for the current user.

        Returns a list of dicts with at least:
        - platform: str
        - native_meeting_id: str
        - status: str
        - meeting_id: int (internal ID, optional)
        """
        raise NotImplementedError()

    async def list_recordings(
        self, vexa_meeting_id: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Recordings visible to the configured API credential.

        ``vexa_meeting_id`` filters to one meeting's recordings; ``None`` returns all.
        Each recording carries ``media_files[]``, one per stream (audio, video).
        """
        raise NotImplementedError()

    async def get_recording_master(
        self, recording_id: int, media_type: str = "video"
    ) -> dict[str, Any]:
        """Metadata for a recording's assembled master.

        Also the finalize-on-read trigger, so this is what makes the master exist. Returns at
        least ``media_file_id``, ``duration_seconds`` and ``start_time_utc`` — the last being the
        recorder's own clock at its first frame, which is the anchor for mapping a transcript
        moment onto an offset in the media.
        """
        raise NotImplementedError()

    async def list_recording_chunks(
        self, recording_id: int, media_file_id: int, after_seq: int = -1
    ) -> dict[str, Any]:
        """The per-part index for a media file: ``{chunks: [...], complete: bool, ...}``.

        ``after_seq`` returns only parts newer than a given seq, so a consumer mirroring the
        recording can poll cheaply. Readable while the recording is still in progress, which is
        what lets a copy be built during the meeting rather than after it.
        """
        raise NotImplementedError()

    async def get_recording_chunk(
        self, recording_id: int, media_file_id: int, chunk_seq: int
    ) -> tuple[bytes, Optional[str]]:
        """One part's bytes plus its advertised sha256, so the caller can verify what it got."""
        raise NotImplementedError()

    async def get_recording_media_raw(
        self, recording_id: int, media_file_id: int, media_type: str = "audio"
    ) -> bytes:
        """The ASSEMBLED master's bytes for one media file.

        The counterpart to ``get_recording_master``, which returns only metadata. Used for the
        audio stream, which is fetched whole once the meeting is over rather than part-by-part:
        it is a fraction of the video's size, and it is only needed at the moment the two streams
        are muxed together.
        """
        raise NotImplementedError()

    async def delete_recording(self, recording_id: int) -> dict[str, Any]:
        """Purge one recording's media and its record, leaving the meeting and its transcript."""
        raise NotImplementedError()

    def register_meeting_id_mapping(
        self, internal_id: int, platform: str, native_meeting_id: str
    ) -> None:
        """Register a mapping from internal meeting ID to platform:native_id.

        This is used for recovery when resubscribing to active meetings.
        """
        pass

    async def close(self):
        """Clean up any resources."""
        pass


def get_transcription_provider() -> TranscriptionProviderBase:
    """Factory function to get the configured transcription provider."""
    provider_type = os.getenv("TRANSCRIPTION_PROVIDER", "vexa")

    if provider_type == "vexa":
        from dna.transcription_providers.vexa import VexaTranscriptionProvider

        return VexaTranscriptionProvider()

    raise ValueError(f"Unknown transcription provider: {provider_type}")
