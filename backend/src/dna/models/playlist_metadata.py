"""Playlist Metadata Models.

Pydantic models for playlist metadata stored in the storage provider.
"""

from datetime import datetime
from typing import Any, Optional

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
    clear_in_review: bool = Field(
        default=False,
        description="If True, unsets in_review. A flag rather than a None assignment because the "
        "upsert reads None as 'leave unchanged'. Used when a meeting ends: the mark says where "
        "arriving segments belong, and once the meeting is over it belongs to nothing — leaving "
        "it set silently attributes the NEXT meeting's opening remarks to a version from the "
        "last one.",
    )
    # ── recording (the meeting's media, produced by the bot and archived by the collector) ──
    collector_site: Optional[str] = Field(
        default=None,
        description="Which side dispatched this meeting, and therefore whose collector should "
        "archive it. Inferred from the peer that made the dispatch — the front end's own proxy, "
        "which runs on the same host as its collector. None means unrouted, and is offered only "
        "to a collector that also declares no site, so no two collectors can be handed the same "
        "job.",
    )
    recording_enabled: Optional[bool] = Field(
        default=None,
        description="Whether the CURRENT meeting is being recorded, as Vexa resolved it at "
        "dispatch. Written in the same upsert as vexa_meeting_id, so it always describes that "
        "meeting rather than some earlier one.\n\n"
        "False switches the whole recording path off for this playlist: it leaves the collector's "
        "queue, the media relay reports nothing to relay, and the cut list answers without asking "
        "Vexa. None means unknown — a meeting dispatched before this was recorded — and is "
        "treated as 'might have one', which is the old behaviour.",
    )
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
        description="The archived file's path RELATIVE to the share root — "
        "`<show>/lib.recording/pix/ref/dna/<YYYYMMDD>/<name>.mp4`. Never absolute: the mount point "
        "belongs to the archiving host across the airgap. Its presence is what permits deleting "
        "the upstream copy; the player turns it into a URL under /recordings/, which nginx "
        "aliases onto that same root. Rows written before the archives were filed by show and "
        "date hold a bare filename instead, and no longer resolve under the new root.",
    )
    recording_sha256: Optional[str] = Field(
        default=None,
        description="sha256 of the archived file, as computed by the collector",
    )
    archived_meeting_id: Optional[int] = Field(
        default=None,
        description="The Vexa meeting whose recording the archive holds. Compared against the "
        "playlist's CURRENT vexa_meeting_id to decide whether there is new work: a playlist that "
        "hosts a second meeting becomes collectable again, instead of looking done forever.",
    )
    archived_recording_id: Optional[int] = Field(
        default=None,
        description="The Vexa recording the archive holds. Survives clear_recording_link (which "
        "clears the resolution CACHE, a different thing) because it is the record of what was "
        "archived, and it names the file on disk.",
    )
    recording_link_meeting_id: Optional[int] = Field(
        default=None,
        description="The meeting vexa_recording_id/recording_media_file_id were resolved for. "
        "The cache is only trusted while this matches vexa_meeting_id — otherwise a playlist "
        "whose collection never finished would keep serving the PREVIOUS meeting's recording.",
    )
    recording_archive_error: Optional[str] = Field(
        default=None,
        description="Why the collector cannot archive this recording, in the collector's own "
        "words, when the reason needs a PERSON rather than another attempt — today that means "
        "the show's recording directory does not exist on the share.\n\n"
        "Recorded so the wait has a reason attached to it. Without it the player says 'still "
        "being collected' forever, which is indistinguishable from a slow collection and gives "
        "nobody the one fact that would resolve it. Cleared the moment an archive is recorded.",
    )
    clear_recording_archive_error: bool = Field(
        default=False,
        description="If True, unsets recording_archive_error. A flag rather than a None "
        "assignment because the upsert reads None as 'leave unchanged', so a blocked recording "
        "that later archived fine would keep advertising the old reason.",
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
    in_review_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Append-only record of the in-review mark, oldest first, each entry "
        "{version_id, since}. A segment is attributed by when it was SPOKEN, and Vexa confirms "
        "segments seconds later — so `in_review` alone cannot answer what was true when the words "
        "were said, and everything said just before a reviewer moves on lands on the wrong shot. "
        "A null version_id is a real entry: it records the mark being cleared.",
    )
    meeting_id: Optional[str] = None
    platform: Optional[str] = None
    vexa_meeting_id: Optional[int] = None
    transcription_paused: bool = False
    transcription_resumed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when transcription was last resumed. "
        "Segments with start time before this are discarded.",
    )
    collector_site: Optional[str] = None
    recording_enabled: Optional[bool] = None
    vexa_recording_id: Optional[int] = None
    recording_media_file_id: Optional[int] = None
    recording_start_time_utc: Optional[str] = None
    recording_duration_seconds: Optional[float] = None
    recording_network_path: Optional[str] = None
    recording_sha256: Optional[str] = None
    archived_meeting_id: Optional[int] = None
    archived_recording_id: Optional[int] = None
    recording_link_meeting_id: Optional[int] = None
    recording_archive_error: Optional[str] = None
