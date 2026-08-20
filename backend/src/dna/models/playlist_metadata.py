"""Playlist Metadata Models.

Pydantic models for playlist metadata stored in the storage provider.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PlaylistMetadataUpdate(BaseModel):
    """Model for updating playlist metadata."""

    in_review: Optional[int] = Field(
        default=None, description="Version ID currently in review"
    )
    meeting_id: Optional[str] = Field(default=None, description="Associated meeting ID")
    platform: Optional[str] = Field(default=None, description="Meeting platform")
    vexa_meeting_id: Optional[int] = Field(
        default=None, description="Internal Vexa meeting ID"
    )
    transcription_paused: Optional[bool] = Field(
        default=None, description="Whether transcription storage is paused"
    )
    clear_resumed_at: bool = Field(
        default=False,
        description="If True, clears transcription_resumed_at. "
        "Used when starting a new transcription session.",
    )
    # ── recording (the meeting's media, produced by the bot and archived by the collector) ──
    vexa_recording_id: Optional[int] = Field(
        default=None, description="Vexa recording holding this meeting's media"
    )
    recording_media_file_id: Optional[int] = Field(
        default=None, description="The video media file within that recording"
    )
    recording_start_time_utc: Optional[str] = Field(
        default=None,
        description="The recorder's own clock at its first frame. The anchor that maps a "
        "transcript wall-clock moment onto an offset in the media — NOT the upload time.",
    )
    recording_duration_seconds: Optional[float] = Field(
        default=None, description="Length of the recorded media, in seconds"
    )
    recording_network_path: Optional[str] = Field(
        default=None,
        description="Where the collector archived the assembled file. Its presence is what "
        "permits deleting the upstream copy.",
    )
    recording_sha256: Optional[str] = Field(
        default=None,
        description="sha256 of the archived file, as computed by the collector",
    )
    clear_recording_link: bool = Field(
        default=False,
        description="If True, unsets vexa_recording_id + recording_media_file_id. Needed because "
        "the upsert treats None as 'leave unchanged', so the ids cannot be cleared by assignment "
        "— and after the upstream copy is purged they would otherwise point at a deleted "
        "recording. The archive path and hash are deliberately KEPT: they are where the media is.",
    )


class PlaylistMetadata(BaseModel):
    """Full playlist metadata model with all fields."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    playlist_id: int
    in_review: Optional[int] = None
    meeting_id: Optional[str] = None
    platform: Optional[str] = None
    vexa_meeting_id: Optional[int] = None
    transcription_paused: bool = False
    transcription_resumed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when transcription was last resumed. "
        "Segments with start time before this are discarded.",
    )
    vexa_recording_id: Optional[int] = None
    recording_media_file_id: Optional[int] = None
    recording_start_time_utc: Optional[str] = None
    recording_duration_seconds: Optional[float] = None
    recording_network_path: Optional[str] = None
    recording_sha256: Optional[str] = None
