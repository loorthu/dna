"""The artist-facing view of a review: what was said about each shot, and where to hear it.

Two jobs, both about keeping one rule in one place.

RESOLVING AN ADDRESS. `/review/<project>/<playlist>` is a claim about names, and names are not
unique — a show runs "Dailies" every day it screens one. `resolve_playlist` turns the claim into
either a playlist id or the list of playlists it could have meant, and never guesses between them:
picking the newest would send an artist following a month-old link to a review they were not in,
and it would look like it worked.

BUILDING THE PAGE. The coordinator app fetches a version, its notes, its segments and its cut list
as it moves between shots, because it edits each of them one shot at a time. The artist page edits
nothing and shows the whole playlist at once, so it is assembled here in one pass and sent whole —
four queries instead of four per shot.

WHOSE NOTES. Only the ones written in DNA (`origin != "prodtrack"`), from everyone who wrote one.
That is the same set the notes email carries, minus the email's filter to whoever pressed send:
the artist is not the sender, so keeping that filter would show them an empty page. The excluded
rows are the empty note ShotGrid seeds against every version when the playlist is created, which
would otherwise put a blank byline under every shot.
"""

import logging
from typing import Any, NamedTuple, Optional

from dna.auth.email import display_name
from dna.models.review import (
    ReviewCut,
    ReviewLink,
    ReviewNote,
    ReviewPlaylist,
    ReviewPlaylistRef,
    ReviewRecording,
    ReviewResolution,
    ReviewShot,
    ReviewTranscriptLine,
)
from dna.recording_cuts_service import RecordingCutsService, recording_playback_enabled
from dna.review_links import (
    playlist_path,
    project_segment,
    slugify,
    version_anchors,
)

logger = logging.getLogger(__name__)


class ReviewPlaylistNotFound(Exception):
    """No playlist answers to this address."""


def _attr(obj: Any, *keys: str) -> Optional[Any]:
    """Read an attribute from an object or a dict, trying each key in order."""
    for key in keys:
        value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        if value is not None:
            return value
    return None


def _text(obj: Any, *keys: str) -> str:
    value = _attr(obj, *keys)
    return "" if value is None else str(value)


def _project_for(prodtrack: Any, project_id: Optional[int]) -> tuple[str, str]:
    """A project's display name and its short code.

    The code has to be looked up rather than read off the version: a version carries its project
    as ShotGrid's link dict — id, name and type — and the code (`tank_name`) is not in it. It is
    one extra call per page, and it is what makes the page's own URL sayable.
    """
    if project_id is None:
        return "", ""
    try:
        project = prodtrack.get_entity("project", project_id, resolve_links=False)
    except Exception:
        logger.warning("Review page: could not load project %s", project_id)
        return "", ""
    return _text(project, "name"), _text(project, "code")


def _playlist_ref(playlist: Any) -> ReviewPlaylistRef:
    """One playlist a name-shaped address could have meant.

    Addressed by id, never by name. These refs exist to be offered when a name matched several
    playlists, and the name form is precisely the address that was ambiguous — offering it back
    would send the reader to the same list they just chose from.
    """
    playlist_id = int(_attr(playlist, "id") or 0)
    return ReviewPlaylistRef(
        playlist_id=playlist_id,
        playlist_name=_text(playlist, "code"),
        url_path=playlist_path(playlist_id, None, None),
        created_at=_stringify(_attr(playlist, "created_at")),
        version_count=_attr(playlist, "version_count"),
    )


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def resolve_playlist(
    prodtrack: Any,
    user_email: str,
    project_slug: str,
    playlist_slug: str,
) -> ReviewResolution:
    """Turn a name-shaped review address into a playlist id, or into the choice it left open.

    The project is matched against the ones the viewer can see rather than against the whole site.
    That is not a second permission check — the page itself is behind the same login — but it does
    mean a link into a show someone is not on reads as "no such review" instead of loading a page
    whose every ShotGrid call then fails one at a time.
    """
    try:
        projects = prodtrack.get_projects_for_user(user_email)
    except Exception as e:
        raise ReviewPlaylistNotFound(f"Could not list projects: {e}")

    wanted = slugify(project_slug)
    # Code first, name second. Codes are what the URLs are built from; matching the name too
    # rescues a link someone typed or edited by hand from the show's full title.
    project = next(
        (p for p in projects if slugify(_text(p, "code")) == wanted),
        None,
    ) or next(
        (p for p in projects if slugify(_text(p, "name")) == wanted),
        None,
    )
    if project is None:
        raise ReviewPlaylistNotFound(f"No project matches '{project_slug}'")

    project_id = int(_attr(project, "id") or 0)
    matches = prodtrack.find_playlists_by_name_slug(project_id, slugify(playlist_slug))

    if not matches:
        raise ReviewPlaylistNotFound(
            f"No playlist named '{playlist_slug}' in '{project_slug}'"
        )
    refs = [_playlist_ref(m) for m in matches]
    if len(refs) == 1:
        return ReviewResolution(playlist_id=refs[0].playlist_id, matches=refs)
    return ReviewResolution(playlist_id=None, matches=refs)


class _Located(NamedTuple):
    """Everything needed to name a playlist and to address it."""

    playlist_id: int
    playlist: Any
    playlist_name: str
    project_id: Optional[int]
    project_name: str
    project_code: str

    @property
    def url_path(self) -> str:
        return playlist_path(
            self.playlist_id,
            self.playlist_name,
            project_segment(self.project_code, self.project_name),
        )


def _locate(playlist_id: int, prodtrack: Any, versions: list) -> _Located:
    """Find the playlist's name and its show, for the heading and for the address.

    The project is taken from the playlist when it loads and from its first version when it does
    not, because those are two different failures: a playlist that cannot be read still has
    versions worth showing, and a page that renders without a heading is better than no page.
    """
    playlist_name = ""
    playlist: Any = None
    project_id: Optional[int] = None
    try:
        playlist = prodtrack.get_entity("playlist", playlist_id, resolve_links=False)
        playlist_name = _text(playlist, "code")
        playlist_project = _attr(playlist, "project")
        if playlist_project is not None:
            project_id = _attr(playlist_project, "id")
    except Exception:
        logger.warning("Review page: could not load playlist %s", playlist_id)

    if project_id is None and versions and versions[0].project:
        project_id = _attr(versions[0].project, "id")
    project_id = int(project_id) if project_id is not None else None
    project_name, project_code = _project_for(prodtrack, project_id)
    return _Located(
        playlist_id=playlist_id,
        playlist=playlist,
        playlist_name=playlist_name,
        project_id=project_id,
        project_name=project_name,
        project_code=project_code,
    )


def build_review_link(playlist_id: int, prodtrack: Any) -> ReviewLink:
    """Where this playlist's artist page is, and the fragment for each of its shots.

    The cheap half of `build_review_playlist`: it asks the production tracker where the playlist
    lives and what its versions are called, and touches neither the note store nor the recording.
    That is what makes it affordable behind a button in the reviewing tool, which needs the
    address and nothing that is on the page.
    """
    versions = prodtrack.get_versions_for_playlist(playlist_id)
    located = _locate(playlist_id, prodtrack, versions)
    return ReviewLink(
        playlist_id=playlist_id,
        url_path=located.url_path,
        anchors=version_anchors(versions),
    )


async def build_review_playlist(
    playlist_id: int,
    prodtrack: Any,
    storage: Any,
    transcription: Any,
) -> ReviewPlaylist:
    """Assemble one playlist's artist-facing page."""
    versions = prodtrack.get_versions_for_playlist(playlist_id)
    located = _locate(playlist_id, prodtrack, versions)
    playlist = located.playlist

    notes_by_version = await _notes_by_version(storage, playlist_id)
    transcript_by_version = await _transcript_by_version(storage, playlist_id)
    recording, cuts_by_version = await _recording(playlist_id, storage, transcription)

    anchors = version_anchors(versions)
    shots = [
        _shot(
            version,
            index=index,
            anchor=anchors.get(version.id, f"version-{version.id}"),
            notes=notes_by_version.get(version.id, []),
            transcript=transcript_by_version.get(version.id, []),
            cuts=cuts_by_version.get(version.id, []),
        )
        for index, version in enumerate(versions, 1)
    ]

    return ReviewPlaylist(
        playlist_id=playlist_id,
        playlist_name=located.playlist_name,
        project_id=located.project_id,
        project_name=located.project_name,
        project_code=located.project_code,
        url_path=located.url_path,
        screened_at=_stringify(_attr(playlist, "created_at")) if playlist else None,
        recording=recording,
        shots=shots,
    )


def _shot(
    version: Any,
    *,
    index: int,
    anchor: str,
    notes: list[ReviewNote],
    transcript: list[ReviewTranscriptLine],
    cuts: list[ReviewCut],
) -> ReviewShot:
    task_name = ""
    if version.task:
        step = _attr(version.task, "pipeline_step")
        task_name = _text(step, "name") if step else _text(version.task, "name")

    return ReviewShot(
        version_id=version.id,
        anchor=anchor,
        index=index,
        name=version.name or f"Version {version.id}",
        entity_name=_text(version.entity, "name") if version.entity else "",
        task_name=task_name,
        artist_name=_text(version.user, "name") if version.user else "",
        status=version.status or "",
        thumbnail=version.thumbnail,
        frame_path=version.frame_path or version.movie_path or "",
        created_at=_stringify(version.created_at),
        prodtrack_detail_url=version.prodtrack_detail_url,
        notes=notes,
        transcript=transcript,
        cuts=cuts,
    )


async def _notes_by_version(
    storage: Any, playlist_id: int
) -> dict[int, list[ReviewNote]]:
    drafts = await storage.get_draft_notes_for_playlist(playlist_id)
    by_version: dict[int, list[ReviewNote]] = {}
    for draft in drafts:
        if draft.origin == "prodtrack":
            continue
        content = (draft.content or "").strip()
        subject = (draft.subject or "").strip()
        if not content and not subject:
            continue
        by_version.setdefault(draft.version_id, []).append(
            ReviewNote(
                author_email=draft.user_email,
                author_name=display_name(draft.user_email),
                subject=subject,
                content=content,
                published=bool(draft.published),
                updated_at=draft.updated_at,
            )
        )
    for notes in by_version.values():
        # Oldest first, so a shot with several people's notes reads in the order they were written
        # rather than in whatever order the store handed them back.
        notes.sort(key=lambda n: (n.updated_at is None, n.updated_at))
    return by_version


async def _transcript_by_version(
    storage: Any, playlist_id: int
) -> dict[int, list[ReviewTranscriptLine]]:
    segments = await storage.get_segments_for_playlist(playlist_id)
    by_version: dict[int, list[ReviewTranscriptLine]] = {}
    for segment in segments:
        by_version.setdefault(segment.version_id, []).append(
            ReviewTranscriptLine(
                speaker=segment.speaker,
                text=segment.text,
                absolute_start_time=segment.absolute_start_time,
                start_time=segment.start_time,
            )
        )
    for lines in by_version.values():
        lines.sort(key=lambda line: line.absolute_start_time or "")
    return by_version


async def _recording(
    playlist_id: int, storage: Any, transcription: Any
) -> tuple[ReviewRecording, dict[int, list[ReviewCut]]]:
    """The recording's state and its per-shot spans, or the disabled answer.

    Failing to build the cut list must not take the page with it. Notes and transcript are the
    reason an artist opened the link; the recording is the part that depends on a collector, a
    share and a mount, and any of the three being unavailable is a normal thing here.
    """
    if not recording_playback_enabled():
        return ReviewRecording(status="disabled"), {}

    try:
        payload = await RecordingCutsService(transcription, storage).build(playlist_id)
    except Exception:
        logger.warning(
            "Review page: could not build recording cuts for playlist %s",
            playlist_id,
            exc_info=True,
        )
        return ReviewRecording(status="no_recording"), {}

    cuts_by_version = {
        entry["version_id"]: [
            ReviewCut(
                video_in_seconds=cut["video_in_seconds"],
                video_out_seconds=cut["video_out_seconds"],
            )
            for cut in entry.get("cuts", [])
        ]
        for entry in payload.get("versions", [])
    }
    recording = ReviewRecording(
        status=payload.get("status", "no_recording"),
        media_url=payload.get("media_url"),
        duration_seconds=payload.get("duration_seconds"),
    )
    return recording, cuts_by_version
