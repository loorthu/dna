"""Poster frames: the still each shot's thumbnail is cut from, and the badge drawn over it.

Three things here are worth holding still, and all three fail silently if they break — a wrong
thumbnail looks like a thumbnail:

  • the badge is a real PNG, drawn the same on every host. It is written by hand precisely so it
    does not depend on an image library or on a GPL-only ffmpeg filter being in whatever build
    the wheel bundles, and a PNG that a mail client cannot decode shows as nothing at all.
  • the frame is taken INSIDE the span, never at or past its out-point — ffmpeg answers a seek
    past the end with no file, which would lose the poster for the briefest mentions.
  • only a `ready` cut list yields frames. A recording still being made has offsets that move.
"""

import struct
import zlib

import pytest

from dna.recording_posters import (
    DEFAULT_LEAD_SECONDS,
    build_poster_command,
    first_cuts,
    poster_filename,
    poster_lead_seconds,
    poster_time_seconds,
    render_play_badge_png,
)


def decode_png(data: bytes) -> tuple[int, int, list[list[tuple[int, int, int, int]]]]:
    """A minimal reader for exactly what `render_play_badge_png` writes: 8-bit RGBA, no filter.

    Written out rather than pulled from a library because the point of the test is that the bytes
    are correct without one — a decoder that shares code with the encoder would agree with it
    about a malformed file.
    """
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks: dict[bytes, bytes] = {}
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        tag = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"{tag!r} chunk CRC"
        chunks.setdefault(tag, b"")
        chunks[tag] += body
        offset += 12 + length

    width, height, depth, colour, _, _, interlace = struct.unpack(
        ">IIBBBBB", chunks[b"IHDR"]
    )
    assert (depth, colour, interlace) == (8, 6, 0)
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = width * 4
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        assert raw[start] == 0, "scanlines are written unfiltered"
        line = raw[start + 1 : start + 1 + stride]
        rows.append(
            [tuple(line[x * 4 : x * 4 + 4]) for x in range(width)]  # type: ignore[misc]
        )
    return width, height, rows


# ── the badge ───────────────────────────────────────────────────────────────────────────────────


def test_the_badge_is_a_png_of_the_size_asked_for():
    width, height, _ = decode_png(render_play_badge_png(40))
    assert (width, height) == (40, 40)


def test_the_badge_is_a_white_triangle_on_a_translucent_disc():
    size = 64
    _, _, rows = decode_png(render_play_badge_png(size))

    centre = rows[size // 2][size // 2]
    assert centre == (
        255,
        255,
        255,
        255,
    ), "the triangle covers the middle, opaque white"

    # Just inside the rim on the left, where the triangle does not reach: the dark disc.
    rim = rows[size // 2][2]
    assert rim[3] > 0 and rim[0] < 60, "the disc is dark and translucent"

    for corner in (rows[0][0], rows[0][-1], rows[-1][0], rows[-1][-1]):
        assert corner[3] == 0, "outside the disc is fully transparent"


def test_the_badge_edge_is_antialiased():
    """A hard edge at this size reads as a rendering fault on top of a photographic frame."""
    size = 64
    _, _, rows = decode_png(render_play_badge_png(size))
    partial = [px for row in rows for px in row if 0 < px[3] < 255]
    assert (
        len(partial) > size
    ), "the rim should be a band of partial coverage, not a step"


# ── where in the span the frame comes from ──────────────────────────────────────────────────────


def test_a_long_span_is_sampled_at_the_lead():
    assert poster_time_seconds(100.0, 160.0, 2.0) == 102.0


def test_a_short_span_is_sampled_at_its_middle():
    """Never at or past the out-point: ffmpeg answers a seek past the end with no file at all."""
    assert poster_time_seconds(100.0, 101.0, 2.0) == 100.5


@pytest.mark.parametrize(
    "video_in,video_out", [(0.0, 0.0), (10.0, 10.0), (10.0, 9.0), (0.0, 0.4)]
)
def test_the_sample_point_never_leaves_the_span(video_in, video_out):
    at = poster_time_seconds(video_in, video_out, DEFAULT_LEAD_SECONDS)
    assert video_in <= at <= max(video_in, video_out)


def test_a_nonsense_lead_setting_falls_back_rather_than_raising(monkeypatch):
    monkeypatch.setenv("RECORDING_POSTER_LEAD_SECONDS", "soon")
    assert poster_lead_seconds() == DEFAULT_LEAD_SECONDS


def test_the_lead_is_tunable(monkeypatch):
    monkeypatch.setenv("RECORDING_POSTER_LEAD_SECONDS", "5")
    assert poster_lead_seconds() == 5.0


# ── naming ──────────────────────────────────────────────────────────────────────────────────────


def test_the_poster_is_named_after_the_archive_it_came_from():
    """So it inherits the recording scoping — a second meeting writes different posters."""
    assert (
        poster_filename("/net/media/dna-recordings/playlist-42-rec7001.mp4", 900)
        == "playlist-42-rec7001-v900.jpg"
    )
    assert (
        poster_filename("/net/media/dna-recordings/playlist-42-rec7002.mp4", 900)
        == "playlist-42-rec7002-v900.jpg"
    )


# ── reading the cut list ────────────────────────────────────────────────────────────────────────


READY = {
    "status": "ready",
    "versions": [
        {
            "version_id": 900,
            "cuts": [
                {"video_in_seconds": 300.0, "video_out_seconds": 340.0},
                {"video_in_seconds": 40.0, "video_out_seconds": 90.0},
            ],
        },
        {"version_id": 901, "cuts": []},
    ],
}


def test_each_version_gives_up_its_opening_span():
    """The first time the shot came up is what a reader following a thumbnail is looking for."""
    assert first_cuts(READY) == [(900, 40.0, 90.0)]


@pytest.mark.parametrize(
    "status", ["pending", "archiving", "no_recording", "no_segments", "no_meeting"]
)
def test_nothing_is_taken_from_a_cut_list_that_is_not_ready(status):
    assert first_cuts({**READY, "status": status}) == []


# ── the ffmpeg call ─────────────────────────────────────────────────────────────────────────────


def test_the_grab_seeks_before_the_input_and_takes_one_frame():
    command = build_poster_command(
        "ffmpeg", "/archive/rec.mp4", "/staging/badge.png", "/archive/out.jpg", 41.5
    )
    assert command[command.index("-ss") + 1] == "41.500"
    # Before -i, so ffmpeg seeks the file rather than decoding an hour of meeting up to it.
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-i") + 1] == "/archive/rec.mp4"
    assert command[-1] == "/archive/out.jpg"
    assert "-frames:v" in command and command[command.index("-frames:v") + 1] == "1"


def test_the_badge_is_composited_over_the_middle_of_a_filled_thumbnail():
    command = build_poster_command(
        "ffmpeg", "/archive/rec.mp4", "/staging/badge.png", "/archive/out.jpg", 1.0
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "force_original_aspect_ratio=increase" in graph, "fill, never letterbox"
    assert "overlay=(W-w)/2:(H-h)/2" in graph
