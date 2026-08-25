"""Transcription Models.

Pydantic models for transcription bot sessions and events.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    """Supported meeting platforms."""

    GOOGLE_MEET = "google_meet"
    TEAMS = "teams"


class BotStatusEnum(str, Enum):
    """Bot lifecycle status values."""

    IDLE = "idle"
    JOINING = "joining"
    WAITING_ROOM = "waiting_room"
    IN_CALL = "in_call"
    TRANSCRIBING = "transcribing"
    FAILED = "failed"
    STOPPED = "stopped"
    COMPLETED = "completed"


class DispatchBotRequest(BaseModel):
    """Request to dispatch a bot to a meeting."""

    platform: Platform
    meeting_id: str = Field(..., description="Native meeting ID for the platform")
    playlist_id: int = Field(
        ..., description="Playlist ID to associate with this meeting"
    )
    passcode: Optional[str] = Field(
        default=None, description="Passcode for Teams meetings"
    )
    bot_name: Optional[str] = Field(default=None, description="Custom name for the bot")
    language: Optional[str] = Field(default=None, description="Transcription language")
    authenticated: bool = Field(
        default=True,
        description="Join as authenticated user via active browser_session",
    )
    recording_enabled: bool = Field(
        default=False,
        description="Record the meeting's video as well as transcribing it. Opt-in per meeting: "
        "a recording is a few hundred MB and a copy of the room, so it is asked for rather than "
        "assumed. ALWAYS sent to Vexa, never omitted — leaving it out would hand the decision to "
        "a deployment default on the Vexa host, which is a setting nobody looking at DNA can see.",
    )


class BotStatus(BaseModel):
    """Current status of a transcription bot."""

    platform: Platform
    meeting_id: str
    status: BotStatusEnum
    message: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    saving_segments: Optional[bool] = Field(
        default=None,
        description="Whether arriving segments are being stored, or None when the status was "
        "read without a playlist to check against. False means the bot is working and the "
        "transcript is being discarded — see BotSession.saving_segments.",
    )
    warnings: list[str] = Field(default_factory=list)


class BotSession(BaseModel):
    """Represents an active or completed bot session."""

    platform: Platform
    meeting_id: str
    playlist_id: int
    status: BotStatusEnum
    vexa_meeting_id: Optional[int] = None
    bot_name: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    recording_enabled: bool = Field(
        default=False,
        description="Whether this meeting is being RECORDED, as resolved by Vexa rather than as "
        "requested — a deployment that ignored the request must not leave the caller believing "
        "a recording is being made.",
    )
    saving_segments: bool = Field(
        default=True,
        description="Whether arriving segments are being stored. False when the playlist has no "
        "version in review: the bot still joins and Vexa still transcribes, but DNA has nowhere "
        "to put the segments and drops them. Reported so a caller is not left reading a healthy "
        "status while the transcript is going nowhere.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Machine-readable notes about this session that are not failures. "
        "`no_version_in_review` is the one that matters: everything works and nothing is kept.",
    )


class TranscriptSegment(BaseModel):
    """A single segment of transcribed speech."""

    text: str
    speaker: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Transcript(BaseModel):
    """Full transcript for a meeting."""

    platform: Platform
    meeting_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: Optional[str] = None
    duration: Optional[float] = None
