"""Tests for the recording media relay.

The behaviours worth pinning here are the ones that lose data or hide readiness:

  * the delete guard — the archived copy is the only OTHER copy, so purging upstream without a
    recorded archive destroys the recording outright;
  * lazy resolution — the bot is usually still uploading when transcription completes, so an
    eager link would find nothing and a never-retried lookup would leave the media unreachable;
  * "not ready" reported as 404 rather than an error, since a meeting in progress legitimately
    has no video recording yet.
"""

from unittest.mock import AsyncMock

import pytest

from dna.models.playlist_metadata import PlaylistMetadata
from dna.recording_media import (
    ArchiveNotConfirmed,
    ArchiveRecordingMismatch,
    RecordingMediaService,
    RecordingNotFound,
)

PLAYLIST_ID = 460115
VEXA_MEETING_ID = 8
RECORDING_ID = 240924981211
MEDIA_FILE_ID = 934483244372
START_UTC = "2026-08-19T20:44:40.371Z"


def _metadata(**over) -> PlaylistMetadata:
    base = {
        "_id": "abc123",
        "playlist_id": PLAYLIST_ID,
        "vexa_meeting_id": VEXA_MEETING_ID,
    }
    base.update(over)
    return PlaylistMetadata(**base)


@pytest.fixture
def storage():
    s = AsyncMock()
    s.get_playlist_metadata = AsyncMock(return_value=_metadata())
    s.upsert_playlist_metadata = AsyncMock()
    return s


@pytest.fixture
def provider():
    p = AsyncMock()
    p.list_recordings = AsyncMock(
        return_value=[
            {
                "id": RECORDING_ID,
                "media_files": [{"id": MEDIA_FILE_ID, "type": "video"}],
            }
        ]
    )
    p.get_recording_master = AsyncMock(
        return_value={
            "media_file_id": MEDIA_FILE_ID,
            "duration_seconds": 134.2,
            "start_time_utc": START_UTC,
        }
    )
    p.list_recording_chunks = AsyncMock(
        return_value={"chunks": [{"seq": 0}, {"seq": 1}], "complete": False}
    )
    p.get_recording_chunk = AsyncMock(return_value=(b"parts", "deadbeef"))
    p.delete_recording = AsyncMock(return_value={"deleted_objects": 12})
    return p


# ── lazy resolution ─────────────────────────────────────────────────────────────────────────────


async def test_resolve_links_the_recording_on_first_use(storage, provider):
    """The link is made when someone first wants the media, not when transcription ended."""
    svc = RecordingMediaService(provider, storage)
    ids = await svc.resolve(PLAYLIST_ID)

    assert ids["recording_id"] == RECORDING_ID
    assert ids["media_file_id"] == MEDIA_FILE_ID
    assert ids["start_time_utc"] == START_UTC
    provider.list_recordings.assert_awaited_once_with(VEXA_MEETING_ID)
    storage.upsert_playlist_metadata.assert_awaited_once()


async def test_resolve_uses_the_cached_link_without_calling_vexa(storage, provider):
    """Once linked, resolution is a metadata read — every chunk fetch must not re-query Vexa."""
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID,
            recording_media_file_id=MEDIA_FILE_ID,
            recording_start_time_utc=START_UTC,
        )
    )
    svc = RecordingMediaService(provider, storage)
    ids = await svc.resolve(PLAYLIST_ID)

    assert ids["recording_id"] == RECORDING_ID
    provider.list_recordings.assert_not_awaited()
    storage.upsert_playlist_metadata.assert_not_awaited()


async def test_resolve_raises_when_the_recording_does_not_exist_yet(storage, provider):
    """A meeting in progress has no video recording yet — that is 'not ready', not broken."""
    provider.list_recordings = AsyncMock(return_value=[])
    svc = RecordingMediaService(provider, storage)
    with pytest.raises(RecordingNotFound):
        await svc.resolve(PLAYLIST_ID)


async def test_resolve_ignores_an_audio_only_recording(storage, provider):
    """Recording-enabled meetings always have audio; only video is the artifact wanted here."""
    provider.list_recordings = AsyncMock(
        return_value=[{"id": 1, "media_files": [{"id": 2, "type": "audio"}]}]
    )
    svc = RecordingMediaService(provider, storage)
    with pytest.raises(RecordingNotFound):
        await svc.resolve(PLAYLIST_ID)


async def test_resolve_raises_without_metadata_or_meeting(storage, provider):
    svc = RecordingMediaService(provider, storage)

    storage.get_playlist_metadata = AsyncMock(return_value=None)
    with pytest.raises(RecordingNotFound):
        await svc.resolve(PLAYLIST_ID)

    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(vexa_meeting_id=None)
    )
    with pytest.raises(RecordingNotFound):
        await svc.resolve(PLAYLIST_ID)


async def test_resolve_raises_when_the_master_has_no_media_file(storage, provider):
    provider.get_recording_master = AsyncMock(return_value={"duration_seconds": 1.0})
    svc = RecordingMediaService(provider, storage)
    with pytest.raises(RecordingNotFound):
        await svc.resolve(PLAYLIST_ID)


# ── relay ───────────────────────────────────────────────────────────────────────────────────────


async def test_list_chunks_passes_after_through_and_carries_the_anchor(
    storage, provider
):
    """`after` is what makes polling cheap; the start clock rides along to save a second call."""
    svc = RecordingMediaService(provider, storage)
    index = await svc.list_chunks(PLAYLIST_ID, after=4)

    provider.list_recording_chunks.assert_awaited_once_with(
        RECORDING_ID, MEDIA_FILE_ID, after_seq=4
    )
    assert index["playlist_id"] == PLAYLIST_ID
    assert index["start_time_utc"] == START_UTC
    assert index["complete"] is False


async def test_get_chunk_relays_bytes_and_hash(storage, provider):
    svc = RecordingMediaService(provider, storage)
    data, sha = await svc.get_chunk(PLAYLIST_ID, 2)

    assert data == b"parts"
    assert sha == "deadbeef"
    provider.get_recording_chunk.assert_awaited_once_with(
        RECORDING_ID, MEDIA_FILE_ID, 2
    )


# ── the delete guard ────────────────────────────────────────────────────────────────────────────


async def test_delete_is_refused_without_a_recorded_archive(storage, provider):
    """THE guard. The upstream copy is the only one until the collector confirms otherwise."""
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID, recording_media_file_id=MEDIA_FILE_ID
        )
    )
    svc = RecordingMediaService(provider, storage)

    with pytest.raises(ArchiveNotConfirmed):
        await svc.delete_upstream(PLAYLIST_ID)
    provider.delete_recording.assert_not_awaited()


async def test_delete_is_refused_when_the_archive_is_only_half_recorded(
    storage, provider
):
    """A path with no hash is not a verified archive."""
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID,
            recording_media_file_id=MEDIA_FILE_ID,
            recording_network_path="/net/media/x.mp4",
        )
    )
    svc = RecordingMediaService(provider, storage)

    with pytest.raises(ArchiveNotConfirmed):
        await svc.delete_upstream(PLAYLIST_ID)
    provider.delete_recording.assert_not_awaited()


async def test_delete_proceeds_once_the_archive_is_recorded(storage, provider):
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID,
            recording_media_file_id=MEDIA_FILE_ID,
            recording_network_path="/net/media/dna/460115.mp4",
            recording_sha256="abc123",
        )
    )
    svc = RecordingMediaService(provider, storage)
    result = await svc.delete_upstream(PLAYLIST_ID)

    provider.delete_recording.assert_awaited_once_with(RECORDING_ID)
    assert result["archived_at"] == "/net/media/dna/460115.mp4"
    assert result["deleted_objects"] == 12


async def test_delete_clears_the_link_with_a_flag_not_a_none(storage, provider):
    """The upsert treats None as 'leave unchanged', so clearing needs the explicit flag.

    Without it the ids survive a purge and keep pointing at a recording that no longer exists,
    so every later read 404s against Vexa instead of reporting 'no recording'.
    """
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID,
            recording_media_file_id=MEDIA_FILE_ID,
            recording_network_path="/net/media/x.mp4",
            recording_sha256="abc123",
        )
    )
    svc = RecordingMediaService(provider, storage)
    await svc.delete_upstream(PLAYLIST_ID)

    update = storage.upsert_playlist_metadata.await_args.args[1]
    assert update.clear_recording_link is True


# ── archiving ───────────────────────────────────────────────────────────────────────────────────


async def test_record_archive_persists_path_and_hash(storage, provider):
    svc = RecordingMediaService(provider, storage)
    result = await svc.record_archive(
        PLAYLIST_ID, "/net/media/dna/460115.mp4", "abc123def456"
    )

    update = storage.upsert_playlist_metadata.await_args.args[1]
    assert update.recording_network_path == "/net/media/dna/460115.mp4"
    assert update.recording_sha256 == "abc123def456"
    assert result["recording_id"] == RECORDING_ID


async def test_record_archive_stamps_which_meeting_and_recording_it_holds(
    storage, provider
):
    """The queue asks 'has THIS meeting been archived', so the archive has to say which one it is.

    Without the stamp the only question answerable was 'does this playlist have any archive',
    which made a playlist that hosted a second meeting look finished forever.
    """
    svc = RecordingMediaService(provider, storage)
    await svc.record_archive(PLAYLIST_ID, "/net/media/x.mp4", "hash")

    update = storage.upsert_playlist_metadata.await_args.args[1]
    assert update.archived_recording_id == RECORDING_ID
    assert update.archived_meeting_id == VEXA_MEETING_ID


async def test_record_archive_refuses_a_recording_it_did_not_resolve(storage, provider):
    """A disagreement means the two ends are looking at different recordings.

    Recording it anyway would stamp THIS meeting as archived while the bytes on disk came from
    another one — and the meeting actually in progress would never be collected.
    """
    svc = RecordingMediaService(provider, storage)

    with pytest.raises(ArchiveRecordingMismatch):
        await svc.record_archive(
            PLAYLIST_ID, "/net/media/x.mp4", "hash", recording_id=999999
        )

    # resolve() may legitimately write the resolution CACHE on the way through. What must not be
    # written is the archive itself — that is the fact the delete guard later opens on.
    written = [c.args[1] for c in storage.upsert_playlist_metadata.await_args_list]
    assert all(u.recording_network_path is None for u in written)
    assert all(u.archived_recording_id is None for u in written)


async def test_a_link_resolved_for_an_earlier_meeting_is_not_reused(storage, provider):
    """The cache is only good for the meeting it was resolved against.

    A playlist whose collection never finished keeps its link, so a SECOND meeting would be served
    the FIRST meeting's recording — and archiving that under the new meeting's id would strand the
    real recording upstream forever.
    """
    stale = _metadata(
        vexa_recording_id=111111,
        recording_media_file_id=222222,
        recording_link_meeting_id=VEXA_MEETING_ID
        - 1,  # resolved for the previous meeting
    )
    storage.get_playlist_metadata = AsyncMock(return_value=stale)
    svc = RecordingMediaService(provider, storage)

    ids = await svc.resolve(PLAYLIST_ID)

    assert (
        ids["recording_id"] == RECORDING_ID
    ), "must re-resolve, not serve the stale link"
    provider.list_recordings.assert_awaited_once_with(VEXA_MEETING_ID)
    update = storage.upsert_playlist_metadata.await_args.args[1]
    assert update.recording_link_meeting_id == VEXA_MEETING_ID


async def test_a_link_resolved_for_the_current_meeting_is_reused(storage, provider):
    """The gate must not defeat the cache it qualifies — a matching stamp still short-circuits."""
    linked = _metadata(
        vexa_recording_id=RECORDING_ID,
        recording_media_file_id=MEDIA_FILE_ID,
        recording_link_meeting_id=VEXA_MEETING_ID,
    )
    storage.get_playlist_metadata = AsyncMock(return_value=linked)
    svc = RecordingMediaService(provider, storage)

    ids = await svc.resolve(PLAYLIST_ID)

    assert ids["recording_id"] == RECORDING_ID
    provider.list_recordings.assert_not_awaited()


async def test_archive_then_delete_is_the_intended_sequence(storage, provider):
    """The collector's real flow: archive, then purge. The guard opens only after the archive."""
    linked = _metadata(
        vexa_recording_id=RECORDING_ID, recording_media_file_id=MEDIA_FILE_ID
    )
    storage.get_playlist_metadata = AsyncMock(return_value=linked)
    svc = RecordingMediaService(provider, storage)

    with pytest.raises(ArchiveNotConfirmed):
        await svc.delete_upstream(PLAYLIST_ID)

    await svc.record_archive(PLAYLIST_ID, "/net/media/x.mp4", "hash")
    storage.get_playlist_metadata = AsyncMock(
        return_value=_metadata(
            vexa_recording_id=RECORDING_ID,
            recording_media_file_id=MEDIA_FILE_ID,
            recording_network_path="/net/media/x.mp4",
            recording_sha256="hash",
        )
    )
    await svc.delete_upstream(PLAYLIST_ID)
    provider.delete_recording.assert_awaited_once_with(RECORDING_ID)


# ── the audio master ────────────────────────────────────────────────────────────────────────────


AUDIO_MEDIA_FILE_ID = 55501
AUDIO_START_UTC = "2026-08-19T20:44:41.871Z"


def _with_audio(provider):
    """Give the provider an audio master alongside the video one it already has."""

    async def master(recording_id, media_type="video"):
        if media_type == "audio":
            return {
                "media_file_id": AUDIO_MEDIA_FILE_ID,
                "duration_seconds": 132.7,
                "start_time_utc": AUDIO_START_UTC,
            }
        return {
            "media_file_id": MEDIA_FILE_ID,
            "duration_seconds": 134.2,
            "start_time_utc": START_UTC,
        }

    provider.get_recording_master = AsyncMock(side_effect=master)
    provider.get_recording_media_raw = AsyncMock(return_value=b"OPUSBYTES")
    return provider


async def test_get_audio_returns_the_master_with_BOTH_anchors(storage, provider):
    """The mux needs the difference between the two start clocks, so one anchor is useless on its
    own — returning both is what saves the caller a second round trip to work out the offset.
    """
    svc = RecordingMediaService(_with_audio(provider), storage)

    data, meta = await svc.get_audio(PLAYLIST_ID)

    assert data == b"OPUSBYTES"
    assert meta["start_time_utc"] == AUDIO_START_UTC
    assert meta["video_start_time_utc"] == START_UTC
    assert meta["media_file_id"] == AUDIO_MEDIA_FILE_ID


async def test_get_audio_reads_the_AUDIO_media_file_not_the_video_one(
    storage, provider
):
    """Both streams live in one recording, so the media type is the only thing separating them."""
    svc = RecordingMediaService(_with_audio(provider), storage)

    await svc.get_audio(PLAYLIST_ID)

    provider.get_recording_media_raw.assert_awaited_once_with(
        RECORDING_ID, AUDIO_MEDIA_FILE_ID, media_type="audio"
    )


async def test_get_audio_404s_when_the_recording_has_no_audio_stream(storage, provider):
    """A video-only recording is a real case (the tap never started). The collector treats this
    as 'archive without sound', which is why it must be a clean 404 rather than a crash.
    """

    async def master(recording_id, media_type="video"):
        if media_type == "audio":
            return {"media_file_id": None, "start_time_utc": None}
        return {"media_file_id": MEDIA_FILE_ID, "start_time_utc": START_UTC}

    provider.get_recording_master = AsyncMock(side_effect=master)

    svc = RecordingMediaService(provider, storage)

    with pytest.raises(RecordingNotFound, match="no audio media file"):
        await svc.get_audio(PLAYLIST_ID)
