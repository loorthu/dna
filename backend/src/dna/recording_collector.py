"""The airgap collector — mirror a meeting recording as it is produced, then take custody of it.

WHERE THIS RUNS: beside the prod nginx, on the airgapped side. It is the ONLY thing on that side
that reaches DNA for media, and DNA is the only thing that reaches Vexa. The browser never crosses
the airgap at all; it plays a finished file from a network path that nginx serves directly.

WHY A SERVICE AND NOT THE BROWSER: a page cannot write to a network filesystem, the prod origin is
plain HTTP so ``crypto.subtle`` is undefined there, a reload would drop several hundred MB of
accumulated state, and nothing would resume. All four vanish here, and hashing becomes one call.

THE ORDERING RULE, which is the whole point of the design:

    assemble  →  verify  →  write to the network path  →  re-verify what landed there
              →  record the archive in DNA  →  and only THEN delete upstream

Until the archive is recorded, Vexa holds the only copy. DNA refuses the delete server-side until
it has a path and a hash, so the rule survives a bug in this file; the same check is made here so
a mistake is caught before it is sent rather than after.

RESUMING IS NOT OPTIONAL. A meeting runs for an hour and this process can be restarted at any
moment within it. Progress is therefore a fact about the STAGING FILE, reconciled against a state
file on every start: the parts already appended are re-derived from the bytes actually on disk,
not trusted from a counter that a crash may have left ahead of reality.
"""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """The collection could not be completed. Always safe to retry — nothing was deleted."""


class MuxFailed(CollectorError):
    """ffmpeg refused to combine the two streams."""


# ── the state a restart is reconstructed from ───────────────────────────────────────────────────


@dataclass(frozen=True)
class PartRecord:
    """One part as the index described it, and as it was appended."""

    seq: int
    size_bytes: int
    sha256: Optional[str] = None

    @classmethod
    def from_index(cls, entry: dict[str, Any]) -> "PartRecord":
        return cls(
            seq=int(entry["seq"]),
            size_bytes=int(entry.get("size_bytes") or 0),
            sha256=entry.get("sha256"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass
class CollectorState:
    """What has been mirrored for one playlist so far."""

    playlist_id: int
    parts: list[PartRecord] = field(default_factory=list)
    complete: bool = False
    video_start_time_utc: Optional[str] = None
    archived_path: Optional[str] = None
    archived_sha256: Optional[str] = None

    @property
    def next_seq(self) -> int:
        """The lowest seq not yet held. Parts are contiguous from 0 by construction."""
        return self.parts[-1].seq + 1 if self.parts else 0

    @property
    def bytes_written(self) -> int:
        return sum(p.size_bytes for p in self.parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "playlist_id": self.playlist_id,
            "parts": [p.as_dict() for p in self.parts],
            "complete": self.complete,
            "video_start_time_utc": self.video_start_time_utc,
            "archived_path": self.archived_path,
            "archived_sha256": self.archived_sha256,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CollectorState":
        return cls(
            playlist_id=int(raw["playlist_id"]),
            parts=[PartRecord(**p) for p in raw.get("parts", [])],
            complete=bool(raw.get("complete")),
            video_start_time_utc=raw.get("video_start_time_utc"),
            archived_path=raw.get("archived_path"),
            archived_sha256=raw.get("archived_sha256"),
        )


@dataclass(frozen=True)
class ResumePlan:
    """How to reconcile a state file against the staging bytes that actually survived."""

    truncate_to: int
    keep_parts: list[PartRecord]
    dropped: list[PartRecord]

    @property
    def next_seq(self) -> int:
        return self.keep_parts[-1].seq + 1 if self.keep_parts else 0


def plan_resume(parts: list[PartRecord], file_size: int) -> ResumePlan:
    """Reconcile recorded parts against the staging file's real size.

    The state file and the staging file are written separately, so a crash can land between them
    in either direction, and BOTH directions are silently corrupting if trusted:

      • file LONGER than the state (crashed after appending, before recording it) — the tail is a
        part that will be fetched again, so leaving it would duplicate those bytes mid-stream.
      • file SHORTER than the state (the append itself was cut short) — the state claims parts
        that are not all there, so continuing from ``next_seq`` would leave a hole.

    Both are handled the same way: keep the longest prefix of parts that the bytes on disk fully
    cover, and truncate to exactly that boundary. Whatever is dropped is simply fetched again.
    """
    keep: list[PartRecord] = []
    offset = 0
    for part in parts:
        end = offset + part.size_bytes
        if end > file_size:
            break
        keep.append(part)
        offset = end
    return ResumePlan(truncate_to=offset, keep_parts=keep, dropped=parts[len(keep) :])


# ── the pieces that touch the world, kept behind narrow seams so the flow is drivable offline ───


class CollectorClient(Protocol):
    """DNA's relay, as this module needs it."""

    async def list_chunks(self, playlist_id: int, after: int) -> dict[str, Any]: ...
    async def get_chunk(
        self, playlist_id: int, seq: int
    ) -> tuple[bytes, Optional[str]]: ...
    async def get_audio(self, playlist_id: int) -> tuple[bytes, dict[str, Any]]: ...
    async def record_archive(
        self, playlist_id: int, network_path: str, sha256: str
    ) -> dict[str, Any]: ...
    async def delete_upstream(self, playlist_id: int) -> dict[str, Any]: ...


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str, block_size: int = 1024 * 1024) -> str:
    """Hash a file in blocks — the assembled recording does not fit comfortably in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compute_audio_delay_ms(
    video_start_utc: Optional[str], audio_start_utc: Optional[str]
) -> tuple[int, str]:
    """How far behind the video the audio starts, in ms, and how confident that number is.

    The bot starts the video recorder before the audio tap on purpose, so this is normally a
    small positive number taken from ONE clock (the bot's) for both streams, which makes it
    exact rather than an estimate across two containers.

    A negative result means that ordering was somehow violated. It is clamped to zero and
    reported: padding can only ever push audio LATER, so a genuinely early audio track cannot be
    corrected here — it would need the video re-cut, which would destroy the offsets the cut list
    depends on. Better a known small mis-sync than a silently shifted timeline.
    """
    video = _parse_utc(video_start_utc)
    audio = _parse_utc(audio_start_utc)
    if video is None or audio is None:
        return 0, "assumed-together"
    delta_ms = int(round((audio - video).total_seconds() * 1000))
    if delta_ms < 0:
        logger.warning(
            "Audio starts %d ms BEFORE video, which the bot's ordering should prevent; "
            "clamping to 0 — expect the audio to run that far early",
            -delta_ms,
        )
        return 0, "clamped-negative"
    return delta_ms, "measured"


def build_mux_command(
    ffmpeg: str, video_path: str, audio_path: str, out_path: str, audio_delay_ms: int
) -> list[str]:
    """The one ffmpeg invocation this service makes.

    ``-c:v copy`` — the video is already h264 and must not be re-encoded: it would cost quality
    and a great deal of CPU, and it would shift frame timings the cut list is computed against.

    ``adelay`` rather than ``-itsoffset`` — the audio is being re-encoded to AAC regardless (Opus
    in MP4 plays in neither Safari nor QuickTime), so padding with real silence is nearly free,
    and it produces a track that starts at zero everywhere instead of a leading sample gap that
    players interpret inconsistently.
    """
    args = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
    ]
    if audio_delay_ms > 0:
        args += ["-af", f"adelay={audio_delay_ms}:all=1"]
    # +faststart moves the index to the front. The fragmented layout the bot streamed was for
    # progressive assembly; this file is finished and is about to be range-served by nginx, where
    # an index up front is what makes seeking to a cut immediate.
    args += ["-movflags", "+faststart", out_path]
    return args


# ── the flow ────────────────────────────────────────────────────────────────────────────────────


class RecordingCollector:
    """Mirror, assemble, mux, archive and only then release the upstream copy."""

    def __init__(
        self,
        client: CollectorClient,
        staging_dir: str,
        archive_root: str,
        ffmpeg_path: str = "ffmpeg",
        run_ffmpeg: Optional[Callable[[list[str]], tuple[int, str]]] = None,
    ):
        self.client = client
        self.staging_dir = staging_dir
        self.archive_root = archive_root
        self.ffmpeg_path = ffmpeg_path
        self._run_ffmpeg = run_ffmpeg or _run_ffmpeg_subprocess

    # -- paths ----------------------------------------------------------------------------------

    def video_path(self, playlist_id: int) -> str:
        return os.path.join(self.staging_dir, f"{playlist_id}.video.mp4")

    def audio_path(self, playlist_id: int) -> str:
        return os.path.join(self.staging_dir, f"{playlist_id}.audio.webm")

    def state_path(self, playlist_id: int) -> str:
        return os.path.join(self.staging_dir, f"{playlist_id}.state.json")

    def archive_path(self, playlist_id: int) -> str:
        return os.path.join(self.archive_root, f"playlist-{playlist_id}.mp4")

    # -- state ----------------------------------------------------------------------------------

    def load_state(self, playlist_id: int) -> CollectorState:
        """The state file reconciled against the staging bytes that actually survived.

        Reconciliation happens HERE rather than at write time because a crash is exactly the case
        where the two disagree, and a restart is the only moment anyone can notice.
        """
        path = self.state_path(playlist_id)
        if not os.path.exists(path):
            return CollectorState(playlist_id=playlist_id)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = CollectorState.from_dict(json.load(handle))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # A torn state file must not strand the recording forever. Starting the mirror over
            # costs one re-fetch; refusing to start costs the recording.
            logger.warning(
                "Playlist %s: unreadable state file (%s) — restarting the mirror",
                playlist_id,
                e,
            )
            return CollectorState(playlist_id=playlist_id)

        video = self.video_path(playlist_id)
        size = os.path.getsize(video) if os.path.exists(video) else 0
        plan = plan_resume(state.parts, size)
        if plan.dropped or plan.truncate_to != size:
            logger.info(
                "Playlist %s: resuming at %d bytes / seq %d (state claimed %d parts, %d bytes "
                "on disk); re-fetching %d part(s)",
                playlist_id,
                plan.truncate_to,
                plan.next_seq,
                len(state.parts),
                size,
                len(plan.dropped),
            )
            if os.path.exists(video):
                with open(video, "r+b") as handle:
                    handle.truncate(plan.truncate_to)
            state.parts = plan.keep_parts
            self.save_state(state)
        return state

    def save_state(self, state: CollectorState) -> None:
        """Write the state file atomically — a torn write here is a lost recording on restart."""
        path = self.state_path(state.playlist_id)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state.as_dict(), handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    # -- mirroring ------------------------------------------------------------------------------

    async def ingest_new_parts(self, state: CollectorState) -> tuple[int, bool]:
        """Fetch, verify and append every part newer than the ones already held.

        Returns ``(parts_appended, complete)``. A part that fails verification stops the pass
        WITHOUT advancing: the stream is a byte concatenation, so skipping a bad part would not
        leave a gap, it would corrupt everything after it. Retrying next poll is free.
        """
        playlist_id = state.playlist_id
        index = await self.client.list_chunks(playlist_id, after=state.next_seq - 1)
        state.video_start_time_utc = (
            index.get("start_time_utc") or state.video_start_time_utc
        )
        entries = sorted(
            (e for e in index.get("chunks", []) if int(e["seq"]) >= state.next_seq),
            key=lambda e: int(e["seq"]),
        )

        appended = 0
        for entry in entries:
            part = PartRecord.from_index(entry)
            if part.seq != state.next_seq:
                # A hole in the index. Waiting is right: parts arrive in order, so a missing seq
                # means it is still uploading, not that it will never come.
                logger.info(
                    "Playlist %s: waiting for part %d (index jumps to %d)",
                    playlist_id,
                    state.next_seq,
                    part.seq,
                )
                break

            data, advertised = await self.client.get_chunk(playlist_id, part.seq)
            actual = sha256_bytes(data)
            expected = part.sha256 or advertised
            if expected and actual != expected:
                logger.error(
                    "Playlist %s part %d: sha256 mismatch (index %s, got %s) — not appending; "
                    "will retry",
                    playlist_id,
                    part.seq,
                    expected,
                    actual,
                )
                break
            if advertised and part.sha256 and advertised != part.sha256:
                logger.error(
                    "Playlist %s part %d: the index and the response disagree on the hash "
                    "(%s vs %s) — not appending",
                    playlist_id,
                    part.seq,
                    part.sha256,
                    advertised,
                )
                break

            # Bytes first, then the record of them. The reverse order would let a crash leave the
            # state claiming a part the file does not contain, which is the harder direction to
            # detect; this way the file is merely ahead, and plan_resume trims it.
            with open(self.video_path(playlist_id), "ab") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            state.parts.append(
                PartRecord(seq=part.seq, size_bytes=len(data), sha256=actual)
            )
            self.save_state(state)
            appended += 1

        # "Done" means the index says the upload finished AND nothing it listed is still
        # outstanding. Either break above (a hole, or a bad hash) leaves entries unconsumed, and
        # finalizing then would archive a truncated recording as if it were the whole meeting.
        outstanding = [e for e in entries if int(e["seq"]) >= state.next_seq]
        return appended, bool(index.get("complete")) and not outstanding

    # -- taking custody -------------------------------------------------------------------------

    async def finalize(self, state: CollectorState) -> dict[str, Any]:
        """Mux, write to the network path, verify what landed, record it, release upstream."""
        playlist_id = state.playlist_id
        video = self.video_path(playlist_id)
        if not os.path.exists(video) or os.path.getsize(video) == 0:
            raise CollectorError(f"Playlist {playlist_id}: nothing staged to finalize")

        audio_delay_ms, delay_source = 0, "no-audio"
        audio = self.audio_path(playlist_id)
        try:
            data, meta = await self.client.get_audio(playlist_id)
            with open(audio, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            audio_delay_ms, delay_source = compute_audio_delay_ms(
                meta.get("video_start_time_utc") or state.video_start_time_utc,
                meta.get("start_time_utc"),
            )
        except Exception as e:
            # A recording with no sound is worth far more than no recording. This is the one
            # failure on the path that degrades rather than aborts.
            logger.warning(
                "Playlist %s: no audio master (%s) — archiving video-only",
                playlist_id,
                e,
            )
            audio = ""

        out = os.path.join(self.staging_dir, f"{playlist_id}.final.mp4")
        if audio:
            command = build_mux_command(
                self.ffmpeg_path, video, audio, out, audio_delay_ms
            )
            code, stderr = await asyncio.to_thread(self._run_ffmpeg, command)
            if code != 0:
                raise MuxFailed(
                    f"Playlist {playlist_id}: ffmpeg exited {code}: {stderr.strip()[:500]}"
                )
            logger.info(
                "Playlist %s: muxed audio %d ms behind video (%s)",
                playlist_id,
                audio_delay_ms,
                delay_source,
            )
        else:
            os.replace(video, out)

        destination = self.archive_path(playlist_id)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        digest = sha256_file(out)
        _move(out, destination)

        # Re-hash what is actually READABLE at the network path. The archive is about to become
        # the only copy, and the claim being recorded is not "the mux produced these bytes" but
        # "these bytes can be read back from there" — a share that silently truncated or refused
        # the write must not pass for a durable archive.
        landed = sha256_file(destination)
        if landed != digest:
            raise CollectorError(
                f"Playlist {playlist_id}: archive at {destination} reads back as {landed}, "
                f"not {digest} — refusing to record it or release upstream"
            )

        await self.client.record_archive(playlist_id, destination, digest)
        state.archived_path, state.archived_sha256 = destination, digest
        state.complete = True
        self.save_state(state)

        await self.release_upstream(state)
        logger.info(
            "Playlist %s: archived at %s (sha256 %s…) and released upstream",
            playlist_id,
            destination,
            digest[:12],
        )

        for leftover in (self.video_path(playlist_id), self.audio_path(playlist_id)):
            if os.path.exists(leftover):
                os.remove(leftover)
        return {
            "playlist_id": playlist_id,
            "network_path": destination,
            "sha256": digest,
            "audio_delay_ms": audio_delay_ms,
            "audio_delay_source": delay_source,
        }

    async def release_upstream(self, state: CollectorState) -> None:
        """Delete the upstream copy — the last step, and the only irreversible one.

        The precondition is stated here as well as enforced by DNA because the two failures are
        different: DNA's guard stops a bad request from destroying the media, while this one stops
        the request from being formed at all, so the mistake surfaces in this service's logs
        rather than as a 409 from the far end.
        """
        if not (state.archived_path and state.archived_sha256):
            raise CollectorError(
                f"Playlist {state.playlist_id}: refusing to delete the upstream copy without a "
                f"recorded archive — it is the only other copy"
            )
        await self.client.delete_upstream(state.playlist_id)

    async def poll_once(self, playlist_id: int) -> dict[str, Any]:
        """One pass for one playlist: mirror what is new, and finish if the recording is done."""
        state = self.load_state(playlist_id)
        if state.complete and state.archived_path:
            return {"playlist_id": playlist_id, "status": "archived"}

        appended, complete = await self.ingest_new_parts(state)
        if not complete:
            return {
                "playlist_id": playlist_id,
                "status": "mirroring",
                "parts": len(state.parts),
                "appended": appended,
                "bytes": state.bytes_written,
            }
        result = await self.finalize(state)
        return {"status": "archived", **result}


def _run_ffmpeg_subprocess(command: list[str]) -> tuple[int, str]:
    import subprocess

    proc = subprocess.run(command, capture_output=True, text=True)
    return proc.returncode, proc.stderr


def _move(source: str, destination: str) -> None:
    """Rename where possible, copy across filesystems — the archive is usually a network mount."""
    try:
        os.replace(source, destination)
    except OSError:
        import shutil

        shutil.copyfile(source, destination)
        os.remove(source)
