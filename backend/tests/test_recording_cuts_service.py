"""The playback answer for a playlist, and the several ways there can be nothing to play.

The cut arithmetic itself is covered in test_video_segment_publish.py. What matters here is the
part that costs a person their afternoon when it is wrong: telling apart "never recorded", "being
recorded now", "recorded but not collected yet" and "recorded, nothing said against these
versions". All four produce an empty cut list, and collapsing them renders all four as the same
blank box — which is indistinguishable from a bug.
"""

from unittest.mock import AsyncMock

import pytest

from dna.models.playlist_metadata import PlaylistMetadata
from dna.models.stored_segment import StoredSegment
from dna.recording_cuts_service import RecordingCutsService, media_url_for
from dna.recording_media import RecordingNotFound

PLAYLIST_ID = 461350
VERSION_ID = 5701144
# The real anchor and duration from the 2026-08-21 meeting this was validated against.
T0 = "2026-08-21T21:27:39.777Z"
DURATION = 156.4
ARCHIVE = "/net/media/dna-recordings/playlist-461350-rec619075238345.mp4"


def _metadata(**over) -> PlaylistMetadata:
    base = {
        "_id": "meta",
        "playlist_id": PLAYLIST_ID,
        "vexa_meeting_id": 31,
        "recording_network_path": ARCHIVE,
        "recording_start_time_utc": T0,
        "recording_duration_seconds": DURATION,
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

    async def test_media_url_hides_the_share_path(self, storage, provider):
        """The browser plays it off this origin; it never learns where the share really is."""
        storage.get_segments_for_playlist.return_value = [
            _segment("a", "2026-08-21T21:28:40.932Z", "2026-08-21T21:28:41.956Z")
        ]
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["media_url"] == "/recordings/playlist-461350-rec619075238345.mp4"
        assert "/net/media" not in result["media_url"]

    async def test_each_version_is_reported_separately(self, storage, provider):
        """A meeting covers several versions; each gets its own spans and its own hash."""
        other = _segment("b", "2026-08-21T21:29:00Z", "2026-08-21T21:29:05Z")
        other.version_id = 999
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


class TestTheFourWaysThereIsNothingToPlay:
    async def test_no_meeting_is_no_recording(self, storage, provider):
        storage.get_playlist_metadata.return_value = _metadata(vexa_meeting_id=None)
        svc = RecordingCutsService(provider, storage)

        result = await svc.build(PLAYLIST_ID)

        assert result["status"] == "no_recording"
        assert result["media_url"] is None

    async def test_no_metadata_at_all_is_no_recording(self, storage, provider):
        storage.get_playlist_metadata.return_value = None
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
        assert result["media_url"] == "/recordings/playlist-461350-rec619075238345.mp4"
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

    async def test_a_missing_upstream_recording_is_no_recording(
        self, storage, provider
    ):
        storage.get_playlist_metadata.return_value = _metadata(
            recording_network_path=None
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


class TestMediaUrl:
    def test_none_when_there_is_no_archive(self):
        assert media_url_for(None) is None

    def test_serves_from_the_nginx_prefix(self):
        assert media_url_for("/anywhere/at/all/file.mp4") == "/recordings/file.mp4"
