"""Where an archived recording is filed, and what it is called.

Worth testing on its own because the name is the ONLY way anyone finds the file afterwards. The
collector writes it once, blind, on the far side of an airgap, and then the upstream copy is
deleted — so a name that is wrong is not a cosmetic problem, it is a recording nobody can locate.
"""

import os
from datetime import timezone

import pytest

from dna.recording_archive_path import (
    archive_relative_path,
    format_start,
    is_safe_relative_path,
    parse_start_time,
    sanitize,
)

# 13:52 PDT on 1 September — the example the layout was specified from.
START = "2026-09-01T20:52:03Z"
EXPECTED = (
    "nite/lib.recording/pix/ref/dna/20260901/"
    "NITE_Director_Review_2026_09_01_13_52_PDT_Recording.mp4"
)


def test_the_path_is_the_show_the_library_the_meetings_date_and_its_name():
    assert archive_relative_path("nite", "NITE_Director_Review", START) == EXPECTED


def test_the_timestamp_is_studio_local_not_utc():
    """20:52 UTC is 13:52 PDT. The name is read by the people who were in the meeting."""
    path = archive_relative_path("nite", "Review", START)
    assert "13_52_PDT" in path and "20_52" not in path


def test_the_date_directory_is_the_meetings_not_the_archivers():
    """A meeting late on the 1st is filed under the 1st, whenever it happens to be archived.

    The collector re-derives this when it resumes; a directory that moved with the calendar
    would send a restarted collection somewhere the earlier pass had not written.
    """
    late = archive_relative_path("nite", "Review", "2026-09-02T05:30:00Z")
    assert "/20260901/" in late, "22:30 PDT on the 1st is still the 1st"


def test_a_winter_meeting_says_pst():
    assert "PST" in archive_relative_path("nite", "Review", "2026-01-15T21:00:00Z")


def test_a_naive_start_time_is_read_as_utc():
    assert archive_relative_path("nite", "Review", "2026-09-01T20:52:03") == (
        archive_relative_path("nite", "Review", START)
    )


def test_an_offset_start_time_is_honoured():
    assert archive_relative_path(
        "nite", "Review", "2026-09-01T16:52:03-04:00"
    ) == archive_relative_path("nite", "Review", START)


@pytest.mark.parametrize(
    "code, expected",
    [
        ("Director Review", "Director_Review"),
        ("seq/010 review", "seq_010_review"),
        ("../../etc/passwd", "etc_passwd"),
        ("  spaced  ", "spaced"),
        (
            "Dailies — Ünïcodé",
            "Dailies_n_cod",
        ),  # non-ASCII drops out; SPI names are ASCII
        ("a  ///  b", "a_b"),
    ],
)
def test_a_playlist_name_is_reduced_to_what_is_safe_in_a_path(code, expected):
    """ShotGrid will accept any name at all; a filesystem, an nginx location and a URL will not."""
    assert sanitize(code) == expected


def test_a_name_that_sanitizes_away_still_produces_a_file():
    """Better a recording called Playlist_<when> than a recording that cannot be archived."""
    path = archive_relative_path("nite", "///", START)
    assert path.endswith("Playlist_2026_09_01_13_52_PDT_Recording.mp4")


def test_a_playlist_with_no_show_cannot_be_filed():
    with pytest.raises(ValueError):
        archive_relative_path("", "Review", START)


def test_a_recording_with_no_start_time_cannot_be_named():
    with pytest.raises(ValueError):
        parse_start_time("")


def test_the_suffix_distinguishes_two_meetings_that_started_in_the_same_minute():
    plain = archive_relative_path("nite", "Review", START)
    scoped = archive_relative_path("nite", "Review", START, suffix="_rec2002")
    assert scoped != plain
    assert os.path.dirname(scoped) == os.path.dirname(plain)
    assert scoped.endswith("_Recording_rec2002.mp4")


@pytest.mark.parametrize("suffix", ["/../../etc/passwd", "; rm -rf /", "../x"])
def test_a_hostile_suffix_cannot_climb_out_of_the_dated_directory(suffix):
    """It reaches the endpoint as a query parameter, so it is whatever the caller sent."""
    path = archive_relative_path("nite", "Review", START, suffix=suffix)
    assert is_safe_relative_path(path)
    assert os.path.dirname(path) == os.path.dirname(
        archive_relative_path("nite", "Review", START)
    ), "still in the dated directory it was meant for"
    assert path.endswith(".mp4")


def test_the_subpath_can_be_pointed_elsewhere_for_a_share_that_is_not_a_show_tree(
    monkeypatch,
):
    monkeypatch.setenv("RECORDING_ARCHIVE_SUBPATH", "recordings")
    assert archive_relative_path("nite", "Review", START).startswith("nite/recordings/")


def test_an_unusable_timezone_names_the_file_in_utc_rather_than_failing(monkeypatch):
    """A zone database this host lacks must not stop a meeting being archived."""
    monkeypatch.setenv("RECORDING_ARCHIVE_TIMEZONE", "Mars/Olympus_Mons")
    assert "20_52_UTC" in archive_relative_path("nite", "Review", START)


def test_format_start_leaves_out_seconds():
    moment = parse_start_time(START).astimezone(timezone.utc)
    assert format_start(moment) == "2026_09_01_20_52_UTC"


@pytest.mark.parametrize(
    "path",
    [
        "/shots/nite/x.mp4",
        "../nite/x.mp4",
        "nite/../../etc/passwd",
        "nite//x.mp4",
        "nite/./x.mp4",
        "",
    ],
)
def test_a_path_that_could_escape_the_share_root_is_not_safe_to_store(path):
    """The stored value becomes a URL. One that resolves outside the share must never get there."""
    assert not is_safe_relative_path(path)


def test_the_real_shape_is_safe_to_store():
    assert is_safe_relative_path(EXPECTED)
