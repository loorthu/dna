"""The airgap collector's runnable shell — discovery, HTTP, and the loop.

Everything that can be decided without the world lives in ``dna.recording_collector``, which is
unit-tested in the backend suite. This file is the part that cannot be: the DNA client, the poll
loop, and shutting down cleanly. Keeping the split sharp is what makes the interesting behaviour
(resuming, verifying, the ordering rule) provable offline.

Configuration, all via environment:

    DNA_API_URL              where DNA's API answers        (default http://localhost:8000)
    DNA_API_TOKEN            bearer token, if AUTH_PROVIDER is not "none"
    COLLECTOR_STAGING_DIR    scratch space for parts        (default /staging)
    RECORDING_NETWORK_PATH   the share ROOT nginx serves    (default /net/media/dna-recordings)
                             Recordings are filed beneath it as
                             <show>/lib.recording/pix/ref/dna/<YYYYMMDD>/<name>.mp4, which DNA
                             names — this only supplies the root.
    COLLECTOR_POLL_SECONDS   seconds between passes         (default 10)
    COLLECTOR_MAX_PLAYLISTS  work-queue depth per pass       (default 25)
    COLLECTOR_SITE           which side's recordings to collect; unset = the unrouted ones
    RECORDING_POSTER_LEAD_SECONDS
                             how far into a shot's span its thumbnail is taken from (default 2)
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Any, Optional

import httpx

sys.path.insert(0, "/app")

from dna.recording_collector import (  # noqa: E402
    ArchiveDirectoryMissing,
    CollectorError,
    RecordingCollector,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("collector")


class DnaCollectorClient:
    """DNA's recording relay over HTTP.

    Every media byte the airgapped side sees comes through here — DNA is the only thing that
    reaches Vexa, and it holds the API key so that credential never crosses over.
    """

    def __init__(
        self, base_url: str, token: Optional[str] = None, timeout: float = 120.0
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # A generous timeout: a part is a few MB over a link whose characteristics are not
        # documented anywhere, and a slow fetch that completes beats a fast one that fails.
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def list_pending(self, limit: int, site: Optional[str] = None) -> list[int]:
        # `site` asks for THIS side's work only. A DNA backend serves more than one front end,
        # and the collector beside the one that dispatched a meeting is the one that must archive
        # it — otherwise the file lands on a host that is not the one serving playback. Omitting
        # it asks for the unrouted jobs, which is the whole queue when only one collector runs.
        params: dict[str, Any] = {"limit": limit}
        if site:
            params["site"] = site
        response = await self.client.get("/recordings/pending", params=params)
        response.raise_for_status()
        return response.json().get("playlist_ids", [])

    async def list_chunks(self, playlist_id: int, after: int) -> dict[str, Any]:
        response = await self.client.get(
            f"/recordings/{playlist_id}/chunks", params={"after": after}
        )
        response.raise_for_status()
        return response.json()

    async def get_chunk(
        self, playlist_id: int, seq: int
    ) -> tuple[bytes, Optional[str]]:
        response = await self.client.get(f"/recordings/{playlist_id}/chunks/{seq}")
        response.raise_for_status()
        return response.content, response.headers.get("x-chunk-sha256")

    async def get_audio(self, playlist_id: int) -> tuple[bytes, dict[str, Any]]:
        response = await self.client.get(f"/recordings/{playlist_id}/audio")
        response.raise_for_status()
        return response.content, {
            "start_time_utc": response.headers.get("x-audio-start-time-utc") or None,
            "video_start_time_utc": response.headers.get("x-video-start-time-utc")
            or None,
        }

    async def record_archive(
        self,
        playlist_id: int,
        network_path: str,
        sha256: str,
        recording_id: Optional[int] = None,
    ) -> dict[str, Any]:
        # recording_id is the collector's claim about what it actually mirrored. DNA compares it
        # with what the playlist resolves to and refuses on a disagreement, so the two ends cannot
        # silently archive one recording under another's name.
        body: dict[str, Any] = {"network_path": network_path, "sha256": sha256}
        if recording_id is not None:
            body["recording_id"] = recording_id
        response = await self.client.post(
            f"/recordings/{playlist_id}/archived", json=body
        )
        response.raise_for_status()
        return response.json()

    async def delete_upstream(self, playlist_id: int) -> dict[str, Any]:
        response = await self.client.delete(f"/recordings/{playlist_id}")
        response.raise_for_status()
        return response.json()

    async def get_archive_path(
        self, playlist_id: int, suffix: str = ""
    ) -> dict[str, Any]:
        # WHERE this recording is filed, decided on the DNA side. The name is built from the show
        # and the playlist's name, which live in the tracking system that only DNA can reach —
        # this side supplies the mount point and nothing else.
        params = {"suffix": suffix} if suffix else {}
        response = await self.client.get(
            f"/recordings/{playlist_id}/archive-path", params=params
        )
        response.raise_for_status()
        return response.json()

    async def report_blocked(self, playlist_id: int, reason: str) -> dict[str, Any]:
        # Why this recording cannot be filed, for the player to show. Only for what a person has
        # to act on — a missing show directory — never for the transient failures every pass
        # retries anyway.
        response = await self.client.post(
            f"/recordings/{playlist_id}/blocked", json={"reason": reason}
        )
        response.raise_for_status()
        return response.json()

    async def get_cuts(self, playlist_id: int) -> dict[str, Any]:
        # Where each version was discussed, which is where the poster frames are taken from.
        # Asked for AFTER the archive is recorded, so the answer is `ready` rather than
        # `archiving` — the same endpoint the player uses, so a thumbnail cannot point at a
        # moment the player would not open.
        response = await self.client.get(f"/recordings/cuts/{playlist_id}")
        response.raise_for_status()
        return response.json()

    async def upload_poster(
        self, playlist_id: int, version_id: int, filename: str, image: bytes
    ) -> dict[str, Any]:
        # The BYTES, unlike the archive, of which DNA is told only the name. A poster is a few
        # tens of kB and the notes email — composed on DNA's side — embeds it in the message
        # rather than linking it, because a mail client asking this host for an image only works
        # from inside the network. The name travels too, so the copy on the share stays findable.
        response = await self.client.post(
            f"/recordings/{playlist_id}/posters/{version_id}",
            params={"filename": filename},
            headers={"Content-Type": "image/jpeg"},
            content=image,
        )
        response.raise_for_status()
        return response.json()


def resolve_ffmpeg() -> str:
    """The bundled static ffmpeg.

    It arrives as a Python wheel rather than an apt package on purpose: the prod host builds
    through an internal PyPI mirror but has no Debian mirror, so apt would make this image
    buildable only on an internet-connected machine and carried over. The wheel keeps both the
    build-on-prod and the transfer paths working, and the binary is a full static build.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (
        Exception
    ) as e:  # pragma: no cover - a broken install, surfaced loudly at startup
        logger.warning("Bundled ffmpeg unavailable (%s) — falling back to PATH", e)
        return "ffmpeg"


def _require_writable(path: str, setting: str) -> None:
    """Refuse to start unless the staging directory can actually be written.

    It is a mount owned by the host, and the uid this runs as is a deployment choice — so "can I
    write here" is settled outside this image and is exactly the sort of thing that is right on one
    host and wrong on the next.

    Checked at STARTUP because the alternative is discovering it during a meeting. Nothing is
    written until parts arrive, so a container with an unwritable staging directory looks perfectly
    healthy for as long as nobody records anything, and then loses the recording it existed to save.
    """
    probe = os.path.join(path, ".collector-write-test")
    try:
        with open(probe, "w") as handle:
            handle.write("")
        os.remove(probe)
    except OSError as e:
        raise SystemExit(
            f"{setting}={path} is not writable as uid {os.getuid()}:{os.getgid()} "
            f"({e.strerror}). The collector must own what it writes: set COLLECTOR_UID/"
            f"COLLECTOR_GID to an account that can write it, or fix the directory's ownership. "
            f"(An existing staging VOLUME keeps the ownership it was created with — recreate it "
            f"after changing the uid.)"
        )


def _require_reachable(path: str, setting: str) -> None:
    """Refuse to start unless the share root is there to be descended into.

    Only reachability, not writability — the root is the top of the studio's show tree and nothing
    writes to it. Archives land several directories down, in a show's own library, and WHICH show
    is not known until a meeting has been collected. So a write probe here would either fail on a
    correctly configured host or, worse, pass by leaving a file at the top of the share.

    What that costs is the startup answer to "can this host archive anything at all"; the write
    permission that used to be settled here is now discovered on the first archive of each show. It
    is discovered safely — a failed write is a CollectorError, the upstream copy is untouched and
    the next pass retries — but it is discovered later, and a new show is the moment to watch.

    An unmounted share is still caught here, which is the failure this check existed for: the
    mount silently missing looks identical to a quiet week until a meeting is lost.
    """
    if not os.path.isdir(path):
        raise SystemExit(
            f"{setting}={path} is not a directory. It is the ROOT the archives are filed under "
            f"(<show>/lib.recording/pix/ref/dna/<date>/), so it must be the real mount — an "
            f"absent one usually means the share is not mounted in this container."
        )
    if not os.access(path, os.R_OK | os.X_OK):
        raise SystemExit(
            f"{setting}={path} cannot be read as uid {os.getuid()}:{os.getgid()}. The collector "
            f"has to descend into each show's directory to file its recording: set COLLECTOR_UID/"
            f"COLLECTOR_GID to an account with access to the share."
        )


async def run_forever() -> None:
    base_url = os.environ.get("DNA_API_URL", "http://localhost:8000")
    staging = os.environ.get("COLLECTOR_STAGING_DIR", "/staging")
    archive = os.environ.get("RECORDING_NETWORK_PATH", "/net/media/dna-recordings")
    interval = float(os.environ.get("COLLECTOR_POLL_SECONDS", "10"))
    max_playlists = int(os.environ.get("COLLECTOR_MAX_PLAYLISTS", "25"))
    site = os.environ.get("COLLECTOR_SITE") or None

    os.makedirs(staging, exist_ok=True)
    _require_writable(staging, "COLLECTOR_STAGING_DIR")
    _require_reachable(archive, "RECORDING_NETWORK_PATH")

    client = DnaCollectorClient(base_url, os.environ.get("DNA_API_TOKEN"))
    collector = RecordingCollector(
        client=client,
        staging_dir=staging,
        archive_root=archive,
        ffmpeg_path=resolve_ffmpeg(),
    )

    stopping = asyncio.Event()

    def request_stop(*_: Any) -> None:
        logger.info("Shutdown requested — finishing the current pass")
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, request_stop)

    logger.info(
        "Collector up: DNA at %s, staging %s, archiving to %s, every %.0fs, site=%s",
        base_url,
        staging,
        archive,
        interval,
        site or "(unrouted)",
    )
    # Playlists that have nothing to collect (a meeting that was never recorded) stay in the work
    # queue forever, so their 404s are logged once and then only counted. Without this the log is
    # unreadable within a day and a real failure hides in it.
    quiet: set[int] = set()

    while not stopping.is_set():
        try:
            pending = await client.list_pending(max_playlists, site=site)
        except Exception as e:
            logger.warning("Could not read the work queue (%s) — retrying", e)
            pending = []

        for playlist_id in pending:
            if stopping.is_set():
                break
            try:
                result = await collector.poll_once(playlist_id)
                quiet.discard(playlist_id)
                if result["status"] == "archived":
                    logger.info("Playlist %s: %s", playlist_id, result)
                elif result.get("appended"):
                    logger.info(
                        "Playlist %s: +%d part(s), %d held, %.1f MB staged",
                        playlist_id,
                        result["appended"],
                        result["parts"],
                        result["bytes"] / 1_048_576,
                    )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    if playlist_id not in quiet:
                        logger.info(
                            "Playlist %s: no recording to collect yet — quietening",
                            playlist_id,
                        )
                        quiet.add(playlist_id)
                else:
                    logger.error("Playlist %s: %s", playlist_id, e)
            except ArchiveDirectoryMissing as e:
                # Waiting on a person, not on a retry, so it is said ONCE per playlist rather
                # than every ten seconds for however long it takes someone to read it. Loud the
                # first time: this is the message that tells them what to create.
                if playlist_id not in quiet:
                    logger.error(
                        "Playlist %s: %s Retrying quietly until it appears.", playlist_id, e
                    )
                    quiet.add(playlist_id)
            except CollectorError as e:
                # Every one of these leaves the upstream copy intact by construction, so the next
                # pass simply tries again.
                logger.error("Playlist %s: %s", playlist_id, e)
            except Exception:
                logger.exception("Playlist %s: unexpected failure", playlist_id)

        try:
            await asyncio.wait_for(stopping.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    await client.aclose()
    logger.info("Collector stopped")


if __name__ == "__main__":
    asyncio.run(run_forever())
