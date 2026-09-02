"""The airgap collector: resuming, verifying, and refusing to release the only other copy.

The three things worth proving here are the three that cost a recording if wrong:

  • a restart mid-meeting RESUMES — it neither starts over nor continues past a torn append;
  • a part whose hash does not match is NEVER appended, because the file is a byte concatenation
    and a bad part corrupts everything after it rather than leaving a gap;
  • the upstream copy is released only after an archive exists, is readable, and re-hashes.

Everything the collector touches is injected, so the whole flow runs offline with no ffmpeg, no
network and no share.
"""

import hashlib
import json
import os

import pytest

from dna.recording_collector import (
    CollectionFailed,
    CollectorError,
    CollectorState,
    MuxFailed,
    PartRecord,
    RecordingCollector,
    build_mux_command,
    compute_audio_delay_ms,
    plan_resume,
    sha256_bytes,
)

VIDEO_T0 = "2026-08-20T17:00:00.000Z"
AUDIO_T0 = "2026-08-20T17:00:01.500Z"
# Staging and archive paths are scoped by recording, not by playlist, so the tests have to name
# the recording they are inspecting — the same scoping that stops a playlist's second meeting
# from resuming the first one's byte stream.
REC = 7001


class FakeClient:
    """DNA's relay, with the parts held in memory and every call recorded."""

    def __init__(
        self, parts: list[bytes], complete: bool = True, audio: bytes = b"AUDIO"
    ):
        self.parts = parts
        self.complete = complete
        self.audio = audio
        self.audio_start = AUDIO_T0
        self.calls: list[str] = []
        self.recording_id: int | None = REC
        self.archived: list[tuple[str, str]] = []
        self.archived_recording_ids: list[int | None] = []
        self.deleted: list[int] = []
        self.corrupt_seq: int | None = None
        self.hide_seq: int | None = None
        self.audio_error: Exception | None = None
        # The cut list the poster frames are taken from, and what was pushed back.
        self.cuts: dict = {
            "status": "ready",
            "versions": [
                {
                    "version_id": 900,
                    "cuts": [{"video_in_seconds": 40.0, "video_out_seconds": 90.0}],
                },
                {
                    "version_id": 901,
                    "cuts": [{"video_in_seconds": 120.0, "video_out_seconds": 200.0}],
                },
            ],
        }
        self.cuts_error: Exception | None = None
        self.posters: list[tuple[int, str, bytes]] = []

    async def list_chunks(self, playlist_id: int, after: int) -> dict:
        self.calls.append(f"list({after})")
        chunks = [
            {"seq": i, "size_bytes": len(p), "sha256": sha256_bytes(p)}
            for i, p in enumerate(self.parts)
            if i > after and i != self.hide_seq
        ]
        return {
            "chunks": chunks,
            "complete": self.complete,
            "start_time_utc": VIDEO_T0,
            "recording_id": self.recording_id,
        }

    async def get_chunk(self, playlist_id: int, seq: int) -> tuple[bytes, str | None]:
        self.calls.append(f"get({seq})")
        data = self.parts[seq]
        if seq == self.corrupt_seq:
            data = data + b"TAMPERED"  # the advertised hash no longer describes it
        return data, sha256_bytes(self.parts[seq])

    async def get_audio(self, playlist_id: int) -> tuple[bytes, dict]:
        self.calls.append("audio")
        if self.audio_error:
            raise self.audio_error
        return self.audio, {
            "start_time_utc": self.audio_start,
            "video_start_time_utc": VIDEO_T0,
        }

    async def record_archive(
        self,
        playlist_id: int,
        network_path: str,
        sha256: str,
        recording_id: int | None = None,
    ) -> dict:
        self.calls.append("archive")
        self.archived.append((network_path, sha256))
        self.archived_recording_ids.append(recording_id)
        return {"ok": True}

    async def delete_upstream(self, playlist_id: int) -> dict:
        self.calls.append("delete")
        self.deleted.append(playlist_id)
        return {"ok": True}

    async def get_cuts(self, playlist_id: int) -> dict:
        self.calls.append("cuts")
        if self.cuts_error:
            raise self.cuts_error
        return self.cuts

    async def upload_poster(
        self, playlist_id: int, version_id: int, filename: str, image: bytes
    ) -> dict:
        self.calls.append(f"poster({version_id})")
        self.posters.append((version_id, filename, image))
        return {"ok": True}


def make_collector(tmp_path, client, run_ffmpeg=None):
    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    staging.mkdir()
    archive.mkdir()

    def fake_ffmpeg(command: list[str]) -> tuple[int, str]:
        out = command[-1]
        if "-filter_complex" in command:
            # A poster grab. The real one decodes a frame and composites the badge; all the flow
            # needs is a distinct, non-empty file appearing where it was asked for.
            with open(out, "wb") as handle:
                handle.write(b"JPEG:" + os.path.basename(out).encode())
            return 0, ""
        # Stand in for the real mux: concatenate the two inputs so the output is a distinct,
        # non-empty file whose content depends on both, which is all the flow needs to be true.
        with open(out, "wb") as handle:
            handle.write(open(command[5], "rb").read() + open(command[7], "rb").read())
        return 0, ""

    return RecordingCollector(
        client=client,
        staging_dir=str(staging),
        archive_root=str(archive),
        ffmpeg_path="ffmpeg",
        run_ffmpeg=run_ffmpeg or fake_ffmpeg,
    )


def make_collector_reusing(collector, client):
    """A second collector over the same directories — a restart, or the next meeting."""
    return RecordingCollector(
        client=client,
        staging_dir=collector.staging_dir,
        archive_root=collector.archive_root,
        ffmpeg_path=collector.ffmpeg_path,
        run_ffmpeg=collector._run_ffmpeg,
    )


# ── resume planning: the pure decision a restart turns on ────────────────────────────────────────


def test_plan_resume_keeps_everything_when_the_file_matches():
    parts = [PartRecord(0, 10, "a"), PartRecord(1, 20, "b")]
    plan = plan_resume(parts, 30)
    assert plan.truncate_to == 30
    assert plan.keep_parts == parts
    assert plan.dropped == []
    assert plan.next_seq == 2


def test_plan_resume_trims_a_file_that_ran_ahead_of_the_state():
    """Crashed after appending, before recording it. The tail will be fetched again, so leaving
    it would duplicate those bytes in the middle of the stream."""
    parts = [PartRecord(0, 10, "a"), PartRecord(1, 20, "b")]
    plan = plan_resume(parts, 45)  # 15 bytes of a part the state never recorded
    assert plan.truncate_to == 30
    assert plan.next_seq == 2


def test_plan_resume_rewinds_when_the_append_was_cut_short():
    """The state claims a part the bytes do not fully cover — continuing would leave a hole."""
    parts = [PartRecord(0, 10, "a"), PartRecord(1, 20, "b"), PartRecord(2, 5, "c")]
    plan = plan_resume(parts, 25)  # part 1 ends at 30 — only half of it survived
    assert plan.truncate_to == 10
    assert plan.next_seq == 1
    assert [p.seq for p in plan.dropped] == [1, 2]


def test_plan_resume_from_nothing():
    assert plan_resume([], 0) == plan_resume([], 0)
    plan = plan_resume([], 0)
    assert plan.truncate_to == 0 and plan.next_seq == 0


# ── the audio offset ────────────────────────────────────────────────────────────────────────────


def test_audio_delay_is_the_difference_between_the_two_anchors():
    delay, source = compute_audio_delay_ms(VIDEO_T0, AUDIO_T0)
    assert delay == 1500
    assert source == "measured"


def test_audio_delay_falls_back_when_an_anchor_is_missing():
    assert compute_audio_delay_ms(VIDEO_T0, None) == (0, "assumed-together")
    assert compute_audio_delay_ms(None, AUDIO_T0) == (0, "assumed-together")
    assert compute_audio_delay_ms(VIDEO_T0, "not-a-time") == (0, "assumed-together")


def test_audio_delay_clamps_a_negative_rather_than_shifting_the_timeline():
    """Padding can only push audio later. A negative would need the video re-cut, which would
    invalidate every offset the cut list is computed against."""
    delay, source = compute_audio_delay_ms(AUDIO_T0, VIDEO_T0)
    assert delay == 0
    assert source == "clamped-negative"


def test_mux_command_copies_video_and_pads_audio():
    command = build_mux_command("ffmpeg", "v.mp4", "a.webm", "out.mp4", 1500)
    assert "-c:v" in command and command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-af") + 1] == "adelay=1500:all=1"
    assert command[-1] == "out.mp4"


def test_mux_command_omits_the_filter_when_there_is_nothing_to_pad():
    assert "-af" not in build_mux_command("ffmpeg", "v.mp4", "a.webm", "o.mp4", 0)


# ── mirroring ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parts_are_appended_in_order_and_reassemble_exactly(tmp_path):
    parts = [b"AAAA", b"BBBBBB", b"CC"]
    client = FakeClient(parts, complete=False)
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "mirroring"
    assert result["parts"] == 3
    assert open(collector.video_path(1, REC), "rb").read() == b"".join(parts)


@pytest.mark.asyncio
async def test_a_second_poll_fetches_only_what_is_new(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    client.parts.append(b"CCCC")
    client.calls.clear()
    await collector.poll_once(1)

    assert "get(2)" in client.calls
    assert "get(0)" not in client.calls, "already-held parts must not be re-fetched"
    assert open(collector.video_path(1, REC), "rb").read() == b"AAAABBBBCCCC"


@pytest.mark.asyncio
async def test_a_corrupt_part_is_not_appended_and_is_retried(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB", b"CCCC"], complete=True)
    client.corrupt_seq = 1
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert (
        result["status"] == "mirroring"
    ), "a bad part must not let the recording finalize"
    assert open(collector.video_path(1, REC), "rb").read() == b"AAAA"
    assert client.deleted == [], "nothing may be released while a part is unverified"

    client.corrupt_seq = None  # the retry succeeds
    result = await collector.poll_once(1)
    assert result["status"] == "archived"
    assert client.deleted == [1]


@pytest.mark.asyncio
async def test_a_hole_in_the_index_stops_the_pass_without_finalizing(tmp_path):
    """Parts arrive in order, so a missing seq means still-uploading, not never-coming. Appending
    past it would put later bytes at the wrong offset."""
    client = FakeClient([b"AAAA", b"BBBB", b"CCCC"], complete=True)
    client.hide_seq = 1
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "mirroring"
    assert open(collector.video_path(1, REC), "rb").read() == b"AAAA"
    assert client.deleted == []


# ── resuming for real, through the state file ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_restart_mid_meeting_resumes_rather_than_restarting(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    # A whole new process against the same staging directory.
    fresh_client = FakeClient([b"AAAA", b"BBBB", b"CCCC"], complete=False)
    resumed = RecordingCollector(
        client=fresh_client,
        staging_dir=collector.staging_dir,
        archive_root=collector.archive_root,
    )
    await resumed.poll_once(1)

    assert "get(0)" not in fresh_client.calls and "get(1)" not in fresh_client.calls
    assert "get(2)" in fresh_client.calls
    assert open(resumed.video_path(1, REC), "rb").read() == b"AAAABBBBCCCC"


@pytest.mark.asyncio
async def test_a_crash_between_the_append_and_the_state_write_is_trimmed(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    # Simulate dying just after appending part 2's bytes and before recording them.
    with open(collector.video_path(1, REC), "ab") as handle:
        handle.write(b"CCC")

    client.parts.append(b"CCCC")
    client.calls.clear()
    await collector.poll_once(1)

    assert "get(2)" in client.calls
    assert (
        open(collector.video_path(1, REC), "rb").read() == b"AAAABBBBCCCC"
    ), "the partially-written tail must be truncated, not left in the middle of the stream"


@pytest.mark.asyncio
async def test_a_torn_state_file_restarts_the_mirror_rather_than_stranding_it(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    with open(collector.state_path(1, REC), "w", encoding="utf-8") as handle:
        handle.write("{ this is not json")

    client.calls.clear()
    await collector.poll_once(1)
    assert (
        "get(0)" in client.calls
    ), "an unreadable state file must not strand the recording"


# ── taking custody ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_full_handover_happens_in_the_only_safe_order(tmp_path):
    client = FakeClient([b"AAAA", b"BBBB"], complete=True)
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "archived"
    assert client.calls.index("archive") < client.calls.index(
        "delete"
    ), "the archive must be recorded BEFORE the upstream copy is released"
    archived_name, archived_hash = client.archived[0]
    assert archived_name == os.path.basename(collector.archive_path(1, REC)), (
        "DNA is told the file's NAME, not where this host keeps it — the archiving host is "
        "across the airgap and its layout is nobody else's business"
    )
    archived_path = collector.archive_path(1, REC)
    assert os.path.exists(archived_path)
    assert hashlib.sha256(open(archived_path, "rb").read()).hexdigest() == archived_hash
    assert result["audio_delay_ms"] == 1500


@pytest.mark.asyncio
async def test_the_staging_copies_are_cleaned_up_once_the_archive_is_durable(tmp_path):
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)
    assert not os.path.exists(collector.video_path(1, REC))
    assert not os.path.exists(collector.audio_path(1, REC))


@pytest.mark.asyncio
async def test_a_failed_mux_aborts_without_releasing_upstream(tmp_path):
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(
        tmp_path, client, run_ffmpeg=lambda c: (1, "codec exploded")
    )

    with pytest.raises(MuxFailed):
        await collector.poll_once(1)

    assert client.archived == [] and client.deleted == []


@pytest.mark.asyncio
async def test_an_archive_that_reads_back_differently_is_refused(tmp_path):
    """The share is about to hold the only copy. The claim recorded is that these bytes can be
    READ BACK from there — a silently truncated write must not pass for a durable archive.
    """
    client = FakeClient([b"AAAA"], complete=True)

    def truncating_ffmpeg(command: list[str]) -> tuple[int, str]:
        with open(command[-1], "wb") as handle:
            handle.write(b"GOOD")
        return 0, ""

    collector = make_collector(tmp_path, client, run_ffmpeg=truncating_ffmpeg)

    real_sha256_file = __import__("dna.recording_collector", fromlist=["x"]).sha256_file
    calls = {"n": 0}

    def flaky(path, block_size=1024 * 1024):
        calls["n"] += 1
        return real_sha256_file(path) if calls["n"] == 1 else "0" * 64

    import dna.recording_collector as module

    module.sha256_file = flaky
    try:
        with pytest.raises(CollectorError, match="reads back as"):
            await collector.poll_once(1)
    finally:
        module.sha256_file = real_sha256_file

    assert (
        client.archived == []
    ), "nothing may be recorded when the archive does not verify"
    assert client.deleted == [], "and the upstream copy must survive"


@pytest.mark.asyncio
async def test_a_missing_audio_master_degrades_to_video_only(tmp_path):
    """A recording with no sound is worth far more than no recording."""
    client = FakeClient([b"AAAA", b"BBBB"], complete=True)
    client.audio_error = RuntimeError("audio master 404")
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "archived"
    assert result["audio_delay_source"] == "no-audio"
    assert open(collector.archive_path(1, REC), "rb").read() == b"AAAABBBB"
    assert client.deleted == [1]


@pytest.mark.asyncio
async def test_an_already_archived_playlist_is_not_collected_twice(tmp_path):
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    client.calls.clear()
    result = await collector.poll_once(1)

    assert result["status"] == "archived"
    # The index IS read again — it is what names the recording, and the state file cannot be
    # chosen before that is known. What must not happen is any of the expensive or destructive
    # work: no part is re-fetched, nothing is re-archived, nothing is deleted a second time.
    assert client.calls == ["list(-1)"]
    assert client.archived == [client.archived[0]], "must not archive twice"
    assert client.deleted == [1], "must not delete upstream twice"


@pytest.mark.asyncio
async def test_a_second_recording_on_the_same_playlist_gets_its_own_archive(tmp_path):
    """A playlist outlives any one meeting. The first archive must survive the second.

    This is the shape that destroyed a recording in practice: both meetings archived to
    playlist-<id>.mp4, and because the upstream copy is released immediately afterwards, the
    overwrite took the only remaining copy of the first one.
    """
    first = FakeClient([b"AAAA"], complete=True)
    first.recording_id = 1001
    collector = make_collector(tmp_path, first)
    await collector.poll_once(1)
    first_archive = collector.archive_path(1, 1001)

    # Same playlist and the same staging/archive dirs, a different meeting's recording.
    second = FakeClient([b"BBBBBB"], complete=True)
    second.recording_id = 2002
    collector.client = second
    await collector.poll_once(1)
    second_archive = collector.archive_path(1, 2002)

    assert first_archive != second_archive, "each recording needs its own archive path"
    assert os.path.exists(first_archive), "the first archive must not be destroyed"
    assert open(first_archive, "rb").read().startswith(b"AAAA")
    assert open(second_archive, "rb").read().startswith(b"BBBBBB")
    assert second.archived_recording_ids == [
        2002
    ], "DNA is told which recording this is"


@pytest.mark.asyncio
async def test_state_from_another_recording_is_not_resumed(tmp_path):
    """Resuming across recordings would splice two meetings into one file.

    Per-part hashes cannot catch it: every part of the new recording verifies correctly against
    its own index. Only the recording's identity distinguishes them.
    """
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)  # holds parts 0..1 of recording REC

    path = collector.state_path(1, REC)
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    assert len(raw["parts"]) == 2

    # A state file sitting at this recording's path but CLAIMING another recording — what a
    # pre-scoping state file left behind, or a hand-edited one, looks like.
    raw["recording_id"] = 9999
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)

    fresh = collector.load_state(1, REC)
    assert (
        fresh.parts == []
    ), "state naming another recording must be discarded, not resumed"
    assert fresh.recording_id == REC


@pytest.mark.asyncio
async def test_an_existing_archive_file_is_never_overwritten(tmp_path):
    """Belt and braces behind the naming: the archive is the only copy once upstream is released."""
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)

    destination = collector.archive_path(1, REC)
    with open(destination, "wb") as handle:
        handle.write(b"AN EARLIER RECORDING")

    with pytest.raises(CollectorError, match="refusing to overwrite"):
        await collector.poll_once(1)

    assert open(destination, "rb").read() == b"AN EARLIER RECORDING"
    assert client.deleted == [], "upstream must survive a refused archive"


@pytest.mark.asyncio
async def test_releasing_upstream_without_a_recorded_archive_is_refused(tmp_path):
    """The client-side half of the delete guard. DNA enforces this too, but a mistake should
    surface in this service's own logs rather than as a 409 from the far end."""
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)

    with pytest.raises(CollectorError, match="only other copy"):
        await collector.release_upstream(CollectorState(playlist_id=5))

    assert client.deleted == []


@pytest.mark.asyncio
async def test_a_part_whose_index_and_response_hashes_disagree_is_not_appended(
    tmp_path,
):
    """The index and the byte response are two separate claims about the same part. When they
    disagree, one of them is wrong and there is no way to tell which — so neither is trusted.
    """
    client = FakeClient([b"AAAA", b"BBBB"], complete=True)
    collector = make_collector(tmp_path, client)

    original = client.get_chunk

    async def disagreeing(playlist_id: int, seq: int):
        data, _ = await original(playlist_id, seq)
        return (
            (data, sha256_bytes(b"something else"))
            if seq == 1
            else (data, sha256_bytes(data))
        )

    client.get_chunk = disagreeing

    result = await collector.poll_once(1)

    assert result["status"] == "mirroring"
    assert open(collector.video_path(1, REC), "rb").read() == b"AAAA"
    assert client.deleted == []


def test_moving_across_filesystems_falls_back_to_a_copy(tmp_path, monkeypatch):
    """In production the staging directory and the archive share are different filesystems, so
    os.replace raises EXDEV and this fallback is the path that actually runs."""
    import dna.recording_collector as module

    source = tmp_path / "src.mp4"
    destination = tmp_path / "dst.mp4"
    source.write_bytes(b"PAYLOAD")

    real_replace = os.replace

    def cross_device(a, b):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(module.os, "replace", cross_device)
    module._move(str(source), str(destination))
    monkeypatch.setattr(module.os, "replace", real_replace)

    assert destination.read_bytes() == b"PAYLOAD"
    assert not source.exists(), "the staging copy must not be left behind"


@pytest.mark.asyncio
async def test_finalizing_with_nothing_staged_is_refused(tmp_path):
    client = FakeClient([], complete=True)
    collector = make_collector(tmp_path, client)

    with pytest.raises(CollectorError, match="nothing staged"):
        await collector.finalize(CollectorState(playlist_id=99))


def test_state_round_trips_through_the_file_format():
    state = CollectorState(
        playlist_id=7,
        parts=[PartRecord(0, 10, "aa"), PartRecord(1, 20, "bb")],
        video_start_time_utc=VIDEO_T0,
    )
    restored = CollectorState.from_dict(json.loads(json.dumps(state.as_dict())))
    assert restored == state
    assert restored.next_seq == 2
    assert restored.bytes_written == 30


@pytest.mark.asyncio
async def test_a_recording_change_mid_pass_abandons_the_pass(tmp_path):
    """The playlist moved to another recording while this pass was mirroring the previous one.

    Appending across that boundary splices two meetings into one file, and per-part hashes cannot
    catch it: every part of the new recording verifies correctly against its own index. The pass
    is abandoned so the next one picks the new recording up cleanly under its own state file.
    """
    client = FakeClient([b"AAAA", b"BBBB"], complete=False)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)  # mirrors recording REC

    state = collector.load_state(1, REC)
    assert state.recording_id == REC
    client.recording_id = 9999  # upstream is now serving a different recording

    with pytest.raises(CollectionFailed, match="abandoning this pass"):
        await collector.ingest_new_parts(state)

    assert client.deleted == [], "upstream must survive an abandoned pass"


def test_the_abandoned_pass_is_an_ordinary_retry_not_an_unexpected_failure(tmp_path):
    """The collector loop catches CollectorError and logs one line; anything else logs a
    traceback under "unexpected failure". A recording change mid-pass is expected and handled, so
    it must not arrive as the latter — which is what an undefined exception name would produce.
    """
    assert issubclass(CollectionFailed, CollectorError)


@pytest.mark.asyncio
async def test_an_unnamed_recording_falls_back_to_the_playlist_name(tmp_path):
    """When the index reports no recording id there is nothing to scope the archive by, so the
    name falls back to the playlist alone — the pre-scoping shape, which two meetings on one
    playlist would both claim.

    That collision is survivable rather than safe: the overwrite refusal catches the second one
    and the upstream copy stays put. Asserted here so the fallback's consequence is on the record
    rather than discovered the next time a deployment stops sending recording ids.
    """
    client = FakeClient([b"AAAA"], complete=True)
    client.recording_id = None
    collector = make_collector(tmp_path, client)

    await collector.poll_once(1)

    unscoped = collector.archive_path(1, None)
    assert unscoped.endswith("playlist-1.mp4"), "no recording id, no scoping"
    assert os.path.exists(unscoped)

    # A second meeting on the same playlist, equally unnamed, claims the same path. Staging is
    # cleared first because that too is scoped by the recording nobody named — the second meeting
    # would otherwise resume the first one's byte stream, which is the same collision one step
    # earlier.
    for path in (
        collector.state_path(1, None),
        collector.video_path(1, None),
        collector.audio_path(1, None),
    ):
        if os.path.exists(path):
            os.remove(path)
    second = FakeClient([b"BBBBBB"], complete=True)
    second.recording_id = None
    collector.client = second
    with pytest.raises(CollectorError, match="refusing to overwrite"):
        await collector.poll_once(1)

    assert open(unscoped, "rb").read().startswith(b"AAAA"), "the first archive survives"
    assert second.deleted == [], "upstream must survive a refused archive"


@pytest.mark.asyncio
async def test_a_state_with_no_recording_learns_it_from_the_index(tmp_path):
    """Identity has to arrive from somewhere before it can be checked.

    A state built before the index was read has no recording id, so the first pass takes the one
    the index reports and stamps it on. From then on the mismatch guard has something to compare
    against — without this the guard can never fire, because one side is always None.
    """
    client = FakeClient([b"AAAA"], complete=False)
    collector = make_collector(tmp_path, client)

    state = CollectorState(playlist_id=1)
    assert state.recording_id is None

    await collector.ingest_new_parts(state)

    assert state.recording_id == REC


# ── poster frames ───────────────────────────────────────────────────────────────────────────────
#
# Decoration, derived from a file that already exists — which is the whole point of the tests
# below. Every one of them is really asking the same question: can anything about a thumbnail
# reach back and touch the recording? It must not, so each failure mode is driven through the
# full pass and the archive is checked afterwards.


@pytest.mark.asyncio
async def test_a_poster_is_written_for_each_shot_after_the_handover(tmp_path):
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["posters"] == 2
    assert client.calls.index("delete") < client.calls.index("cuts"), (
        "frames are grabbed only once the custody chain has finished — nothing about a "
        "thumbnail may sit between archiving and releasing the upstream copy"
    )
    archive = os.path.basename(collector.archive_path(1, REC))
    stem = archive.rsplit(".", 1)[0]
    assert [name for _, name, _ in client.posters] == [
        f"{stem}-v900.jpg",
        f"{stem}-v901.jpg",
    ]
    for version_id, name, image in client.posters:
        # Both copies exist: the share's, which nginx serves, and DNA's, which the notes email
        # embeds because a mail client cannot always reach the share.
        on_share = os.path.join(collector.archive_root, name)
        assert os.path.exists(on_share)
        assert image == open(on_share, "rb").read()


@pytest.mark.asyncio
async def test_the_badge_is_drawn_once_into_staging_not_onto_the_share(tmp_path):
    """The share holds meeting media that outlives the container; a build artefact does not."""
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)

    await collector.poll_once(1)

    assert os.path.exists(collector.badge_path())
    assert collector.badge_path().startswith(collector.staging_dir)
    assert not [n for n in os.listdir(collector.archive_root) if n.endswith(".png")]


@pytest.mark.asyncio
async def test_a_cut_list_that_is_not_ready_yields_no_posters_and_no_complaint(
    tmp_path,
):
    client = FakeClient([b"AAAA"], complete=True)
    client.cuts = {"status": "no_segments", "versions": []}
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "archived" and result["posters"] == 0
    assert client.posters == []
    assert os.path.exists(collector.archive_path(1, REC))


@pytest.mark.asyncio
async def test_one_shot_whose_frame_cannot_be_grabbed_does_not_cost_the_others(
    tmp_path,
):
    def refuse_second_poster(command: list[str]) -> tuple[int, str]:
        out = command[-1]
        if "-filter_complex" in command:
            if out.endswith("-v901.jpg"):
                return 1, "Output file is empty"
            with open(out, "wb") as handle:
                handle.write(b"JPEG")
            return 0, ""
        with open(out, "wb") as handle:
            handle.write(open(command[5], "rb").read() + open(command[7], "rb").read())
        return 0, ""

    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client, run_ffmpeg=refuse_second_poster)

    result = await collector.poll_once(1)

    assert result["posters"] == 1
    assert [version_id for version_id, _, _ in client.posters] == [900]


@pytest.mark.asyncio
async def test_a_thumbnailer_that_fails_outright_still_leaves_the_recording_archived(
    tmp_path,
):
    """The one that matters. Losing the recording because a picture failed would be absurd."""
    client = FakeClient([b"AAAA"], complete=True)
    client.cuts_error = RuntimeError("cut list unavailable")
    collector = make_collector(tmp_path, client)

    result = await collector.poll_once(1)

    assert result["status"] == "archived"
    assert result["posters"] == 0
    assert client.deleted == [1], "the upstream copy was still released"
    assert os.path.exists(collector.archive_path(1, REC))


@pytest.mark.asyncio
async def test_posters_are_named_by_recording_so_a_second_meeting_replaces_nothing(
    tmp_path,
):
    client = FakeClient([b"AAAA"], complete=True)
    collector = make_collector(tmp_path, client)
    await collector.poll_once(1)

    second = FakeClient([b"CCCC"], complete=True)
    second.recording_id = REC + 1
    await make_collector_reusing(collector, second).poll_once(1)

    on_share = sorted(
        name for name in os.listdir(collector.archive_root) if name.endswith(".jpg")
    )
    assert on_share == [
        f"playlist-1-rec{REC}-v900.jpg",
        f"playlist-1-rec{REC}-v901.jpg",
        f"playlist-1-rec{REC + 1}-v900.jpg",
        f"playlist-1-rec{REC + 1}-v901.jpg",
    ]
