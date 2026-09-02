"""Request models for API endpoints."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class EntityLink(BaseModel):
    """Reference to an existing entity for linking."""

    type: str = Field(description="Entity type (e.g., 'Version', 'Playlist', 'Shot')")
    id: int = Field(description="Entity ID")


class CreateNoteRequest(BaseModel):
    """Request model for creating a new note."""

    subject: str = Field(description="Note subject line")
    content: Optional[str] = Field(default=None, description="Note body content")
    project: dict[str, Any] = Field(
        description="Project reference (e.g., {'type': 'Project', 'id': 85})"
    )
    note_links: Optional[list[EntityLink]] = Field(
        default=None, description="Entities to link this note to"
    )


class AddVersionsToPlaylistRequest(BaseModel):
    """Request model for appending versions to a playlist, by external review id."""

    jts: list[int] = Field(
        min_length=1,
        max_length=200,
        description=(
            "The versions to add, by the id the review tool announces for them — the JTS at "
            "SPI, whichever field PRODTRACK_VERSION_EXTERNAL_REF_FIELD names elsewhere. A list, "
            "because a review is assembled from a list of them pasted in one go; they are "
            "appended in the order given, and repeats are ignored."
        ),
    )


class AddVersionOutcome(BaseModel):
    """What became of one requested id. Some of a pasted list land and some do not."""

    jts: int = Field(description="The external review id that was asked for")
    status: str = Field(
        description="added | already_in_playlist | not_found",
    )
    version_id: Optional[int] = Field(
        default=None, description="The version it resolved to, when it resolved to one"
    )
    version_name: Optional[str] = Field(
        default=None, description="That version's name, so the answer is legible"
    )


class AddVersionsToPlaylistResponse(BaseModel):
    """Response model for appending versions to a playlist."""

    outcomes: list[AddVersionOutcome] = Field(
        description="One per requested id, in the order they were given"
    )
    added_count: int = Field(description="How many versions the playlist gained")


class FilterCondition(BaseModel):
    """A single filter condition for entity queries."""

    field: str = Field(description="DNA field name to filter on")
    operator: str = Field(description="Filter operator (e.g., 'is', 'contains', 'in')")
    value: Any = Field(description="Value to filter by")


class FindRequest(BaseModel):
    """Request model for finding entities."""

    entity_type: str = Field(
        description="DNA entity type to search (e.g., 'project', 'shot', 'version')"
    )
    filters: list[FilterCondition] = Field(
        default_factory=list, description="List of filter conditions"
    )


class GenerateNoteRequest(BaseModel):
    """Request model for generating an AI note suggestion."""

    playlist_id: int = Field(description="Playlist ID")
    version_id: int = Field(description="Version ID")
    user_email: str = Field(description="User email address")
    additional_instructions: Optional[str] = Field(
        default=None,
        description="Optional additional instructions to append to the prompt",
    )


class GenerateNoteResponse(BaseModel):
    """Response model for AI note generation."""

    suggestion: str = Field(description="The generated note suggestion")
    prompt: str = Field(description="The full prompt with values substituted")
    context: str = Field(description="The version context used for generation")


class SearchRequest(BaseModel):
    """Request model for unified entity search."""

    query: str = Field(description="Text to search for (searches name field)")
    entity_types: list[str] = Field(
        description="Entity types to search: user, shot, asset, version, task, playlist"
    )
    project_id: Optional[int] = Field(
        default=None,
        description="Scope results to a specific project (recommended for non-user entities)",
    )
    limit: int = Field(
        default=10, description="Max results per entity type (default: 10)"
    )


class SearchResult(BaseModel):
    """Lightweight entity representation for search results."""

    type: str = Field(description="Entity type (e.g., 'User', 'Shot', 'Asset')")
    id: int = Field(description="Entity ID")
    name: str = Field(description="Entity name")
    description: Optional[str] = Field(
        default=None, description="Entity description (for shots/assets/versions)"
    )
    email: Optional[str] = Field(default=None, description="Email (for users)")
    project: Optional[dict[str, Any]] = Field(
        default=None, description="Project reference (for project-scoped entities)"
    )


class StatusOption(BaseModel):
    """A status option from ShotGrid schema."""

    code: str = Field(description="Status code (e.g., 'rev', 'apr', 'rej')")
    name: str = Field(description="Display name (e.g., 'Pending Review', 'Approved')")


class PublishNoteTarget(BaseModel):
    """A single draft note to publish (user + version key)."""

    user_email: str
    version_id: int


class PublishNotesRequest(BaseModel):
    """Request model for publishing draft notes."""

    user_email: str
    targets: list[PublishNoteTarget] = Field(
        description="Only draft notes matching these (user_email, version_id) pairs are published."
    )


class PublishNotesResponse(BaseModel):
    """Response model for publishing draft notes."""

    published_count: int
    republished_count: int
    skipped_count: int
    failed_count: int
    total: int


class PublishTranscriptRequest(BaseModel):
    """Request to publish a version's captured transcript."""

    version_id: int = Field(description="Version whose segments to publish")


class PublishTranscriptResponse(BaseModel):
    """Response from the publish-transcript endpoint."""

    transcript_entity_id: int = Field(
        description="Entity ID of the row in the tracking system"
    )
    outcome: str = Field(description="created | updated | skipped")
    skipped_reason: Optional[str] = None
    segments_count: int


class EmailNotesRequest(BaseModel):
    """Request model for emailing notes for a playlist."""

    to: str = Field(description="Recipient email address(es), comma-separated")
    cc: Optional[str] = Field(
        default=None, description="CC email address(es), comma-separated"
    )
    subject: Optional[str] = Field(
        default=None, description="Email subject (auto-generated if omitted)"
    )
    sent_by: str = Field(description="Display name or email of the person sending")


class RecordingBlockedRequest(BaseModel):
    """The collector reporting that it cannot archive a recording without someone acting.

    Only for what a retry will never clear on its own — today, a show whose recording directory
    does not exist on the share. Transient failures are retried silently; a reason that appears
    and clears by itself would flicker in front of a viewer who can do nothing with it.
    """

    reason: str = Field(
        ...,
        max_length=500,
        description="What is wrong, in words the person who can fix it will recognise. Shown in "
        "the player, so it names the directory relative to the share root rather than the "
        "archiving host's absolute path.",
    )


class RecordingArchiveRequest(BaseModel):
    """The collector declaring where it durably archived a playlist's recording.

    Recording this is what later permits purging the upstream copy; until it exists, deletion is
    refused. The hash is the collector's own, computed over the file it wrote.
    """

    network_path: str = Field(
        ...,
        description="Path of the archived media RELATIVE to the root the player is served from "
        "— the collector's configured archive directory, plus the `<YYYYMMDD>/<name>.mp4` that "
        "GET /recordings/{playlist_id}/archive-name supplied. Not absolute: the mount point "
        "belongs to the archiving host, which is across the airgap and holds the only copy, so "
        "its layout should not be recorded here. An absolute path is still accepted from an "
        "older collector and reduced to its basename.",
    )
    sha256: str = Field(..., description="sha256 of the archived file")
    recording_id: Optional[int] = Field(
        default=None,
        description="The Vexa recording the collector mirrored. Optional, but when supplied it "
        "must match what the playlist currently resolves to — a mismatch means the two ends are "
        "looking at different recordings, and is refused with 409 rather than recorded.",
    )
