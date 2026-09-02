"""What an archived meeting recording is CALLED, and the dated directory it sits in.

    <YYYYMMDD>/<playlist code>_<start>_Recording.mp4

WHERE that pair goes is not decided here, and deliberately so. The directory a studio files
recordings in is a fact about that studio's filesystem — at SPI it threads through a show's
reference library, elsewhere it will be something else entirely — and a naming rule that hard-codes
one site's folders is a naming rule nobody else can adopt. So the deployment configures the
directory (``RECORDING_ARCHIVE_DIR`` on the collector, which is the only process that can see the
share), and this module supplies the part that is the same everywhere: a name derived from the
playlist and the moment its meeting started, under a directory named for the day.

WHY THE NAME IS DERIVED HERE AND NOT BY THE COLLECTOR: the collector is on the airgapped side and
knows only playlist ids and bytes. The playlist's name, and the show it belongs to, live in the
tracking system that only DNA can reach. So DNA says what to call the file and which show it
belongs to; the deployment says where that goes; the collector puts the two together.

THE DATE DIRECTORY IS THE MEETING'S, NOT TODAY'S. Two reasons, and the second is the load-bearing
one: it agrees with the timestamp in the filename beside it, and it is STABLE. The collector
re-derives the destination when it resumes, and a meeting that runs past midnight — or a
collector restarted the next morning — would otherwise compute a different directory than the one
it already wrote to, defeating both the resume logic and the refuse-to-overwrite guard.

Timestamps are rendered in local time, not UTC: the name is read by people who were in the
meeting, and 13_52_PDT is the time it happened to them.
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# The clock the directory date and the filename timestamp are rendered in.
DEFAULT_TIMEZONE = "America/Los_Angeles"

# What survives into a filename. Everything else becomes "_": the components come from ShotGrid,
# where a playlist may be called anything at all, and a name that reaches a filesystem, an nginx
# location and a URL is not the place to find out what "anything" included.
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

SUFFIX = "_Recording"


def archive_timezone():
    """The studio's clock, or UTC if this host cannot name it.

    Falling back rather than raising is deliberate: a missing zone database would otherwise stop
    every recording being archived, and a file named in UTC is a cosmetic problem next to a
    meeting that stays in Vexa because its name could not be rendered.
    """
    name = os.getenv("RECORDING_ARCHIVE_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception as e:
        logger.warning("Cannot use timezone %s (%s) — naming archives in UTC", name, e)
        return timezone.utc


def sanitize(component: str) -> str:
    """One path component, reduced to what is safe in a filename and a URL.

    Runs of replaced characters collapse to a single "_" so a code with a space either side of a
    slash does not become a stretch of underscores, and leading/trailing separators are dropped
    so a component can never start a hidden file or end in a dot.
    """
    cleaned = _SAFE.sub("_", component or "").strip("._-")
    return re.sub(r"_{2,}", "_", cleaned)


def parse_start_time(start_time_utc: str) -> datetime:
    """Vexa's start clock as an aware datetime. Naive input is read as UTC, which is what it is."""
    text = (start_time_utc or "").strip()
    if not text:
        raise ValueError("no recording start time")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_start(local_start: datetime) -> str:
    """``2026_09_01_13_52_PDT`` — the minute the meeting started, where it started.

    Seconds are left out: the name is read by people, and two meetings on one playlist within the
    same minute is not a thing that happens. If it ever did, the collector disambiguates by
    recording id rather than by overwriting.
    """
    zone = sanitize(local_start.strftime("%Z")) or "UTC"
    return f"{local_start.strftime('%Y_%m_%d_%H_%M')}_{zone}"


def archive_filename(
    playlist_code: str, local_start: datetime, suffix: str = ""
) -> str:
    """The file's name.

    The suffix is sanitized like every other component. It arrives over HTTP as a query
    parameter, and this string is on its way to a filesystem and a URL — an unsanitized one
    could carry the path straight out of the dated directory.
    """
    name = sanitize(playlist_code) or "Playlist"
    tail = sanitize(suffix)
    return f"{name}_{format_start(local_start)}{SUFFIX}{'_' + tail if tail else ''}.mp4"


def archive_name(
    show: str,
    playlist_code: str,
    start_time_utc: str,
    tz=None,
    suffix: str = "",
) -> dict[str, str]:
    """What to call this recording, and which day's directory it belongs in.

    Three strings and no path: ``show`` for the deployment to place, ``date_dir`` and ``filename``
    to join beneath wherever that turns out to be. The show is sanitized here rather than by the
    caller because it is the one component that comes from outside and ends up in a directory
    name — a project called "Foo / Bar" must not become two levels of anything.
    """
    show_dir = sanitize(show)
    if not show_dir:
        raise ValueError("no show for this playlist — cannot place its recording")
    local = parse_start_time(start_time_utc).astimezone(tz or archive_timezone())
    return {
        "show": show_dir,
        "date_dir": local.strftime("%Y%m%d"),
        "filename": archive_filename(playlist_code, local, suffix),
    }


def is_safe_relative_path(path: str) -> bool:
    """A path that may be stored and later handed to nginx as a URL.

    Rejects anything absolute or containing a traversal, so a compromised or simply buggy
    collector cannot make DNA advertise a URL that resolves outside the share.
    """
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)
