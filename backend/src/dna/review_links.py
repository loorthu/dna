"""Addresses for the artist-facing review page.

One playlist has one URL and one anchor per shot inside it. Both are built here, by the one
function each, because two things need them and they must agree exactly: the email writes the
links, and the page resolves them. A slug computed one way in the mailer and another way in the
resolver produces links that look right and land nowhere, and nothing in either place would
report it.

The playlist address is its name rather than its id because that is what the person clicking it
recognises — "abc/dailies-comp-2026-08-30" says which review it was, "4471" does not. Names are
not unique, though (a show reuses "Dailies" every day it runs one), so the name form is a claim
that has to be checked at resolve time, and `playlist_path` falls back to the id form whenever
there is no name to slug at all.
"""

import os
import re
import unicodedata
from typing import Any, Iterable, Optional
from urllib.parse import quote

# The front-end route these paths are for. Not the API prefix: the browser asks nginx for
# /review/..., which falls through to index.html, and the SPA resolves it against /api/review/...
REVIEW_PREFIX = "/review"

# The path a playlist with no usable name gets, and the escape hatch a duplicated name resolves
# to. Kept distinct from a project code by the literal segment, which is why "id" is reserved and
# a project whose code slugs to "id" is not addressable by name (it is still addressable by id).
REVIEW_ID_SEGMENT = "id"


def slugify(value: Optional[str], *, keep: str = "") -> str:
    """Lowercase, ASCII, hyphen-joined form of a name.

    `keep` names extra characters to pass through rather than fold into hyphens. Version names
    are the reason: `abc_0100_comp_v012` is already an address, and turning its underscores into
    hyphens makes an anchor nobody recognises as the shot it points at.
    """
    if not value:
        return ""
    # NFKD then ASCII-drop: accented characters become their base letter rather than vanishing,
    # so "Prévis" slugs to "previs" and not "prvis".
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    allowed = re.escape(keep)
    collapsed = re.sub(rf"[^a-z0-9{allowed}]+", "-", ascii_only)
    return collapsed.strip("-")


def project_segment(
    project_code: Optional[str], project_name: Optional[str] = None
) -> str:
    """The URL segment naming a show: its code, or failing that its name.

    The fallback is not cosmetic. A site whose ShotGrid projects carry no `tank_name` — which the
    one this was built against does not — reports every project's code as empty, and without the
    fallback every review link on that site collapses to the id form. Its projects are named "ap1"
    and "bogz", so the name is exactly the short handle the code was wanted for.

    The resolver matches code first and name second for the same reason, so both segments this can
    produce resolve back to the project they came from.
    """
    return slugify(project_code) or slugify(project_name)


def playlist_path(
    playlist_id: int,
    playlist_name: Optional[str],
    project: Optional[str],
) -> str:
    """The path for one playlist's review page.

    `project` is the segment naming the show — see `project_segment`, which is what callers use to
    choose it. The name form needs both halves: a playlist slug with no project is ambiguous
    across shows, which is the whole reason the show is in the path. Missing either, this returns
    the id form, which always resolves.
    """
    slug = slugify(playlist_name)
    code = slugify(project)
    if not slug or not code or code == REVIEW_ID_SEGMENT:
        return f"{REVIEW_PREFIX}/{REVIEW_ID_SEGMENT}/{playlist_id}"
    return f"{REVIEW_PREFIX}/{quote(code)}/{quote(slug)}"


def version_anchors(versions: Iterable[Any]) -> dict[int, str]:
    """An anchor per version, unique within the playlist.

    Keyed by version id and computed over the whole list at once, because uniqueness is a property
    of the list: two versions in one playlist can carry the same name, and an anchor that appears
    twice sends every link to the first one. The tiebreak appends the id, so the first occurrence
    keeps the readable form and only the collision pays for itself.
    """
    anchors: dict[int, str] = {}
    seen: set[str] = set()
    for version in versions:
        version_id = _attr_int(version, "id")
        if version_id is None:
            continue
        base = slugify(_attr_str(version, "name"), keep="_.") or f"version-{version_id}"
        anchor = base if base not in seen else f"{base}-{version_id}"
        seen.add(anchor)
        anchors[version_id] = anchor
    return anchors


def app_base_url() -> str:
    """Where the review page is served from, for links that leave the browser.

    Only the email needs this: in the app a path is enough, but a mail client has no origin to
    resolve one against. Unset means the deployment has not been told its own address, and the
    mailer omits the links rather than writing ones that cannot be followed.
    """
    return os.getenv("DNA_APP_BASE_URL", "").strip().rstrip("/")


def review_url(
    playlist_id: int,
    playlist_name: Optional[str],
    project_code: Optional[str],
    project_name: Optional[str] = None,
) -> Optional[str]:
    """The absolute review URL, or None when this deployment has no configured address."""
    base = app_base_url()
    if not base:
        return None
    segment = project_segment(project_code, project_name)
    return f"{base}{playlist_path(playlist_id, playlist_name, segment)}"


def _attr_str(obj: Any, key: str) -> Optional[str]:
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return None if value is None else str(value)


def _attr_int(obj: Any, key: str) -> Optional[int]:
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
