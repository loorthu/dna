"""Models for the artist-facing review page.

A read-only projection, deliberately not the shapes the coordinator app uses. The reviewing tool
sends a version, its draft rows, its segments and its cut list separately because it edits each of
them; the artist page edits nothing and renders a whole playlist at once, so sending it the same
way would be one request per shot per kind — around ninety for a thirty-shot dailies — to build a
page that never changes after it loads.

The projection also decides what an artist is shown, in one place. Notes arrive here already
filtered to the ones people wrote in DNA and already carrying a display name, so no caller has to
remember either rule.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewNote(BaseModel):
    """One person's note on one shot, as an artist reads it."""

    author_email: str = Field(description="Mailbox the note was written from")
    author_name: str = Field(
        description="Display name derived from the mailbox, for the byline"
    )
    subject: str = ""
    content: str = ""
    published: bool = Field(
        default=False,
        description="Whether this note has been pushed to the production tracker",
    )
    updated_at: Optional[datetime] = None


class ReviewTranscriptLine(BaseModel):
    """One transcribed utterance filed against a shot."""

    speaker: Optional[str] = None
    text: str = ""
    absolute_start_time: Optional[str] = Field(
        default=None, description="UTC timestamp (ISO 8601) of the utterance"
    )
    start_time: Optional[float] = Field(
        default=None, description="Seconds from the start of the meeting"
    )


class ReviewCut(BaseModel):
    """A span of the meeting recording that discussed this shot."""

    video_in_seconds: float
    video_out_seconds: float


class ReviewShot(BaseModel):
    """One row of the playlist, with everything said about it."""

    version_id: int
    anchor: str = Field(
        description="Fragment identifier for this shot, unique within the playlist"
    )
    index: int = Field(description="1-based position in the playlist, as screened")
    name: str = ""
    entity_name: str = ""
    task_name: str = ""
    artist_name: str = ""
    status: str = ""
    thumbnail: Optional[str] = None
    frame_path: str = ""
    created_at: Optional[str] = None
    prodtrack_detail_url: Optional[str] = None
    notes: list[ReviewNote] = Field(default_factory=list)
    transcript: list[ReviewTranscriptLine] = Field(default_factory=list)
    cuts: list[ReviewCut] = Field(default_factory=list)


class ReviewRecording(BaseModel):
    """Where the meeting recording is, and why it might not be there yet.

    `status` carries the same enum the coordinator's player uses, plus `disabled` for a deployment
    with no recording pipeline at all — the artist page has no capabilities call of its own, and
    one field that already distinguishes six kinds of nothing may as well distinguish seven.
    """

    status: str
    media_url: Optional[str] = None
    duration_seconds: Optional[float] = None


class ReviewPlaylist(BaseModel):
    """The whole artist-facing page, in one response."""

    playlist_id: int
    playlist_name: str = ""
    project_id: Optional[int] = None
    project_name: str = ""
    project_code: str = ""
    url_path: str = Field(description="Canonical path for this page")
    screened_at: Optional[str] = Field(
        default=None,
        description="When the playlist was created, as a stand-in for its screening",
    )
    recording: ReviewRecording
    shots: list[ReviewShot] = Field(default_factory=list)


class ReviewLink(BaseModel):
    """Where the artist page for a playlist is, and the fragment for each shot in it.

    What the reviewing tool needs to offer "open the artist view" beside its production-tracking
    button, and nothing else — no notes, no transcript, no cut list. It is asked for rather than
    computed in the browser because slugging is lossy and the page, the notes email and this
    button must all agree on the result; a second implementation in TypeScript would agree right
    up until one of them changed.

    Every shot's anchor arrives at once so moving between versions does not re-ask: the answer is
    about the playlist, and the coordinator walks its versions one at a time.
    """

    playlist_id: int
    url_path: str = Field(description="Canonical path for this playlist's review page")
    anchors: dict[int, str] = Field(
        default_factory=dict, description="Fragment identifier per version id"
    )


class ReviewPlaylistRef(BaseModel):
    """A playlist a name-shaped URL could have meant."""

    playlist_id: int
    playlist_name: str = ""
    url_path: str
    created_at: Optional[str] = None
    version_count: Optional[int] = None


class ReviewResolution(BaseModel):
    """What a `/review/<project>/<name>` address resolved to.

    Ambiguity is an answer rather than an error: a show that runs "Dailies" every day has several
    playlists with one name, and the person who followed the link needs to be shown which ones
    rather than told the link is broken.
    """

    playlist_id: Optional[int] = None
    matches: list[ReviewPlaylistRef] = Field(default_factory=list)
