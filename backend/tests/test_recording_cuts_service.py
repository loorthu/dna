"""The playback answer for a playlist, and the several ways there can be nothing to play.

The cut arithmetic itself is covered in test_video_segment_publish.py. What matters here is the
part that costs a person their afternoon when it is wrong: telling apart "no meeting yet", "ran
unrecorded", "being recorded now", "recorded but not collected yet" and "recorded, nothing said
against these versions". All five produce an empty cut list, and collapsing them renders all five
as the same blank box — which is indistinguishable from a bug.
"""

from unittest.mock import AsyncMock

import pytest

from dna.models.playlist_metadata import PlaylistMetadata
from dna.models.stored_segment import StoredSegment
from dna.recording_cuts_service import (
    RecordingCutsService,
    media_url_for,
    recording_playback_enabled,
)
from dna.recording_media import RecordingNotFound

PLAYLIST_ID = 461350
VERSION_ID = 5701144
# The real anchor and duration from the 2026-08-21 meeting this was validated against.
T0 = "2026-08-21T21:27:39.777Z"
DURATION = 156.4
ARCHIVE = (
    "nite/lib.recording/pix/ref/dna/20260821/"
    "NITE_Director_Review_2026_08_21_14_28_PDT_Recording.mp4"
)


# A cut is a period the version was under review, so the tests need the mark's timeline. This one
# holds VERSION_ID for exactly the span it was spoken about in the meeting these numbers come from.
IN_REVIEW = [
    {"version_id": VERSION_ID, "since": "2026-08-21T21:28:40.932Z"},
    {"version_id": None, "since": "2026-08-21T21:28:41.956Z"},
]


def _metadata(**over) -> PlaylistMetadata:
    base = {
        "_id": "meta",
        "playlist_id": PLAYLIST_ID,
        "vexa_meeting_id": 31,
        "recording_network_path": ARCHIVE,
        "recording_start_time_utc": T0,
        "recording_duration_seconds": DURATION,
        "in_review_history": IN_REVIEW,
    }
    base.update(over)
    return PlaylistMetadata(**base)


def _segment(segment_id: str, start: str, end: str) -> StoredSegment:
    from datetime import datetime, timezone

    now = datetime(2026, 8, 21, 21, 30, tzinfo=timezone.utc)
    return StoredSegment(
        _id="m" + segment_id,
        segment_id=segment_id,
        playlist_id=PLAYLIST_ID,
        version_id=VERSION_ID,
        text="hello",
        speaker="Cottalango Leon",
        language="en",
        absolute_start_time=start,
        absolute_end_time=end,
        vexa_updated_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def storage():
    s = AsyncMock()
    s.get_playlist_metadata = AsyncMock(return_value=_metadata())
    s.get_segments_for_playlist = AsyncMock(return_value=[])
    return s


@pytest.fixture
def provider():
    return AsyncMock()


class TestTheReadyAnswer:
    async def test_cuts_are_measured_from_the_recorders_own_clock(
        self, storage, provider
    ):
        """The numbers here are the real ones: a segment spoken at 21:28:40.932 sits 61.155s in."""
        storage.get_segments_for_playlist.return_value = [
            _segment("a", "2026-08-21T21:28:40.932Z", "2026-08-21T21:28:41.956Z")
        ]
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "ready"
        assert result["recording_t0_source"] == "vexa_recorder_clock"
        cut = result["versions"][0]["cuts"][0]
        assert round(cut["video_in_seconds"], 3) == 61.155
        assert round(cut["video_out_seconds"], 3) == 62.179

    async def test_media_url_hides_where_the_share_is_mounted(self, storage, provider):
        """The browser plays it off this origin. It sees the show and the date — that is the
        file's address under the root nginx serves — but never where that root really is.
        """
        storage.get_segments_for_playlist.return_value = [
            _segment("a", "2026-08-21T21:28:40.932Z", "2026-08-21T21:28:41.956Z")
        ]
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["media_url"] == f"/recordings/{ARCHIVE}"
        assert "/shots" not in result["media_url"]

    async def test_each_version_is_reported_separately(self, storage, provider):
        """A meeting covers several versions; each gets its own spans and its own hash."""
        other = _segment("b", "2026-08-21T21:29:00Z", "2026-08-21T21:29:05Z")
        other.version_id = 999
        storage.get_playlist_metadata.return_value = _metadata(
            in_review_history=IN_REVIEW[:1]
            + [
                {"version_id": 999, "since": "2026-08-21T21:28:50Z"},
                {"version_id": None, "since": "2026-08-21T21:29:10Z"},
            ]
        )
        storage.get_segments_for_playlist.return_value = [
            _segment("a", "2026-08-21T21:28:40.932Z", "2026-08-21T21:28:41.956Z"),
            other,
        ]
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        # Ascending version_id, per build_video_cuts_payload's contract — a stable order the
        # caller can rely on rather than whatever the segments happened to arrive in.
        assert [v["version_id"] for v in result["versions"]] == [999, VERSION_ID]
        assert result["versions"][0]["body_hash"] != result["versions"][1]["body_hash"]


class TestTheFiveWaysThereIsNothingToPlay:
    async def test_a_playlist_with_no_meeting_yet_is_no_meeting(
        self, storage, provider
    ):
        """NOT `no_recording`.

        This is the state every playlist is in before its bot is dispatched, which is when the
        panel first asks. Answering `no_recording` there told someone who was about to record a
        meeting that their recording would not happen — and the client, reading it as settled,
        never asked again for the rest of the meeting.
        """
        storage.get_playlist_metadata.return_value = _metadata(vexa_meeting_id=None)
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "no_meeting"
        assert result["media_url"] is None

    async def test_no_metadata_at_all_is_no_meeting(self, storage, provider):
        storage.get_playlist_metadata.return_value = None
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "no_meeting"

    async def test_a_meeting_that_ran_unrecorded_is_no_recording(
        self, storage, provider
    ):
        """The other half of the split: a meeting DID happen, with recording turned off."""
        storage.get_playlist_metadata.return_value = _metadata(
            vexa_meeting_id=38, recording_enabled=False, recording_network_path=None
        )
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "no_recording"

    async def test_an_incomplete_upstream_recording_is_pending(self, storage, provider):
        """Still being recorded — come back when the meeting ends."""
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None
        )
        provider.list_recordings.return_value = [
            {"id": 1, "media_files": [{"id": 2, "type": "video"}]}
        ]
        provider.get_recording_master.return_value = {"media_file_id": 2}
        provider.list_recording_chunks.return_value = {"chunks": [], "complete": False}
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "pending"

    async def test_a_complete_upstream_recording_is_archiving(self, storage, provider):
        """Recorded, and the collector has not taken custody yet — come back in a minute."""
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None
        )
        provider.list_recordings.return_value = [
            {"id": 1, "media_files": [{"id": 2, "type": "video"}]}
        ]
        provider.get_recording_master.return_value = {"media_file_id": 2}
        provider.list_recording_chunks.return_value = {"chunks": [], "complete": True}
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "archiving"

    async def test_an_archived_recording_with_no_transcript_is_no_segments(
        self, storage, provider
    ):
        """The meeting happened and was recorded; nothing was said against these versions.

        The media is still offered — there is a recording to watch, just no shot list.
        """
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "no_segments"
        assert result["media_url"] == f"/recordings/{ARCHIVE}"
        assert result["versions"] == []

    async def test_an_unreachable_upstream_does_not_claim_there_is_no_recording(
        self, storage, provider
    ):
        """Vexa being unreachable is not evidence a recording never existed.

        Saying `no_recording` would tell the viewer to stop waiting for something that is on its
        way; `archiving` merely asks them to look again.
        """
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None
        )
        provider.list_recordings.side_effect = RuntimeError("connection refused")
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "archiving"

    async def test_nothing_upstream_yet_is_pending_when_recording_was_asked_for(
        self, storage, provider
    ):
        """The first seconds of a recorded meeting: the bot has joined, the recorder has not
        registered anything yet.

        NOT `no_recording`. That answer is terminal — the client stops asking — so a meeting being
        recorded right now spent its whole duration telling the viewer it was not being recorded,
        next to a checkbox they had ticked.
        """
        storage.get_playlist_metadata.return_value = _metadata(
            recording_enabled=True, recording_network_path=None
        )
        provider.list_recordings.return_value = []  # -> RecordingNotFound
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "pending"

    async def test_nothing_upstream_and_nobody_asked_is_no_recording(
        self, storage, provider
    ):
        """A meeting from before the flag was recorded either way. Nothing is coming, and saying
        `pending` would leave the client polling for something that will never arrive.
        """
        storage.get_playlist_metadata.return_value = _metadata(
            recording_enabled=None, recording_network_path=None
        )
        provider.list_recordings.return_value = []  # -> RecordingNotFound
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "no_recording"


class TestARecordingWithNoUsableAnchor:
    async def test_media_is_offered_without_invented_cuts(self, storage, provider):
        """Every offset would be a guess, and a guessed zero is wrong in a way that looks right."""
        storage.get_playlist_metadata.return_value = _metadata(
            recording_start_time_utc=None
        )
        storage.get_segments_for_playlist.return_value = [
            _segment("a", "2026-08-21T21:28:40.932Z", "2026-08-21T21:28:41.956Z")
        ]
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "no_segments"
        assert result["media_url"] is not None
        assert result["versions"] == []
        assert result["recording_t0"] is None


class TestACollectionThatNeedsSomebody:
    """`blocked` exists because "still being collected", repeated forever, is true and useless.

    A recording the collector cannot file — today, a show with no recording directory on the
    share — is not a wait. Reporting it as one hides the single fact that would resolve it.
    """

    async def test_the_reason_is_reported_instead_of_another_wait(
        self, storage, provider
    ):
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None,
            recording_archive_error="nite/lib.recording/pix/ref/dna does not exist",
        )
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "blocked"
        assert result["status_detail"] == (
            "nite/lib.recording/pix/ref/dna does not exist"
        )
        assert result["media_url"] is None

    async def test_it_is_answered_without_asking_the_upstream_index(
        self, storage, provider
    ):
        """Nothing about the upstream copy can change this answer, so nothing asks it."""
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None, recording_archive_error="no directory"
        )
        svc = RecordingCutsService(provider, storage)

        await svc.build(PLAYLIST_ID)

        provider.list_recording_chunks.assert_not_called()

    async def test_an_archive_that_landed_wins_over_a_stale_reason(
        self, storage, provider
    ):
        """The reason is cleared when an archive is recorded; a row that somehow kept both is
        answered by the file, which is the thing the viewer wanted."""
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=ARCHIVE,
            recording_archive_error="no directory",
        )
        storage.get_segments_for_playlist.return_value = []
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] != "blocked"
        assert result["media_url"] == f"/recordings/{ARCHIVE}"


class TestMediaUrl:
    def test_none_when_there_is_no_archive(self):
        assert media_url_for(None) is None

    def test_serves_the_stored_path_from_the_nginx_prefix(self):
        """nginx aliases /recordings/ onto the share ROOT, so the whole relative path travels."""
        assert media_url_for(ARCHIVE) == f"/recordings/{ARCHIVE}"

    def test_a_pre_layout_filename_still_reads_as_a_url(self):
        """Rows from before the archives were filed by show and date. They still form a URL; it
        no longer RESOLVES, because nginx now aliases a different root."""
        assert (
            media_url_for("playlist-42-rec7.mp4") == "/recordings/playlist-42-rec7.mp4"
        )


class TestAMeetingThatWasNotRecorded:
    """Recording off is a fact, not something to rediscover on every poll.

    It is recorded at dispatch, so nothing downstream has to ask Vexa about media it was told not
    to make. These tests pin the ABSENCE of that work: they would pass just as happily if the
    round trips came back, which is why each asserts the provider was never called.
    """

    async def test_the_cut_list_answers_without_asking_vexa(self, storage, provider):
        storage.get_playlist_metadata.return_value = _metadata(
            recording_enabled=False, recording_network_path=None
        )
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "no_recording"
        assert result["media_url"] is None
        provider.list_recordings.assert_not_awaited()
        provider.list_recording_chunks.assert_not_awaited()

    async def test_an_unknown_flag_still_asks(self, storage, provider):
        """None means "dispatched before this was recorded" — unknown, not known-absent.

        Treating it as off would strand any meeting recorded before the flag existed.
        """
        storage.get_playlist_metadata.return_value = _metadata(
            recording_enabled=None, recording_network_path=None
        )
        provider.list_recordings.return_value = [
            {"id": 1, "media_files": [{"id": 2, "type": "video"}]}
        ]
        provider.get_recording_master.return_value = {"media_file_id": 2}
        provider.list_recording_chunks.return_value = {"chunks": [], "complete": True}
        svc = RecordingCutsService(provider, storage)

        assert (await svc.build(PLAYLIST_ID))["status"] == "archiving"
        provider.list_recordings.assert_awaited()


class TestTheFlagThatGatesTheFeature:
    """One env read, but it decides whether the endpoint exists at all — a typo here disables
    playback everywhere with no error to notice."""

    def test_off_unless_explicitly_turned_on(self, monkeypatch):
        monkeypatch.delenv("DNA_ENABLE_RECORDING_PLAYBACK", raising=False)
        assert recording_playback_enabled() is False

    def test_on_however_true_is_spelled(self, monkeypatch):
        for spelling in ("true", "True", "TRUE"):
            monkeypatch.setenv("DNA_ENABLE_RECORDING_PLAYBACK", spelling)
            assert recording_playback_enabled() is True

    def test_anything_else_is_off(self, monkeypatch):
        for spelling in ("false", "1", "yes", ""):
            monkeypatch.setenv("DNA_ENABLE_RECORDING_PLAYBACK", spelling)
            assert recording_playback_enabled() is False
