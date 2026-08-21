"""The airgap collector's runnable shell — discovery, HTTP, and the loop.

Everything that can be decided without the world lives in ``dna.recording_collector``, which is
unit-tested in the backend suite. This file is the part that cannot be: the DNA client, the poll
loop, and shutting down cleanly. Keeping the split sharp is what makes the interesting behaviour
(resuming, verifying, the ordering rule) provable offline.

Configuration, all via environment:

    DNA_API_URL              where DNA's API answers        (default http://localhost:8000)
    DNA_API_TOKEN            bearer token, if AUTH_PROVIDER is not "none"
    COLLECTOR_STAGING_DIR    scratch space for parts        (default /staging)
    RECORDING_NETWORK_PATH   the archive root nginx serves  (default /net/media/dna-recordings)
    COLLECTOR_POLL_SECONDS   seconds between passes         (default 10)
    COLLECTOR_MAX_PLAYLISTS  work-queue depth per pass       (default 25)
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

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 120.0):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # A generous timeout: a part is a few MB over a link whose characteristics are not
        # documented anywhere, and a slow fetch that completes beats a fast one that fails.
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def list_pending(self, limit: int) -> list[int]:
        response = await self.client.get("/recordings/pending", params={"limit": limit})
        response.raise_for_status()
        return response.json().get("playlist_ids", [])

    async def list_chunks(self, playlist_id: int, after: int) -> dict[str, Any]:
        response = await self.client.get(
            f"/recordings/{playlist_id}/chunks", params={"after": after}
        )
        response.raise_for_status()
        return response.json()

    async def get_chunk(self, playlist_id: int, seq: int) -> tuple[bytes, Optional[str]]:
        response = await self.client.get(f"/recordings/{playlist_id}/chunks/{seq}")
        response.raise_for_status()
        return response.content, response.headers.get("x-chunk-sha256")

    async def get_audio(self, playlist_id: int) -> tuple[bytes, dict[str, Any]]:
        response = await self.client.get(f"/recordings/{playlist_id}/audio")
        response.raise_for_status()
        return response.content, {
            "start_time_utc": response.headers.get("x-audio-start-time-utc") or None,
            "video_start_time_utc": response.headers.get("x-video-start-time-utc") or None,
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
    except Exception as e:  # pragma: no cover - a broken install, surfaced loudly at startup
        logger.warning("Bundled ffmpeg unavailable (%s) — falling back to PATH", e)
        return "ffmpeg"


def _require_writable(path: str, setting: str) -> None:
    """Refuse to start unless the directories can actually be written.

    Both are mounts owned by the host, and the uid this runs as is a deployment choice — so "can I
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


async def run_forever() -> None:
    base_url = os.environ.get("DNA_API_URL", "http://localhost:8000")
    staging = os.environ.get("COLLECTOR_STAGING_DIR", "/staging")
    archive = os.environ.get("RECORDING_NETWORK_PATH", "/net/media/dna-recordings")
    interval = float(os.environ.get("COLLECTOR_POLL_SECONDS", "10"))
    max_playlists = int(os.environ.get("COLLECTOR_MAX_PLAYLISTS", "25"))

    os.makedirs(staging, exist_ok=True)
    _require_writable(staging, "COLLECTOR_STAGING_DIR")
    _require_writable(archive, "RECORDING_NETWORK_PATH")

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
        "Collector up: DNA at %s, staging %s, archiving to %s, every %.0fs",
        base_url, staging, archive, interval,
    )
    # Playlists that have nothing to collect (a meeting that was never recorded) stay in the work
    # queue forever, so their 404s are logged once and then only counted. Without this the log is
    # unreadable within a day and a real failure hides in it.
    quiet: set[int] = set()

    while not stopping.is_set():
        try:
            pending = await client.list_pending(max_playlists)
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
                        playlist_id, result["appended"], result["parts"],
                        result["bytes"] / 1_048_576,
                    )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    if playlist_id not in quiet:
                        logger.info(
                            "Playlist %s: no recording to collect yet — quietening", playlist_id
                        )
                        quiet.add(playlist_id)
                else:
                    logger.error("Playlist %s: %s", playlist_id, e)
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
