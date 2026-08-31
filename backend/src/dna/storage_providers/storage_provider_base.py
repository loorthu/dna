"""Storage Provider Base.

Abstract base class for storage providers and factory function.
"""

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dna.models.draft_note import DraftNote, DraftNoteUpdate
    from dna.models.playlist_metadata import PlaylistMetadata, PlaylistMetadataUpdate
    from dna.models.published_transcript import (
        PublishedTranscript,
        PublishedTranscriptUpdate,
    )
    from dna.models.qc_check import NoteQCCheck, NoteQCCheckCreate, NoteQCCheckUpdate
    from dna.models.stored_segment import StoredSegment, StoredSegmentCreate
    from dna.models.user_settings import UserSettings, UserSettingsUpdate


class StorageProviderBase:
    """Abstract base class for storage providers."""

    async def get_draft_notes_for_version(
        self, playlist_id: int, version_id: int
    ) -> list["DraftNote"]:
        """Get all draft notes for a playlist/version (all users)."""
        raise NotImplementedError()

    async def get_draft_notes_for_playlist(self, playlist_id: int) -> list["DraftNote"]:
        """Get all draft notes for a playlist (all users, all versions)."""
        raise NotImplementedError()

    async def get_draft_note(
        self, user_email: str, playlist_id: int, version_id: int
    ) -> Optional["DraftNote"]:
        """Get a draft note by composite key (user_email, playlist_id, version_id)."""
        raise NotImplementedError()

    async def upsert_draft_note(
        self,
        user_email: str,
        playlist_id: int,
        version_id: int,
        data: "DraftNoteUpdate",
    ) -> "DraftNote":
        """Create or update a draft note."""
        raise NotImplementedError()

    async def upsert_published_note(
        self,
        user_email: str,
        playlist_id: int,
        version_id: int,
        data: "DraftNoteUpdate",
    ) -> "DraftNote":
        """Upsert a published note (sync from ShotGrid)."""
        raise NotImplementedError()

    async def delete_draft_note(
        self, user_email: str, playlist_id: int, version_id: int
    ) -> bool:
        """Delete a draft note. Returns True if deleted."""
        raise NotImplementedError()

    async def get_playlist_metadata(
        self, playlist_id: int
    ) -> Optional["PlaylistMetadata"]:
        """Get playlist metadata by playlist ID."""
        raise NotImplementedError()

    async def get_playlist_metadata_by_vexa_meeting_id(
        self, vexa_meeting_id: int
    ) -> Optional["PlaylistMetadata"]:
        """The playlist for a specific Vexa meeting.

        Unambiguous, unlike the lookup by native meeting id below: a meeting ROOM is reused across
        playlists, so that one returns an arbitrary match among them. A Vexa meeting is one
        meeting, and only one playlist dispatched it.
        """
        raise NotImplementedError()

    async def get_playlist_metadata_by_meeting_id(
        self, meeting_id: str
    ) -> Optional["PlaylistMetadata"]:
        """Get playlist metadata by meeting ID (reverse lookup)."""
        raise NotImplementedError()

    async def upsert_playlist_metadata(
        self, playlist_id: int, data: "PlaylistMetadataUpdate"
    ) -> "PlaylistMetadata":
        """Create or update playlist metadata."""
        raise NotImplementedError()

    async def delete_playlist_metadata(self, playlist_id: int) -> bool:
        """Delete playlist metadata. Returns True if deleted."""
        raise NotImplementedError()

    async def list_playlists_pending_archive(self, limit: int = 25) -> list[int]:
        """Playlists whose meeting media has not been archived yet, newest first.

        "Not archived" is the absence of a network path, which is exactly the condition that
        keeps the upstream copy undeletable — so this is the collector's work queue, expressed as
        the same fact the delete guard turns on rather than as a second piece of bookkeeping that
        could disagree with it.
        """
        raise NotImplementedError()

    async def upsert_segment(
        self,
        playlist_id: int,
        version_id: int,
        segment_id: str,
        data: "StoredSegmentCreate",
    ) -> tuple["StoredSegment", bool]:
        """Create or update a segment. Returns (segment, is_new)."""
        raise NotImplementedError()

    async def get_segments_for_version(
        self, playlist_id: int, version_id: int
    ) -> list["StoredSegment"]:
        """Get all segments for a version, ordered by start time."""
        raise NotImplementedError()

    async def list_playlists_pending_archive(
        self, limit: int = 25, site: Optional[str] = None
    ) -> list[int]:
        """Playlists whose current meeting still needs collecting, for ONE collector.

        ``site`` scopes the queue to the side that dispatched the meeting; None means the
        unrouted jobs. The two are exclusive, so two collectors are never handed the same work.
        """
        raise NotImplementedError()

    async def get_segments_for_playlist(
        self, playlist_id: int
    ) -> list["StoredSegment"]:
        """Every stored segment for a playlist, across all versions.

        The cut list is built per playlist rather than per version because a meeting's segments
        belong to whichever version was in review at the time, and the caller wants all of them
        in one pass — asking version by version would mean knowing the versions first.
        """
        raise NotImplementedError()

    async def delete_playlist_data(
        self, playlist_id: int, include_notes: bool = True
    ) -> dict[str, int]:
        """Forget everything this store holds about one playlist. Returns counts per collection.

        The segments a meeting produced had no way to be removed at all: the store could upsert
        and read them but never delete, so re-running an end-to-end test meant reaching into the
        database by hand. That is fine beside the backend and impossible from an air-gapped host,
        where the HTTP API is the only channel — hence one call that clears the whole playlist
        rather than a delete per collection the caller has to remember to chain.

        `include_notes` is separate because a draft note is the only one of these a person
        authored. Segments and metadata are machine-produced and always regenerable from a new
        meeting; an unpublished note is not.

        Deliberately scoped to this store. The production tracking system holds notes DNA only
        mirrors, and nothing here may reach into it.
        """
        raise NotImplementedError()

    async def get_user_settings(self, user_email: str) -> Optional["UserSettings"]:
        """Get user settings by email."""
        raise NotImplementedError()

    async def upsert_user_settings(
        self, user_email: str, data: "UserSettingsUpdate"
    ) -> "UserSettings":
        """Create or update user settings."""
        raise NotImplementedError()

    async def delete_user_settings(self, user_email: str) -> bool:
        """Delete user settings. Returns True if deleted."""
        raise NotImplementedError()

    async def get_published_transcript(
        self, playlist_id: int, version_id: int, meeting_id: str
    ) -> Optional["PublishedTranscript"]:
        """Get the published-transcript record for a (playlist, version, meeting)."""
        raise NotImplementedError()

    async def upsert_published_transcript(
        self, data: "PublishedTranscriptUpdate"
    ) -> "PublishedTranscript":
        """Create or update the published-transcript record.

        Upsert key is (playlist_id, version_id, meeting_id). A re-publish with a
        different body_hash overwrites the existing row rather than inserting.
        """
        raise NotImplementedError()

    async def get_qc_checks(self, user_email: str) -> list["NoteQCCheck"]:
        """List QC checks for a user; seeds default checks when none exist."""
        raise NotImplementedError()

    async def create_qc_check(
        self, user_email: str, data: "NoteQCCheckCreate"
    ) -> "NoteQCCheck":
        """Create a QC check."""
        raise NotImplementedError()

    async def update_qc_check(
        self, user_email: str, check_id: str, data: "NoteQCCheckUpdate"
    ) -> Optional["NoteQCCheck"]:
        """Update a QC check owned by the user. Returns None if not found."""
        raise NotImplementedError()

    async def delete_qc_check(self, user_email: str, check_id: str) -> bool:
        """Delete a QC check. Returns True if deleted."""
        raise NotImplementedError()


def get_storage_provider() -> StorageProviderBase:
    """Factory function to get the configured storage provider."""
    provider_type = os.getenv("STORAGE_PROVIDER", "mongodb")

    if provider_type == "mongodb":
        from dna.storage_providers.mongodb import MongoDBStorageProvider

        return MongoDBStorageProvider()

    raise ValueError(f"Unknown storage provider: {provider_type}")
