"""Poster frames — one still per shot, taken from the part of the meeting that discussed it.

WHY THESE EXIST: the notes email lists shots as text, and nothing in it says that a clip of the
discussion is one click away. A frame of the shot with a play button on it says so before a word
is read, and it says it in the one place the artist is already looking.

WHERE THIS RUNS: in the collector, beside the archive it just took custody of — which is the only
side of the airgap the media is ever on. The poster is written next to the archive (nginx serves
it at /recordings/ like the recording itself) AND pushed to DNA, because the email is composed on
the other side and a mail client fetching an image from an internal host does not work for
everyone: Gmail's web client proxies images through Google, which cannot reach the share. The
bytes DNA holds are embedded in the message instead, so the thumbnail renders everywhere.

NOTHING HERE MAY ENDANGER THE RECORDING. Posters are decoration derived from a file that already
exists; the custody chain in `recording_collector` runs to completion first, and every failure in
this module is logged and dropped. A missing thumbnail costs a visual cue. Anything that reordered
the archive-then-release rule to make one would cost the meeting.

Stdlib only, like `recording_collector` — the collector image copies both modules out of the
backend package rather than vendoring a second copy, and it has no room for the application's
imports. The play badge is therefore drawn here rather than by an image library or by ffmpeg's
`geq` (which is a GPL-only filter, so its presence is a property of whichever ffmpeg build the
wheel happens to bundle): a PNG is a handful of CRC'd chunks around a zlib stream, and drawing it
ourselves means the badge is identical on every host and covered by an offline test.
"""

import logging
import os
import struct
import zlib
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 2× the 160×90 the email displays, so the thumbnail is not soft on a high-DPI screen. Small
# enough at JPEG q3 (~30 kB) that a thirty-shot email carries them all without complaint.
POSTER_WIDTH = 320
POSTER_HEIGHT = 180

# The badge, as a fraction of the poster's height, and the darkness of its disc. Sized by eye
# against a 320×180 frame: large enough to read as "play" in a mail client's list view, small
# enough that it does not hide the shot it is advertising.
BADGE_SIZE = 80
DISC_ALPHA = 150

# How far into a shot's span the still is taken from. The span opens at the instant the operator
# marked the shot, which is routinely a beat before the new frame is actually up on the shared
# screen — so the literal first frame often shows the shot BEFORE this one, which is worse than
# no thumbnail. Clamped to the middle of short spans below, so a two-second span is not asked for
# a frame past its end.
DEFAULT_LEAD_SECONDS = 2.0


def poster_lead_seconds() -> float:
    """`RECORDING_POSTER_LEAD_SECONDS`, or the default. Tunable because how long a screen share
    takes to catch up with the operator is a property of the room, not of this code."""
    try:
        return float(os.getenv("RECORDING_POSTER_LEAD_SECONDS", DEFAULT_LEAD_SECONDS))
    except ValueError:
        logger.warning(
            "RECORDING_POSTER_LEAD_SECONDS is not a number — using %.1fs",
            DEFAULT_LEAD_SECONDS,
        )
        return DEFAULT_LEAD_SECONDS


def poster_time_seconds(
    video_in_seconds: float,
    video_out_seconds: float,
    lead_seconds: float = DEFAULT_LEAD_SECONDS,
) -> float:
    """Where in the recording to take this shot's still.

    The lead is clamped to half the span so a short cut cannot be asked for a frame at or beyond
    its out-point — ffmpeg answers that with no file at all, which would lose the poster for
    exactly the shots that got the briefest mention.
    """
    span = max(0.0, video_out_seconds - video_in_seconds)
    return video_in_seconds + min(max(lead_seconds, 0.0), span / 2)


def poster_filename(archive_name: str, version_id: int) -> str:
    """The poster's name on the share: the archive's, with the version appended.

    Derived from the archive rather than allocated, so it inherits the recording scoping the
    archive name already carries — a playlist's second meeting writes different posters instead
    of silently replacing the first meeting's.
    """
    stem = os.path.basename(archive_name).rsplit(".", 1)[0]
    return f"{stem}-v{version_id}.jpg"


# ── the play badge ──────────────────────────────────────────────────────────────────────────────


def _png(width: int, height: int, rgba: bytes) -> bytes:
    """The smallest correct PNG: one IHDR, one IDAT of unfiltered scanlines, one IEND."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(
            0
        )  # filter type 0 (None) — the image is tiny; filtering buys nothing
        raw += rgba[y * stride : (y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        # 8 bits per channel, colour type 6 (truecolour with alpha), no interlace
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def render_play_badge_png(size: int = BADGE_SIZE) -> bytes:
    """A white play triangle on a translucent black disc, as RGBA PNG bytes.

    Coverage is supersampled 4×4 per pixel rather than tested at the pixel centre: a hard test
    gives a circle with visibly stepped edges at this size, and the badge sits on a photographic
    frame where that reads as a rendering fault. The triangle is tested only where the disc
    already covers, so it cannot spill past the rim however it is proportioned.
    """
    samples_per_axis = 4
    step = 1.0 / samples_per_axis
    offset = step / 2
    total = samples_per_axis * samples_per_axis

    centre = size / 2.0
    radius = size * 0.48
    # Nudged right of centre: a triangle centred on its bounding box looks left-heavy, because
    # the eye centres it on its area rather than its extent.
    x_left, x_right = size * 0.40, size * 0.68
    half_height = size * 0.17

    pixels = bytearray(size * size * 4)
    for py in range(size):
        for px in range(size):
            disc = triangle = 0
            for sy in range(samples_per_axis):
                y = py + sy * step + offset
                for sx in range(samples_per_axis):
                    x = px + sx * step + offset
                    if (x - centre) ** 2 + (y - centre) ** 2 > radius * radius:
                        continue
                    disc += 1
                    if x_left <= x <= x_right and abs(y - centre) <= half_height * (
                        x_right - x
                    ) / (x_right - x_left):
                        triangle += 1

            if not disc:
                continue
            # Two disjoint coverages — white triangle, and the disc around it — so the alphas
            # add rather than composite. The colour is then the white share of that total,
            # which is what an un-premultiplied PNG wants.
            white = triangle / total
            dark = (disc - triangle) / total * (DISC_ALPHA / 255)
            alpha = white + dark
            level = round(255 * white / alpha) if alpha else 0
            i = (py * size + px) * 4
            pixels[i] = pixels[i + 1] = pixels[i + 2] = level
            pixels[i + 3] = round(255 * alpha)

    return _png(size, size, bytes(pixels))


# ── the one ffmpeg invocation this module makes ─────────────────────────────────────────────────


def build_poster_command(
    ffmpeg: str,
    source: str,
    badge_path: str,
    out_path: str,
    at_seconds: float,
    width: int = POSTER_WIDTH,
    height: int = POSTER_HEIGHT,
) -> list[str]:
    """Grab one frame, letterbox-free, with the badge composited over its centre.

    ``-ss`` BEFORE ``-i`` so ffmpeg seeks the input rather than decoding up to the timestamp: an
    hour-long meeting would otherwise take minutes per shot, and the archive is a +faststart MP4
    whose index makes the seek immediate.

    ``force_original_aspect_ratio=increase`` then ``crop`` fills the 16:9 thumbnail rather than
    padding it. A meeting recording is already 16:9, so this is a no-op on the expected input and
    a sensible answer on anything else.
    """
    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[bg];"
        f"[bg][1:v]overlay=(W-w)/2:(H-h)/2:format=auto[out]"
    )
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        source,
        "-i",
        badge_path,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-f",
        "image2",
        out_path,
    ]


# ── reading the cut list ────────────────────────────────────────────────────────────────────────


def first_cuts(cuts_payload: dict[str, Any]) -> list[tuple[int, float, float]]:
    """The opening span of each version that has one, as ``(version_id, in, out)``.

    The FIRST span, not the longest or the last: it is the one the reader is looking for when
    they follow a thumbnail — where this shot came up — and it is also the span least likely to
    move, since a version's earliest in-review mark is settled long before the meeting ends.

    Anything but a ``ready`` cut list yields nothing. The other statuses mean the recording is
    still being made, still being archived, or has no transcript against these versions; none of
    them is a frame anyone can grab, and guessing an offset into a file that is still growing
    would produce a still of the wrong moment rather than no still.
    """
    if cuts_payload.get("status") != "ready":
        return []
    found: list[tuple[int, float, float]] = []
    for entry in cuts_payload.get("versions", []):
        version_id = _int(entry.get("version_id"))
        cuts = entry.get("cuts") or []
        if version_id is None or not cuts:
            continue
        opening = min(cuts, key=lambda c: float(c.get("video_in_seconds") or 0.0))
        found.append(
            (
                version_id,
                float(opening.get("video_in_seconds") or 0.0),
                float(opening.get("video_out_seconds") or 0.0),
            )
        )
    return found


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
