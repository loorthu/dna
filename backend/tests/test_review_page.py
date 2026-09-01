"""The artist-facing view of a review: what it shows, and what it refuses to guess.

Two rules earn most of these tests.

WHOSE NOTES. The notes email filters to whoever pressed send. An artist is not the sender, so
carrying that filter over would render an empty page; this projection takes everyone's notes
instead, minus the empty rows ShotGrid seeds against every version when a playlist is created —
those would put a blank byline under every shot.

WHICH PLAYLIST. `/review/<project>/<name>` is a claim about names, and a show runs "Dailies" every
day it screens one. Resolving must either name one playlist or hand back the choice; picking the
newest sends someone following a month-old link to a review they were not in, and looks like it
worked.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from dna.models.draft_note import DraftNote
from dna.models.entity import Playlist, Project, Shot, Task, User, Version
from dna.models.stored_segment import StoredSegment
from dna.review_page import (
    ReviewPlaylistNotFound,
    build_review_link,
    build_review_playlist,
    resolve_playlist,
)

PLAYLIST_ID = 4471
PROJECT_ID = 124
VERSION_A = 900
VERSION_B = 901


def _version(version_id: int, name: str) -> Version:
    return Version(
        id=version_id,
        name=name,
        status="rev",
        user=User(id=7, name="Cottalango Leon"),
        entity=Shot(id=50, name="abc_0100"),
        task=Task(id=60, name="comp"),
        frame_path="/net/show/abc/abc_0100/comp/v012/abc_0100_comp_v012.####.exr",
        project={"id": PROJECT_ID, "name": "ABC Show", "type": "Project"},
        created_at="2026-08-30T10:00:00Z",
    )


def _draft(version_id: int, email: str, content: str, **over) -> DraftNote:
    base = {
        "_id": f"note-{version_id}-{email}",
        "user_email": email,
        "playlist_id": PLAYLIST_ID,
        "version_id": version_id,
        "content": content,
        "published": True,
        "origin": "dna",
        "created_at": datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc),
    }
    base.update(over)
    return DraftNote(**base)


def _segment(version_id: int, text: str, start: str, speaker: str) -> StoredSegment:
    return StoredSegment(
        _id=f"seg-{start}",
        segment_id=f"seg-{start}",
        playlist_id=PLAYLIST_ID,
        version_id=version_id,
        text=text,
        speaker=speaker,
        absolute_start_time=start,
        absolute_end_time=start,
        created_at=datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc),
    )


def _prodtrack(versions=None, playlist_name="Dailies Comp 2026-08-30"):
    provider = MagicMock()
    provider.get_versions_for_playlist.return_value = versions or [
        _version(VERSION_A, "abc_0100_comp_v012")
    ]

    def get_entity(entity_type, entity_id, resolve_links=True):
        if entity_type == "playlist":
            return Playlist(
                id=entity_id,
                code=playlist_name,
                project={"id": PROJECT_ID, "name": "ABC Show", "type": "Project"},
                created_at="2026-08-30T09:00:00Z",
            )
        if entity_type == "project":
            return Project(id=entity_id, name="ABC Show", code="ABC")
        raise ValueError(entity_type)

    provider.get_entity.side_effect = get_entity
    return provider


def _storage(drafts=None, segments=None):
    storage = MagicMock()
    storage.get_draft_notes_for_playlist = AsyncMock(return_value=drafts or [])
    storage.get_segments_for_playlist = AsyncMock(return_value=segments or [])
    return storage


class TestNotesShown:
    @pytest.mark.asyncio
    async def test_every_author_is_shown_not_just_one(self):
        """The email's filter to the sender would leave an artist with a blank page."""
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(
                drafts=[
                    _draft(VERSION_A, "sup@example.com", "Push the haze back."),
                    _draft(
                        VERSION_A, "lead@example.com", "Agreed, and soften the rim."
                    ),
                ]
            ),
            MagicMock(),
        )
        authors = [n.author_email for n in page.shots[0].notes]
        assert authors == ["sup@example.com", "lead@example.com"]

    @pytest.mark.asyncio
    async def test_shotgrid_seeded_notes_are_left_out(self):
        """ShotGrid seeds an empty note per version; showing them bylines every shot with nobody."""
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(
                drafts=[
                    _draft(VERSION_A, "sup@example.com", "Push the haze back."),
                    _draft(VERSION_A, "seed@example.com", "Seeded", origin="prodtrack"),
                ]
            ),
            MagicMock(),
        )
        assert [n.author_email for n in page.shots[0].notes] == ["sup@example.com"]

    @pytest.mark.asyncio
    async def test_empty_notes_are_left_out(self):
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(drafts=[_draft(VERSION_A, "sup@example.com", "   ")]),
            MagicMock(),
        )
        assert page.shots[0].notes == []

    @pytest.mark.asyncio
    async def test_an_unpublished_note_is_shown_and_says_so(self):
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(
                drafts=[_draft(VERSION_A, "sup@example.com", "Draft", published=False)]
            ),
            MagicMock(),
        )
        assert page.shots[0].notes[0].published is False

    @pytest.mark.asyncio
    async def test_the_byline_is_a_name_not_a_mailbox(self):
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(drafts=[_draft(VERSION_A, "jane.smith@example.com", "Note")]),
            MagicMock(),
        )
        assert page.shots[0].notes[0].author_name == "Jane Smith"

    @pytest.mark.asyncio
    async def test_notes_are_filed_against_their_own_shot(self):
        versions = [
            _version(VERSION_A, "abc_0100_comp_v012"),
            _version(VERSION_B, "abc_0110_comp_v004"),
        ]
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(versions=versions),
            _storage(drafts=[_draft(VERSION_B, "sup@example.com", "Only on B")]),
            MagicMock(),
        )
        assert page.shots[0].notes == []
        assert page.shots[1].notes[0].content == "Only on B"


class TestTranscript:
    @pytest.mark.asyncio
    async def test_lines_come_back_in_the_order_they_were_said(self):
        page = await build_review_playlist(
            PLAYLIST_ID,
            _prodtrack(),
            _storage(
                segments=[
                    _segment(VERSION_A, "second", "2026-08-30T18:00:10Z", "Jane"),
                    _segment(VERSION_A, "first", "2026-08-30T18:00:00Z", "Jane"),
                ]
            ),
            MagicMock(),
        )
        assert [line.text for line in page.shots[0].transcript] == ["first", "second"]


class TestRecording:
    @pytest.mark.asyncio
    async def test_disabled_when_the_deployment_has_no_pipeline(self, monkeypatch):
        monkeypatch.setenv("DNA_ENABLE_RECORDING_PLAYBACK", "false")
        page = await build_review_playlist(
            PLAYLIST_ID, _prodtrack(), _storage(), MagicMock()
        )
        assert page.recording.status == "disabled"
        assert page.recording.media_url is None

    @pytest.mark.asyncio
    async def test_a_failed_cut_list_does_not_take_the_page_with_it(self, monkeypatch):
        """Notes and transcript are why the artist opened the link; the share may not be mounted."""
        monkeypatch.setenv("DNA_ENABLE_RECORDING_PLAYBACK", "true")
        storage = _storage(drafts=[_draft(VERSION_A, "sup@example.com", "A note")])
        storage.get_playlist_metadata = AsyncMock(
            side_effect=RuntimeError("share down")
        )
        page = await build_review_playlist(
            PLAYLIST_ID, _prodtrack(), storage, MagicMock()
        )
        assert page.recording.status == "no_recording"
        assert page.shots[0].notes[0].content == "A note"


class TestPageShape:
    @pytest.mark.asyncio
    async def test_shots_are_numbered_as_screened(self):
        versions = [
            _version(VERSION_A, "abc_0100_comp_v012"),
            _version(VERSION_B, "abc_0110_comp_v004"),
        ]
        page = await build_review_playlist(
            PLAYLIST_ID, _prodtrack(versions=versions), _storage(), MagicMock()
        )
        assert [s.index for s in page.shots] == [1, 2]

    @pytest.mark.asyncio
    async def test_the_page_knows_its_own_canonical_address(self):
        page = await build_review_playlist(
            PLAYLIST_ID, _prodtrack(), _storage(), MagicMock()
        )
        assert page.url_path == "/review/abc/dailies-comp-2026-08-30"
        assert page.shots[0].anchor == "abc_0100_comp_v012"

    @pytest.mark.asyncio
    async def test_a_playlist_that_cannot_be_loaded_still_renders_its_shots(self):
        """The heading is not what the artist came for."""
        prodtrack = _prodtrack()
        prodtrack.get_entity.side_effect = RuntimeError("ShotGrid down")
        page = await build_review_playlist(
            PLAYLIST_ID, prodtrack, _storage(), MagicMock()
        )
        assert page.playlist_name == ""
        assert len(page.shots) == 1


class TestReviewLink:
    """The address alone, for the button the reviewing tool puts beside its PT tab one."""

    def test_gives_the_page_address_and_an_anchor_per_shot(self):
        versions = [
            _version(VERSION_A, "abc_0100_comp_v012"),
            _version(VERSION_B, "abc_0110_comp_v004"),
        ]
        link = build_review_link(PLAYLIST_ID, _prodtrack(versions=versions))
        assert link.url_path == "/review/abc/dailies-comp-2026-08-30"
        assert link.anchors == {
            VERSION_A: "abc_0100_comp_v012",
            VERSION_B: "abc_0110_comp_v004",
        }

    def test_costs_nothing_from_the_note_store_or_the_recording(self):
        """It sits behind a button, so it must not drag the whole page along with it."""
        prodtrack = _prodtrack()
        link = build_review_link(PLAYLIST_ID, prodtrack)
        assert link.playlist_id == PLAYLIST_ID
        # Only the production tracker is consulted — no storage or transcription argument exists
        # to pass, which is the point.
        assert prodtrack.get_versions_for_playlist.call_count == 1

    def test_agrees_with_the_page_it_links_to(self):
        """Two callers, one slug rule: a mismatch is a link that lands nowhere."""
        versions = [_version(VERSION_A, "abc_0100_comp_v012")]
        link = build_review_link(PLAYLIST_ID, _prodtrack(versions=versions))
        page = asyncio.run(
            build_review_playlist(
                PLAYLIST_ID, _prodtrack(versions=versions), _storage(), MagicMock()
            )
        )
        assert link.url_path == page.url_path
        assert link.anchors[VERSION_A] == page.shots[0].anchor


class TestResolvePlaylist:
    def _provider(self, playlists, projects=None):
        provider = MagicMock()
        provider.get_projects_for_user.return_value = projects or [
            Project(id=PROJECT_ID, name="ABC Show", code="ABC")
        ]
        provider.find_playlists_by_name_slug.return_value = playlists
        return provider

    def test_one_match_resolves_to_its_id(self):
        provider = self._provider(
            [
                Playlist(
                    id=PLAYLIST_ID, code="Dailies", created_at="2026-08-30T09:00:00Z"
                )
            ]
        )
        result = resolve_playlist(provider, "a@b.com", "abc", "dailies")
        assert result.playlist_id == PLAYLIST_ID

    def test_several_matches_resolve_to_a_choice_not_a_guess(self):
        provider = self._provider(
            [
                Playlist(id=2, code="Dailies", created_at="2026-08-30T09:00:00Z"),
                Playlist(id=1, code="Dailies", created_at="2026-07-30T09:00:00Z"),
            ]
        )
        result = resolve_playlist(provider, "a@b.com", "abc", "dailies")
        assert result.playlist_id is None
        assert [m.playlist_id for m in result.matches] == [2, 1]
        # Each candidate carries an address that always resolves, so picking one cannot land back
        # on the same ambiguous name.
        assert result.matches[0].url_path == "/review/id/2"

    def test_no_match_is_not_found(self):
        provider = self._provider([])
        with pytest.raises(ReviewPlaylistNotFound):
            resolve_playlist(provider, "a@b.com", "abc", "dailies")

    def test_a_project_the_viewer_cannot_see_is_not_found(self):
        provider = self._provider(
            [], projects=[Project(id=9, name="Other", code="XYZ")]
        )
        with pytest.raises(ReviewPlaylistNotFound):
            resolve_playlist(provider, "a@b.com", "abc", "dailies")

    def test_the_project_may_be_named_by_its_full_name(self):
        """Rescues a link someone typed or edited by hand."""
        provider = self._provider(
            [
                Playlist(
                    id=PLAYLIST_ID, code="Dailies", created_at="2026-08-30T09:00:00Z"
                )
            ]
        )
        result = resolve_playlist(provider, "a@b.com", "abc-show", "dailies")
        assert result.playlist_id == PLAYLIST_ID
