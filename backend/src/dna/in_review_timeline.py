"""Which version was in review when a sentence was SPOKEN.

Vexa confirms a transcript segment several seconds after the words are said — measured at five to
seven on real meetings. Attributing that segment to whatever is in review when it ARRIVES puts
everything said in the last few seconds before a reviewer moves on into the shot they moved to.

That is not an edge case. It is what a review sounds like: someone finishes their point about a
shot and then clicks to the next one. On a controlled test where each shot's version number was
read aloud, two of three shots had their own identifier filed under the following shot.

So the mark is kept as a timeline rather than a single value, and a segment is resolved against
the moment it was spoken. `in_review` still holds the current mark — the timeline is what lets a
late arrival ask what was true when it happened.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


def parse_utc(value: Any) -> Optional[datetime]:
    """A timezone-aware UTC datetime, or None if it cannot be read as one.

    Naive input is read as UTC: both sides of the comparison are produced by this deployment, and
    guessing a local zone would silently shift every boundary by hours.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def version_in_review_at(
    history: Optional[Sequence[dict[str, Any]]],
    spoken_at: Any,
    fallback: Optional[int] = None,
) -> Optional[int]:
    """The version marked in review at ``spoken_at``.

    ``history`` is the append-only record of the mark, oldest first, each entry
    ``{"version_id": int | None, "since": iso8601}``. A ``version_id`` of None is a real entry: it
    records the mark being cleared, and segments spoken after it belong to nothing.

    Returns ``fallback`` — the CURRENT mark — when the timeline cannot answer:

      * no history at all, which is every playlist from before this was recorded;
      * an unreadable timestamp on either side.

    But NOT when the timeline answers "nothing yet". A segment spoken before the first mark was
    ever set has an answer, and the answer is that it belongs to no version — falling back there
    would file the opening minutes of a meeting under whichever shot was eventually chosen.
    """
    if not history:
        return fallback

    when = parse_utc(spoken_at)
    if when is None:
        logger.warning(
            "Unreadable segment timestamp %r — attributing to the current mark instead",
            spoken_at,
        )
        return fallback

    # Oldest first, so the last entry at or before `when` is the one in force. Sorted here rather
    # than trusted: the order matters to the answer, and an out-of-order append would otherwise
    # misfile silently.
    entries = []
    for entry in history:
        since = parse_utc(entry.get("since"))
        if since is None:
            logger.warning(
                "Skipping in-review history entry with no usable time: %r", entry
            )
            continue
        entries.append((since, entry.get("version_id")))
    if not entries:
        return fallback

    entries.sort(key=lambda e: e[0])
    if when < entries[0][0]:
        return None  # spoken before anything was marked — belongs to no version

    current: Optional[int] = None
    for since, version_id in entries:
        if since > when:
            break
        current = version_id
    return current


def append_to_history(
    history: Optional[Sequence[dict[str, Any]]],
    version_id: Optional[int],
    at: datetime,
) -> list[dict[str, Any]]:
    """The timeline with this change recorded, or unchanged if it is not a change.

    Re-marking the version already in review is not a boundary, and recording it would move the
    boundary to the re-click — putting words spoken before it on the wrong side.
    """
    entries = list(history or [])
    if entries and entries[-1].get("version_id") == version_id:
        return entries
    entries.append(
        {
            "version_id": version_id,
            "since": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    return entries
