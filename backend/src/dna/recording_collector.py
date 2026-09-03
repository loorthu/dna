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

from dna.recording_archive_path import is_safe_relative_path
from dna.recording_posters import (
    BADGE_SIZE,
    build_poster_command,
    first_cuts,
    poster_filename,
    poster_lead_seconds,
    poster_time_seconds,
    render_play_badge_png,
)

logger = logging.getLogger(__name__)

# How many consecutive failed passes make a stall rather than a blip. At the default ten-second
# poll this is about half a minute — long enough that a slow share or a backend restarting does
# not reach the player, short enough that nobody watches a progress step for an hour wondering.
FAILURES_BEFORE_REPORTING = 3


class CollectorError(Exception):
    """The collection could not be completed. Always safe to retry — nothing was deleted."""


class MuxFailed(CollectorError):
    """ffmpeg refused to combine the two streams."""


class ArchiveDirectoryMissing(CollectorError):
    """The show's recording directory is not on the share, and this side must not create it.

    A show's directory tree is made by the studio, with the ownership and permissions the studio
    means it to have. The first recording for a new show therefore waits for a person; every one
    after it just works, because only the dated directory below is created here.

    Distinct from its siblings because it is the one failure that will never clear by retrying,
    which is why it is the one reported back to DNA for the player to show.
    """


class CollectionFailed(CollectorError):
    """This pass cannot continue, but nothing is wrong that a later pass will not resolve.

    A CollectorError like any other — the upstream copy is intact and the next poll retries. It
    is named apart from its parent only so the log says which kind of "try again" this was.
    """


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
    # WHICH recording these parts came from. Without it the state was keyed on the playlist
    # alone, so a second meeting resumed the first one's byte stream — appending new parts onto
    # old ones, which per-part hashes cannot detect because each new part verifies fine against
    # its own index.
    recording_id: Optional[int] = None
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
            "recording_id": self.recording_id,
            "parts": [p.as_dict() for p in self.parts],
            "complete": self.complete,
            "video_start_time_utc": self.video_start_time_utc,
            "archived_path": self.archived_path,
            "archived_sha256": self.archived_sha256,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CollectorState":
        recording_id = raw.get("recording_id")
        return cls(
            playlist_id=int(raw["playlist_id"]),
            recording_id=int(recording_id) if recording_id is not None else None,
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
        self,
        playlist_id: int,
        network_path: str,
        sha256: str,
        recording_id: Optional[int] = None,
    ) -> dict[str, Any]: ...
    async def delete_upstream(self, playlist_id: int) -> dict[str, Any]: ...
    async def get_cuts(self, playlist_id: int) -> dict[str, Any]: ...
    async def get_archive_name(
        self, playlist_id: int, suffix: str = ""
    ) -> dict[str, Any]: ...
    async def report_blocked(self, playlist_id: int, reason: str) -> dict[str, Any]: ...
    async def upload_poster(
        self, playlist_id: int, version_id: int, filename: str, image: bytes
    ) -> dict[str, Any]: ...


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
        archive_dir_template: Optional[str] = None,
        ffmpeg_path: str = "ffmpeg",
        run_ffmpeg: Optional[Callable[[list[str]], tuple[int, str]]] = None,
    ):
        self.client = client
        self.staging_dir = staging_dir
        self.archive_root = archive_root
        # Where a show's recordings are filed, with `{show}` standing in for the show. Defaults to
        # one directory per show directly under the served root — the plain arrangement, for a
        # deployment that has no opinion. A studio with an existing layout configures its own.
        self.archive_dir_template = archive_dir_template or os.path.join(
            archive_root, "{show}"
        )
        self.ffmpeg_path = ffmpeg_path
        self._run_ffmpeg = run_ffmpeg or _run_ffmpeg_subprocess
        # What has already been reported to DNA, so a blocked playlist is not re-posted every
        # ten seconds for as long as it stays blocked. Deliberately in memory: a restart
        # re-reporting once is harmless, and is the right behaviour if DNA was the thing down.
        self._reported: dict[int, str] = {}
        # Consecutive failed passes per playlist, for telling a blip apart from a stall.
        self._failures: dict[int, int] = {}

    # -- paths ----------------------------------------------------------------------------------

    # Every STAGING path is scoped by RECORDING, not just playlist. A playlist outlives any one
    # meeting, so playlist-only names made the second meeting collide with the first: staging
    # resumed the wrong byte stream, and the archive silently overwrote a file whose upstream
    # copy had already been released — destroying the only remaining copy.
    #
    # The ARCHIVE is named by DNA instead (archive_destination below), from the playlist and the
    # meeting's start clock, and placed by this deployment's configured directory. Those are
    # facts about the meeting rather than ids, so the same collision cannot come back through
    # them — two recordings of one playlist a minute apart is the only overlap, and that is
    # handled where it is discovered.
    def _scope(self, playlist_id: int, recording_id: Optional[int]) -> str:
        return (
            f"{playlist_id}-{recording_id}"
            if recording_id is not None
            else str(playlist_id)
        )

    def video_path(self, playlist_id: int, recording_id: Optional[int] = None) -> str:
        return os.path.join(
            self.staging_dir, f"{self._scope(playlist_id, recording_id)}.video.mp4"
        )

    def audio_path(self, playlist_id: int, recording_id: Optional[int] = None) -> str:
        return os.path.join(
            self.staging_dir, f"{self._scope(playlist_id, recording_id)}.audio.webm"
        )

    def state_path(self, playlist_id: int, recording_id: Optional[int] = None) -> str:
        return os.path.join(
            self.staging_dir, f"{self._scope(playlist_id, recording_id)}.state.json"
        )

    def archive_directory(self, show: str) -> str:
        """The directory this deployment files `show`'s recordings in.

        The template is the deployment's, not this code's: which folders a studio keeps recordings
        under is a fact about that studio's filesystem, and one site's layout baked into the
        naming rule is a naming rule nobody else can adopt. So it arrives as configuration, with
        `{show}` wherever the show belongs in it.
        """
        return self.archive_dir_template.replace("{show}", show).rstrip("/")

    async def archive_destination(
        self, playlist_id: int, recording_id: Optional[int] = None
    ) -> tuple[str, str]:
        """Where this recording is filed, as (relative path, absolute path).

        Two halves meeting here, and neither side can supply the other's. DNA says what the file
        is called and which show it belongs to — both live in the tracking system, which this side
        cannot reach. This deployment says which directory a show's recordings go in. Only here
        are both known.

        The relative half is derived from the absolute one rather than sent by DNA, so the
        configured directory is the single place the layout is written down. It is what DNA
        stores and nginx serves, which is why it must resolve UNDER the served root.

        A destination that already exists is NOT overwritten and NOT quietly renamed here: DNA is
        asked again for a name carrying the recording id. The file already there may be the only
        copy of a meeting, since the upstream is released the moment an archive is recorded, and
        two recordings of one playlist within the same minute is the only way to reach this.
        """
        try:
            answer = await self.client.get_archive_name(playlist_id)
        except Exception as e:
            # Retryable, and nothing is lost by waiting: the upstream copy is intact and the
            # staged bytes survive. Archiving under some fallback name would be worse — the file
            # would land where nobody looks for it, under a name nothing can later reconcile.
            raise CollectionFailed(
                f"Playlist {playlist_id}: DNA cannot say what to call this recording ({e})"
            )
        directory = self.archive_directory(answer["show"])
        self.require_archive_directory(playlist_id, directory)

        absolute = os.path.join(directory, answer["date_dir"], answer["filename"])
        if os.path.exists(absolute) and recording_id is not None:
            answer = await self.client.get_archive_name(
                playlist_id, suffix=f"_rec{recording_id}"
            )
            absolute = os.path.join(directory, answer["date_dir"], answer["filename"])
            logger.warning(
                "Playlist %s: archive name was already taken — filing this recording as %s",
                playlist_id,
                os.path.basename(absolute),
            )
        return self.relative_to_root(absolute), absolute

    def relative_to_root(self, absolute: str) -> str:
        """The path under the root nginx serves — what DNA stores and the player fetches.

        A configured directory outside that root is a misconfiguration this must not paper over:
        the file would archive perfectly and every emitted URL would resolve somewhere else, or
        nowhere. Caught here, where the two settings are first compared, rather than as a 404 a
        week later.
        """
        relative = os.path.relpath(absolute, self.archive_root)
        if not is_safe_relative_path(relative):
            raise CollectionFailed(
                f"{absolute} is not under the served root {self.archive_root} — "
                f"RECORDING_ARCHIVE_DIR and RECORDING_NETWORK_PATH disagree, and a recording "
                f"filed there could never be played back"
            )
        return relative

    def require_archive_directory(self, playlist_id: int, directory: str) -> None:
        """The configured directory must already exist. Only the DATED one below it is created.

        Deliberately not `makedirs` all the way up. That directory is part of a tree the studio
        owns — made with the ownership and permissions it means them to have — and one invented
        here would carry the collector's uid, in a place people expect their own layout. It would
        also hide the real problem: a share that is not mounted, and a show nobody has set up for
        recording, both look exactly like a missing directory, and silently creating one turns
        either into a recording filed where no one will look for it.

        So the first recording for a new show waits for a person, once. After that this passes and
        the dated directory is made per meeting.
        """
        if os.path.islink(directory) and not os.path.exists(directory):
            # A symlink whose TARGET this process cannot reach — the ordinary shape of a share
            # where each show's storage lives on its own volume. `isdir` follows the link, so
            # this is indistinguishable from a missing directory unless it is asked about
            # separately, and reporting "does not exist" about a path that plainly does sends
            # whoever reads it to check the wrong thing.
            raise ArchiveDirectoryMissing(
                f"{directory} is a symlink to {os.readlink(directory)}, which cannot be reached "
                f"from here. The link resolves on the host but its target is not mounted in this "
                f"container — mount the target as well, at the same path."
            )
        if not os.path.isdir(directory):
            raise ArchiveDirectoryMissing(
                f"{directory} does not exist on the recordings host. It has to be created once, "
                f"by hand, before recordings for this show can be filed — everything below it is "
                f"made automatically."
            )

    # -- state ----------------------------------------------------------------------------------

    def load_state(
        self, playlist_id: int, recording_id: Optional[int] = None
    ) -> CollectorState:
        """The state file reconciled against the staging bytes that actually survived.

        Reconciliation happens HERE rather than at write time because a crash is exactly the case
        where the two disagree, and a restart is the only moment anyone can notice.
        """
        path = self.state_path(playlist_id, recording_id)
        if not os.path.exists(path):
            return CollectorState(playlist_id=playlist_id, recording_id=recording_id)
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
            return CollectorState(playlist_id=playlist_id, recording_id=recording_id)

        # Belt and braces: the filename already scopes by recording, but a state file that names
        # a DIFFERENT recording must never be resumed — that is the splice this fix exists to
        # prevent, and it costs one re-fetch to refuse.
        if (
            recording_id is not None
            and state.recording_id is not None
            and state.recording_id != recording_id
        ):
            logger.warning(
                "Playlist %s: staged state belongs to recording %s, not %s — starting fresh",
                playlist_id,
                state.recording_id,
                recording_id,
            )
            return CollectorState(playlist_id=playlist_id, recording_id=recording_id)
        state.recording_id = recording_id or state.recording_id

        video = self.video_path(playlist_id, state.recording_id)
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
        path = self.state_path(state.playlist_id, state.recording_id)
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
        indexed_recording = index.get("recording_id")
        if (
            indexed_recording is not None
            and state.recording_id is not None
            and int(indexed_recording) != state.recording_id
        ):
            # The playlist moved to another recording mid-pass. Appending across that boundary is
            # the corruption this guards; the next poll picks the new recording up cleanly under
            # its own state file.
            raise CollectionFailed(
                f"Playlist {playlist_id}: index now reports recording {indexed_recording}, "
                f"but {state.recording_id} is being mirrored — abandoning this pass"
            )
        if state.recording_id is None and indexed_recording is not None:
            state.recording_id = int(indexed_recording)
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
            with open(self.video_path(playlist_id, state.recording_id), "ab") as handle:
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
        recording_id = state.recording_id
        video = self.video_path(playlist_id, recording_id)
        if not os.path.exists(video) or os.path.getsize(video) == 0:
            raise CollectorError(f"Playlist {playlist_id}: nothing staged to finalize")

        audio_delay_ms, delay_source = 0, "no-audio"
        audio = self.audio_path(playlist_id, recording_id)
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

        out = os.path.join(
            self.staging_dir, f"{self._scope(playlist_id, recording_id)}.final.mp4"
        )
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

        relative, destination = await self.archive_destination(
            playlist_id, recording_id
        )
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        # Never write over an existing archive. archive_destination has already asked for a
        # distinguishing name if the first one was taken, so this should be unreachable — but the
        # failure it guards is unrecoverable: the upstream copy is released right after
        # archiving, so an overwrite destroys the only remaining copy.
        if os.path.exists(destination):
            raise CollectorError(
                f"Playlist {playlist_id}: {destination} already exists — refusing to overwrite "
                f"an archive (it may be the only copy of that recording)"
            )
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

        # The path RELATIVE to the share root, not the absolute one. DNA needs to find the file
        # under the root nginx serves; where THIS host mounts that root is local knowledge, and
        # this side of the airgap holds the only copy of the media. The absolute path stays in
        # the local state file below, which is where the resume logic needs it.
        await self.client.record_archive(
            playlist_id,
            relative,
            digest,
            recording_id=recording_id,
        )
        self._reported.pop(playlist_id, None)
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

        for leftover in (
            self.video_path(playlist_id, recording_id),
            self.audio_path(playlist_id, recording_id),
        ):
            if os.path.exists(leftover):
                os.remove(leftover)
        return {
            "playlist_id": playlist_id,
            "network_path": destination,
            "relative_path": relative,
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

    # -- poster frames -------------------------------------------------------------------------

    def badge_path(self) -> str:
        """The play badge, rendered once per process into staging and reused.

        In staging rather than beside the archives because it is scratch, not a recording: the
        share holds meeting media that outlives this container, and a build artefact of the
        thumbnailer does not belong in it.
        """
        path = os.path.join(self.staging_dir, f"play-badge-{BADGE_SIZE}.png")
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(render_play_badge_png(BADGE_SIZE))
        return path

    async def write_posters(self, state: CollectorState) -> dict[int, str]:
        """One still per shot, written beside the archive and pushed to DNA.

        Called only once the archive is recorded and the upstream copy released — the custody
        chain is finished before a single frame is grabbed, so nothing here can reorder it.

        Failures are per shot and never raise. A poster is a visual cue derived from a file that
        already exists; losing one costs the cue, and the same frame can always be grabbed again
        from the archive. Losing the recording because a thumbnail failed would be absurd.
        """
        archive = state.archived_path
        if not archive or not os.path.exists(archive):
            return {}

        payload = await self.client.get_cuts(state.playlist_id)
        spans = first_cuts(payload)
        if not spans:
            logger.info(
                "Playlist %s: no poster frames (cut list is %s)",
                state.playlist_id,
                payload.get("status"),
            )
            return {}

        badge = self.badge_path()
        lead = poster_lead_seconds()
        # Beside the archive, in its show's dated directory — not in the share root, which is now
        # the top of a tree of shows and belongs to nobody. A poster is a derivative of that one
        # file and travels with it.
        archive_dir = os.path.dirname(archive)
        written: dict[int, str] = {}
        for version_id, video_in, video_out in spans:
            name = poster_filename(archive, version_id)
            destination = os.path.join(archive_dir, name)
            at = poster_time_seconds(video_in, video_out, lead)
            try:
                command = build_poster_command(
                    self.ffmpeg_path, archive, badge, destination, at
                )
                code, stderr = await asyncio.to_thread(self._run_ffmpeg, command)
                if code != 0 or not os.path.exists(destination):
                    raise CollectorError(
                        f"ffmpeg exited {code} at {at:.1f}s: {stderr.strip()[:200]}"
                    )
                with open(destination, "rb") as handle:
                    image = handle.read()
                # DNA gets the bytes, not the name. The notes email is composed on the other side
                # of the airgap and embeds the image in the message, because a mail client asking
                # this host for it only works from inside — Gmail's web client fetches images
                # through a Google proxy that cannot reach the share.
                await self.client.upload_poster(
                    state.playlist_id, version_id, name, image
                )
                written[version_id] = name
            except Exception as e:
                logger.warning(
                    "Playlist %s version %s: no poster frame (%s)",
                    state.playlist_id,
                    version_id,
                    e,
                )
        if written:
            logger.info(
                "Playlist %s: %d poster frame(s) written to %s",
                state.playlist_id,
                len(written),
                archive_dir,
            )
        return written

    async def report_persistent_failure(self, playlist_id: int, reason: str) -> None:
        """Report a failure that has now repeated enough times to be a stall, not a blip.

        Most collection failures are transient by design — the whole flow is built to be retried,
        so a single bad pass is not worth telling anyone about. But the retry is silent, and a
        cause that never clears turns that silence into a recording that reports itself "still
        being collected" for the rest of the day. This is the point at which the silence becomes
        the bug: the collector has tried, and gone on failing for the same reason.

        Learned from a real one. The backend was not restarted after a deploy, so every request
        for a name 404'd; the collector retried correctly and forever, and the only visible
        symptom was a progress step that never turned green with nothing anywhere saying why.
        """
        if self._failures.get(playlist_id, 0) < FAILURES_BEFORE_REPORTING:
            return
        await self.report_blocked(playlist_id, reason)

    async def report_blocked(self, playlist_id: int, reason: str) -> None:
        """Tell DNA why this playlist is stuck, once, so the player can say so.

        Failures here are swallowed. This is an explanation of a problem, not part of the custody
        chain — losing the message must not turn a stalled collection into a raised exception
        that hides which one it was.
        """
        if self._reported.get(playlist_id) == reason:
            return
        try:
            await self.client.report_blocked(playlist_id, reason)
            self._reported[playlist_id] = reason
        except Exception as e:
            logger.warning(
                "Playlist %s: could not report why it is blocked (%s)", playlist_id, e
            )

    async def poll_once(self, playlist_id: int) -> dict[str, Any]:
        """One pass for one playlist: mirror what is new, and finish if the recording is done.

        The recording is identified BEFORE any state is loaded. The work queue can only ask a
        coarse question (has this playlist's current MEETING been archived), so the precise
        decision — is this exact recording already held — is made here, where the index has just
        named it.
        """
        index = await self.client.list_chunks(playlist_id, after=-1)
        recording_id = index.get("recording_id")
        recording_id = int(recording_id) if recording_id is not None else None

        state = self.load_state(playlist_id, recording_id)
        if state.complete and state.archived_path:
            return {
                "playlist_id": playlist_id,
                "recording_id": recording_id,
                "status": "archived",
            }

        appended, complete = await self.ingest_new_parts(state)
        if not complete:
            return {
                "playlist_id": playlist_id,
                "status": "mirroring",
                "parts": len(state.parts),
                "appended": appended,
                "bytes": state.bytes_written,
            }
        try:
            result = await self.finalize(state)
        except ArchiveDirectoryMissing as e:
            # Known from the first pass never to clear by retrying, so it is reported at once
            # rather than after a few. Re-raised afterwards: this pass still failed, and nothing
            # has been archived or deleted.
            await self.report_blocked(playlist_id, str(e))
            raise
        except CollectorError as e:
            # Everything else is transient until it demonstrably is not. Counted rather than
            # reported, so a blip stays quiet and a stall does not.
            self._failures[playlist_id] = self._failures.get(playlist_id, 0) + 1
            await self.report_persistent_failure(playlist_id, str(e))
            raise
        self._failures.pop(playlist_id, None)
        # After finalize, never inside it: the archive is recorded and the upstream copy released
        # by the time this runs, so a thumbnailer that cannot reach DNA, cannot read the cut list
        # or cannot run ffmpeg costs a picture and nothing else.
        try:
            posters = await self.write_posters(state)
        except Exception as e:
            logger.warning(
                "Playlist %s: archived, but no poster frames (%s)", playlist_id, e
            )
            posters = {}
        return {"status": "archived", "posters": len(posters), **result}


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
