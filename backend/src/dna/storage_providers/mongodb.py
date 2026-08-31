"""MongoDB Storage Provider.

MongoDB implementation of the storage provider interface using PyMongo's native async API.
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import AsyncMongoClient, ReturnDocument

from dna.in_review_timeline import append_to_history
from dna.models.draft_note import DraftNote, DraftNoteUpdate
from dna.models.playlist_metadata import PlaylistMetadata, PlaylistMetadataUpdate
from dna.models.published_transcript import (
    PublishedTranscript,
    PublishedTranscriptUpdate,
)
from dna.models.qc_check import (
    DEFAULT_ACTION_ITEM_CHECK,
    NoteQCCheck,
    NoteQCCheckCreate,
    NoteQCCheckUpdate,
)
from dna.models.stored_segment import StoredSegment, StoredSegmentCreate
from dna.models.user_settings import UserSettings, UserSettingsUpdate
from dna.storage_providers.storage_provider_base import StorageProviderBase


class MongoDBStorageProvider(StorageProviderBase):
    """MongoDB implementation of the storage provider."""

    def __init__(self) -> None:
        self._client: Optional[AsyncMongoClient[Any]] = None
        self._indexes_ensured = False

    async def ensure_indexes(self) -> None:
        """Create collection indexes. Idempotent; safe to call on every startup.

        The compound unique index on the `segments` upsert key makes
        `upsert_segment` O(log n) instead of a full-collection scan — at
        Vexa's refine-heavy write rate, scans become user-visible at ~100k
        segments and timeouts at ~1M.
        """
        if self._indexes_ensured:
            return
        await self.segments_collection.create_index(
            [("segment_id", 1), ("playlist_id", 1), ("version_id", 1)],
            unique=True,
            name="segments_upsert_key",
        )
        await self.segments_collection.create_index(
            [("playlist_id", 1), ("version_id", 1), ("absolute_start_time", 1)],
            name="segments_list_by_version",
        )
        await self.qc_checks_collection.create_index(
            [("user_email", 1)],
            name="qc_checks_by_user",
        )
        self._indexes_ensured = True

    @property
    def client(self) -> AsyncMongoClient[Any]:
        if self._client is None:
            mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
            self._client = AsyncMongoClient(mongo_url)
        return self._client

    @property
    def db(self) -> Any:
        return self.client.dna

    @property
    def draft_notes(self) -> Any:
        return self.db.draft_notes

    @property
    def playlist_metadata_collection(self) -> Any:
        return self.db.playlist_metadata

    @property
    def segments_collection(self) -> Any:
        return self.db.segments

    @property
    def user_settings_collection(self) -> Any:
        return self.db.user_settings

    @property
    def published_transcripts_collection(self) -> Any:
        return self.db.published_transcripts

    @property
    def qc_checks_collection(self) -> Any:
        return self.db.qc_checks

    def _build_query(
        self, user_email: str, playlist_id: int, version_id: int
    ) -> dict[str, Any]:
        """Build the composite key query."""
        return {
            "user_email": user_email,
            "playlist_id": playlist_id,
            "version_id": version_id,
        }

    async def get_draft_notes_for_version(
        self, playlist_id: int, version_id: int
    ) -> list[DraftNote]:
        """Get all draft notes for a playlist/version (all users)."""
        query = {"playlist_id": playlist_id, "version_id": version_id}
        cursor = self.draft_notes.find(query)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(DraftNote(**doc))
        return results

    async def get_draft_notes_for_playlist(self, playlist_id: int) -> list[DraftNote]:
        """Get all draft notes for a playlist (all users, all versions)."""
        query = {"playlist_id": playlist_id}
        cursor = self.draft_notes.find(query)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(DraftNote(**doc))
        return results

    async def get_draft_note(
        self, user_email: str, playlist_id: int, version_id: int
    ) -> Optional[DraftNote]:
        query = {
            **self._build_query(user_email, playlist_id, version_id),
        }
        doc = await self.draft_notes.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
            return DraftNote(**doc)
        return None

    async def upsert_draft_note(
        self, user_email: str, playlist_id: int, version_id: int, data: DraftNoteUpdate
    ) -> DraftNote:
        now = datetime.now(timezone.utc)
        query = {
            **self._build_query(user_email, playlist_id, version_id),
        }

        update_data = data.model_dump(exclude_none=True)
        set_on_insert = {
            "created_at": now,
            "user_email": user_email,
            "playlist_id": playlist_id,
            "version_id": version_id,
        }
        if "published" not in update_data:
            update_data["published"] = False
        # Every caller of this is someone acting in DNA — writing a note, or publishing one — so
        # the row is DNA's from here on. Set, not set-on-insert: the sync may already have made
        # this row to mirror an upstream note (ShotGrid seeds an empty one per version, under the
        # playlist owner's name, on the same user/playlist/version key), and a person writing
        # over that has made it theirs. One way only; `upsert_published_note` never sets it back.
        update_data["origin"] = "dna"

        update: dict[str, Any] = {
            "$set": {**update_data, "updated_at": now},
            "$setOnInsert": set_on_insert,
        }
        result = await self.draft_notes.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return DraftNote(**result)

    async def upsert_published_note(
        self, user_email: str, playlist_id: int, version_id: int, data: DraftNoteUpdate
    ) -> DraftNote:
        now = datetime.now(timezone.utc)
        # Query for the note (same query as upsert_draft_note, no "published: True" filter)
        # This ensures we update the SAME record, not create a duplicate
        query = self._build_query(user_email, playlist_id, version_id)

        update_data = data.model_dump(exclude_none=True)
        set_on_insert = {
            "created_at": now,
            "user_email": user_email,
            "playlist_id": playlist_id,
            "version_id": version_id,
            # A mirror of a note that already existed upstream, not something anyone wrote here.
            # Insert only, so mirroring an upstream copy of a DNA note never disowns it.
            "origin": "prodtrack",
        }

        existing = await self.draft_notes.find_one(query)
        if existing:
            # If existing note has unpublished changes (published=False or edited=True),
            # do not overwrite it with the published version from sync.
            # This preserves local edits when re-fetching published notes.
            if not existing.get("published", True) or existing.get("edited", False):
                existing["_id"] = str(existing["_id"])
                return DraftNote(**existing)

        update: dict[str, Any] = {
            "$set": {**update_data, "updated_at": now},
            "$setOnInsert": set_on_insert,
        }
        result = await self.draft_notes.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return DraftNote(**result)

    async def delete_draft_note(
        self, user_email: str, playlist_id: int, version_id: int
    ) -> bool:
        query = self._build_query(user_email, playlist_id, version_id)
        result = await self.draft_notes.delete_one(query)
        return result.deleted_count > 0

    async def get_playlist_metadata(
        self, playlist_id: int
    ) -> Optional[PlaylistMetadata]:
        query = {"playlist_id": playlist_id}
        doc = await self.playlist_metadata_collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
            return PlaylistMetadata(**doc)
        return None

    async def get_playlist_metadata_by_vexa_meeting_id(
        self, vexa_meeting_id: int
    ) -> Optional[PlaylistMetadata]:
        """The one playlist that dispatched this Vexa meeting.

        A meeting ROOM is reused across playlists — five here share one — so looking up by native
        meeting id returns an arbitrary one of them. A Vexa meeting id identifies a single meeting,
        and exactly one playlist asked for it.
        """
        doc = await self.playlist_metadata_collection.find_one(
            {"vexa_meeting_id": vexa_meeting_id}
        )
        if doc:
            doc["_id"] = str(doc["_id"])
            return PlaylistMetadata(**doc)
        return None

    async def get_playlist_metadata_by_meeting_id(
        self, meeting_id: str
    ) -> Optional[PlaylistMetadata]:
        """A playlist using this meeting ROOM — ANY of them, if several do.

        Prefer `get_playlist_metadata_by_vexa_meeting_id` wherever the Vexa meeting is known.
        Recovering a live meeting through this one attributed a meeting to the wrong playlist and
        cleaned up its state instead.
        """
        query = {"meeting_id": meeting_id}
        doc = await self.playlist_metadata_collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
            return PlaylistMetadata(**doc)
        return None

    async def upsert_playlist_metadata(
        self, playlist_id: int, data: PlaylistMetadataUpdate
    ) -> PlaylistMetadata:
        query = {"playlist_id": playlist_id}
        update_fields = {
            k: v
            for k, v in data.model_dump().items()
            if v is not None
            and k not in ("clear_resumed_at", "clear_recording_link", "clear_in_review")
        }

        unset_fields: dict[str, Any] = {}

        # Record WHEN the mark moved, not just where it is now. Vexa confirms segments seconds
        # after the words are said, so a segment arriving now may have been spoken under the
        # previous mark; without this timeline there is no way to ask what was true back then, and
        # everything said in the last few seconds before a reviewer moves on lands on the shot
        # they moved to. `in_review` still holds the current mark — this is its history.
        marks_a_version = data.in_review is not None
        if marks_a_version or data.clear_in_review:
            existing = await self.playlist_metadata_collection.find_one(query)
            new_mark = None if data.clear_in_review else data.in_review
            if not (existing or {}).get("in_review_history") and (existing or {}).get(
                "in_review"
            ) not in (None, new_mark):
                # First change on a playlist that already had a mark: the timeline would otherwise
                # start midway and claim the earlier mark never applied. Nothing records when it
                # was set, so it is opened at the epoch — "since before anything we can ask about".
                update_fields["in_review_history"] = append_to_history(
                    [], existing["in_review"], datetime.min.replace(tzinfo=timezone.utc)
                )
            update_fields["in_review_history"] = append_to_history(
                update_fields.get("in_review_history")
                or (existing or {}).get("in_review_history"),
                new_mark,
                datetime.now(timezone.utc),
            )

        if data.clear_recording_link:
            unset_fields["vexa_recording_id"] = ""
            unset_fields["recording_media_file_id"] = ""
            # The meeting stamp belongs to the cache it qualifies, so it goes with it.
            # archived_meeting_id / archived_recording_id deliberately stay: they record what
            # was archived, which outlives the upstream copy being purged.
            unset_fields["recording_link_meeting_id"] = ""

        if data.clear_in_review:
            unset_fields["in_review"] = ""

        if data.clear_resumed_at:
            unset_fields["transcription_resumed_at"] = ""
        elif data.transcription_paused is False:
            existing = await self.playlist_metadata_collection.find_one(query)
            if existing and existing.get("transcription_paused", False):
                update_fields["transcription_resumed_at"] = datetime.now(timezone.utc)

        update: dict[str, Any] = {
            "$set": update_fields,
            "$setOnInsert": {"playlist_id": playlist_id},
        }
        if unset_fields:
            update["$unset"] = unset_fields

        result = await self.playlist_metadata_collection.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return PlaylistMetadata(**result)

    async def delete_playlist_metadata(self, playlist_id: int) -> bool:
        query = {"playlist_id": playlist_id}
        result = await self.playlist_metadata_collection.delete_one(query)
        return result.deleted_count > 0

    async def list_playlists_pending_archive(
        self, limit: int = 25, site: Optional[str] = None
    ) -> list[int]:
        # A null path matches both "absent" and "explicitly null", so a playlist that never had a
        # recording and one whose archive is still in flight look the same here — which is right:
        # the collector cannot tell them apart either, and asking is cheap (a 404 it backs off on).
        cursor = (
            self.playlist_metadata_collection.find(
                {
                    "vexa_meeting_id": {"$ne": None},
                    # A meeting that was never recorded has no archive coming, ever. Without this
                    # it satisfies "has a meeting, has no archive" permanently: the collector asks
                    # it for a chunk index every poll, forever, and — since the queue is capped —
                    # a backlog of never-recorded meetings can crowd out real work.
                    # `$ne: False` deliberately keeps null/absent: a meeting dispatched before
                    # this was recorded is unknown, not known-absent.
                    "recording_enabled": {"$ne": False},
                    # Eligible while the archive on record is not THIS meeting's. Asking
                    # "is there any archive" instead made a playlist look done forever, so a
                    # second meeting on it was never collected. `$ne` on two fields needs $expr;
                    # a missing archived_meeting_id resolves to null and so never equals a real
                    # meeting id, which is the "never collected" case.
                    "$expr": {
                        "$ne": ["$archived_meeting_id", "$vexa_meeting_id"],
                    },
                    # Only this collector's own work. The two forms are exclusive by
                    # construction — a named site matches exactly itself, and an unsited
                    # collector gets exactly the unrouted jobs — so no playlist can ever be
                    # offered to two collectors at once. That is the fix for a real incident:
                    # two collectors mirrored one meeting in parallel and the loser was left
                    # with a partial it could never finish.
                    "collector_site": site if site else None,
                },
                {"playlist_id": 1},
            )
            # Vexa meeting ids increase monotonically, so this is "most recent first" without
            # needing a timestamp the metadata does not carry. It bounds the queue to the
            # meetings that could plausibly still be recording.
            .sort("vexa_meeting_id", -1).limit(limit)
        )
        return [doc["playlist_id"] async for doc in cursor]

    async def upsert_segment(
        self,
        playlist_id: int,
        version_id: int,
        segment_id: str,
        data: StoredSegmentCreate,
    ) -> tuple[StoredSegment, bool]:
        """Create or update a segment. Returns (segment, is_new)."""
        now = datetime.now(timezone.utc)
        query = {
            "segment_id": segment_id,
            "playlist_id": playlist_id,
            "version_id": version_id,
        }

        existing = await self.segments_collection.find_one(query)
        is_new = existing is None

        # `segment_id` is already in `data.model_dump()` — MongoDB rejects an
        # update that lists the same field in both `$set` and `$setOnInsert`.
        # `playlist_id`/`version_id` stay in `$setOnInsert` because they aren't
        # part of `StoredSegmentCreate` (they come from the enclosing context).
        update: dict[str, Any] = {
            "$set": {
                **data.model_dump(),
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "playlist_id": playlist_id,
                "version_id": version_id,
            },
        }

        result = await self.segments_collection.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return StoredSegment(**result), is_new

    async def get_segments_for_version(
        self, playlist_id: int, version_id: int
    ) -> list[StoredSegment]:
        """Get all segments for a version, ordered by start time."""
        query = {"playlist_id": playlist_id, "version_id": version_id}
        cursor = self.segments_collection.find(query).sort("absolute_start_time", 1)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(StoredSegment(**doc))
        return results

    async def get_segments_for_playlist(self, playlist_id: int) -> list[StoredSegment]:
        """Every segment for a playlist, ordered by version then start time.

        An index-prefix scan: `segments_list_by_version` is
        (playlist_id, version_id, absolute_start_time), so both the match and the ordering are
        served by the index that already exists for the per-version read.
        """
        query = {"playlist_id": playlist_id}
        cursor = self.segments_collection.find(query).sort(
            [("version_id", 1), ("absolute_start_time", 1)]
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(StoredSegment(**doc))
        return results

    async def delete_playlist_data(
        self, playlist_id: int, include_notes: bool = True
    ) -> dict[str, int]:
        """Delete a playlist's segments, metadata and (optionally) draft notes."""
        query = {"playlist_id": playlist_id}
        deleted = {
            "segments": (await self.segments_collection.delete_many(query)).deleted_count,
            "playlist_metadata": (
                await self.playlist_metadata_collection.delete_many(query)
            ).deleted_count,
            "draft_notes": 0,
        }
        if include_notes:
            deleted["draft_notes"] = (
                await self.draft_notes.delete_many(query)
            ).deleted_count
        return deleted

    async def get_user_settings(self, user_email: str) -> Optional[UserSettings]:
        """Get user settings by email."""
        query = {"user_email": user_email}
        doc = await self.user_settings_collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
            return UserSettings(**doc)
        return None

    async def upsert_user_settings(
        self, user_email: str, data: UserSettingsUpdate
    ) -> UserSettings:
        """Create or update user settings."""
        now = datetime.now(timezone.utc)
        query = {"user_email": user_email}
        update_fields = {
            k: v
            for k, v in data.model_dump(exclude_unset=True).items()
            if v is not None
        }
        defaults = {
            "note_prompt": "",
            "regenerate_on_version_change": False,
            "regenerate_on_transcript_update": False,
            "sync_prodtrack_tab_on_version_change": True,
            "prodtrack_page_type": "version",
        }
        set_on_insert = {
            "created_at": now,
            "user_email": user_email,
        }
        for key, value in defaults.items():
            if key not in update_fields:
                set_on_insert[key] = value
        update: dict[str, Any] = {
            "$set": {**update_fields, "updated_at": now},
            "$setOnInsert": set_on_insert,
        }
        result = await self.user_settings_collection.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return UserSettings(**result)

    async def delete_user_settings(self, user_email: str) -> bool:
        """Delete user settings. Returns True if deleted."""
        query = {"user_email": user_email}
        result = await self.user_settings_collection.delete_one(query)
        return result.deleted_count > 0

    async def get_published_transcript(
        self, playlist_id: int, version_id: int, meeting_id: str
    ) -> Optional[PublishedTranscript]:
        """Fetch the bookkeeping row for a previously published transcript."""
        query = {
            "playlist_id": playlist_id,
            "version_id": version_id,
            "meeting_id": meeting_id,
        }
        doc = await self.published_transcripts_collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
            return PublishedTranscript(**doc)
        return None

    async def upsert_published_transcript(
        self, data: PublishedTranscriptUpdate
    ) -> PublishedTranscript:
        """Insert or overwrite the bookkeeping row for a published transcript."""
        now = datetime.now(timezone.utc)
        query = {
            "playlist_id": data.playlist_id,
            "version_id": data.version_id,
            "meeting_id": data.meeting_id,
        }
        # Composite key only on insert; mutable fields go in $set.
        payload = data.model_dump()
        set_on_insert = {
            "playlist_id": payload.pop("playlist_id"),
            "version_id": payload.pop("version_id"),
            "meeting_id": payload.pop("meeting_id"),
            "created_at": now,
        }
        update: dict[str, Any] = {
            "$set": {**payload, "updated_at": now},
            "$setOnInsert": set_on_insert,
        }
        result = await self.published_transcripts_collection.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        result["_id"] = str(result["_id"])
        return PublishedTranscript(**result)

    async def get_qc_checks(self, user_email: str) -> list[NoteQCCheck]:
        query = {"user_email": user_email}
        cursor = self.qc_checks_collection.find(query)
        results: list[NoteQCCheck] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(NoteQCCheck(**doc))
        if results:
            return sorted(results, key=lambda c: (c.name.lower(), c.id))
        now = datetime.now(timezone.utc)
        default = DEFAULT_ACTION_ITEM_CHECK
        await self.qc_checks_collection.find_one_and_update(
            {"user_email": user_email, "name": default.name},
            {
                "$setOnInsert": {
                    "user_email": user_email,
                    "name": default.name,
                    "prompt": default.prompt,
                    "severity": default.severity,
                    "enabled": default.enabled,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        cursor = self.qc_checks_collection.find(query)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(NoteQCCheck(**doc))
        return sorted(results, key=lambda c: (c.name.lower(), c.id))

    async def create_qc_check(
        self, user_email: str, data: NoteQCCheckCreate
    ) -> NoteQCCheck:
        now = datetime.now(timezone.utc)
        doc: dict[str, Any] = {
            "user_email": user_email,
            "name": data.name,
            "prompt": data.prompt,
            "severity": data.severity,
            "enabled": data.enabled,
            "created_at": now,
            "updated_at": now,
        }
        insert = await self.qc_checks_collection.insert_one(doc)
        stored = await self.qc_checks_collection.find_one({"_id": insert.inserted_id})
        assert stored is not None
        stored["_id"] = str(stored["_id"])
        return NoteQCCheck(**stored)

    async def update_qc_check(
        self, user_email: str, check_id: str, data: NoteQCCheckUpdate
    ) -> Optional[NoteQCCheck]:
        try:
            oid = ObjectId(check_id)
        except Exception:
            return None
        update_fields = {
            k: v
            for k, v in data.model_dump(exclude_unset=True).items()
            if v is not None
        }
        if not update_fields:
            doc = await self.qc_checks_collection.find_one(
                {"_id": oid, "user_email": user_email}
            )
        else:
            update_fields["updated_at"] = datetime.now(timezone.utc)
            doc = await self.qc_checks_collection.find_one_and_update(
                {"_id": oid, "user_email": user_email},
                {"$set": update_fields},
                return_document=ReturnDocument.AFTER,
            )
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return NoteQCCheck(**doc)

    async def delete_qc_check(self, user_email: str, check_id: str) -> bool:
        try:
            oid = ObjectId(check_id)
        except Exception:
            return False
        result = await self.qc_checks_collection.delete_one(
            {"_id": oid, "user_email": user_email}
        )
        return result.deleted_count > 0
