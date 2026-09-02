"""FastAPI application entry point."""

import logging
import os
import shutil
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Optional, cast

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dna.auth.email import emails_match
from dna.auth_providers.auth_provider_base import AuthProviderBase, get_auth_provider
from dna.cors_settings import get_cors_middleware_kwargs
from dna.events import EventType, get_event_publisher
from dna.llm_providers.llm_provider_base import LLMProviderBase, get_llm_provider
from dna.models import (
    AddVersionOutcome,
    AddVersionsToPlaylistRequest,
    AddVersionsToPlaylistResponse,
    Asset,
    BotSession,
    BotStatus,
    CreateNoteRequest,
    DispatchBotRequest,
    DraftNote,
    DraftNoteUpdate,
    EmailNotesRequest,
    FindRequest,
    GenerateNoteRequest,
    GenerateNoteResponse,
    Note,
    NoteQCCheck,
    NoteQCCheckCreate,
    NoteQCCheckUpdate,
    Platform,
    Playlist,
    PlaylistMetadata,
    PlaylistMetadataUpdate,
    Project,
    PublishedTranscriptUpdate,
    PublishNotesRequest,
    PublishNotesResponse,
    PublishTranscriptRequest,
    PublishTranscriptResponse,
    RecordingArchiveRequest,
    RecordingBlockedRequest,
    ReviewLink,
    ReviewPlaylist,
    ReviewResolution,
    RunQCChecksRequest,
    RunQCChecksResponse,
    SearchRequest,
    SearchResult,
    Shot,
    StatusOption,
    StoredSegment,
    Task,
    Transcript,
    User,
    UserSettings,
    UserSettingsResponse,
    UserSettingsUpdate,
    Version,
)
from dna.models.entity import ENTITY_MODELS, EntityBase
from dna.note_prompt_config import get_default_note_prompt
from dna.prodtrack_providers.prodtrack_provider_base import (
    ProdtrackProviderBase,
    get_prodtrack_provider,
)
from dna.qc.qc_runner import run_qc_checks_for_draft
from dna.recording_cuts_service import RecordingCutsService, recording_playback_enabled
from dna.recording_media import (
    ArchiveDestinationService,
    ArchiveDestinationUnknown,
    ArchiveNotConfirmed,
    ArchiveRecordingMismatch,
    RecordingMediaService,
    RecordingNotFound,
)
from dna.review_links import review_url
from dna.review_page import (
    ReviewPlaylistNotFound,
    build_review_link,
    build_review_playlist,
    resolve_playlist,
)
from dna.site_routing import site_for_client
from dna.storage_providers.storage_provider_base import (
    StorageProviderBase,
    get_storage_provider,
)
from dna.transcription_providers.transcription_provider_base import (
    TranscriptionProviderBase,
    TranscriptionUpstreamError,
    get_transcription_provider,
)
from dna.transcription_service import TranscriptionService, get_transcription_service

# API metadata for Swagger documentation
API_TITLE = "DNA Backend"
API_DESCRIPTION = """
## DNA Backend API

Backend API for the DNA (Dailies Notes Assistant) application.

### Features
- 🎬 Production tracking integration (ShotGrid)
- 🎤 Transcription services
- 🤖 LLM-powered note generation
- 📋 Playlist and version management

### Documentation
- **Swagger UI**: Available at `/docs`
- **ReDoc**: Available at `/redoc`
- **OpenAPI JSON**: Available at `/openapi.json`
"""

API_VERSION = "0.1.0"

# Define API tags for organizing endpoints
tags_metadata = [
    {
        "name": "Health",
        "description": "Health check and status endpoints",
    },
    {
        "name": "Entities",
        "description": "Operations for managing production entities",
    },
    {
        "name": "Playlists",
        "description": "Operations for managing playlists",
    },
    {
        "name": "Versions",
        "description": "Operations for managing versions",
    },
    {
        "name": "Shots",
        "description": "Operations for managing shots",
    },
    {
        "name": "Assets",
        "description": "Operations for managing assets",
    },
    {
        "name": "Tasks",
        "description": "Operations for managing tasks",
    },
    {
        "name": "Notes",
        "description": "Operations for managing notes",
    },
    {
        "name": "Projects",
        "description": "Operations for managing projects",
    },
    {
        "name": "Users",
        "description": "Operations for managing users",
    },
    {
        "name": "Transcription",
        "description": "Audio transcription services",
    },
    {
        "name": "LLM",
        "description": "LLM-powered note generation",
    },
    {
        "name": "Draft Notes",
        "description": "Operations for managing draft notes",
    },
    {
        "name": "Playlist Metadata",
        "description": "Operations for managing playlist metadata (in-review version and meeting ID)",
    },
    {
        "name": "User Settings",
        "description": "Operations for managing user settings and preferences",
    },
    {
        "name": "Note QC",
        "description": "User-defined LLM quality checks for draft notes at publish time",
    },
]

DISABLE_DOCS = os.getenv("DISABLE_DOCS", "false").lower() == "true"

# Nothing configured logging, so the root logger sat at its WARNING default and every
# `logger.info(...)` in the dna package was discarded before reaching the container log. The lines
# describing what the service is DOING — which meeting it subscribed to, which recording it linked,
# which playlist it cleaned up after — were written and thrown away, while only complaints
# survived. Diagnosing anything therefore meant reasoning from silence, and silence had two
# indistinguishable causes: the code did not run, or it ran and could not say so.
#
# `force=True` because uvicorn installs its own handlers first; without it this call is a no-op and
# the defaults stand. LOG_LEVEL matches the knob the collector already uses.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    force=True,
)

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    openapi_tags=tags_metadata,
    docs_url=None if DISABLE_DOCS else "/docs",
    redoc_url=None if DISABLE_DOCS else "/redoc",
    openapi_url=None if DISABLE_DOCS else "/openapi.json",
    contact={
        "name": "DNA Project",
        "url": "https://github.com/AcademySoftwareFoundation/dna",
    },
)

app.add_middleware(CORSMiddleware, **get_cors_middleware_kwargs())


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------


@lru_cache
def get_prodtrack_provider_cached() -> ProdtrackProviderBase:
    """Get or create the production tracking provider singleton."""
    return get_prodtrack_provider()


@lru_cache
def get_storage_provider_cached() -> StorageProviderBase:
    """Get or create the storage provider singleton."""
    return get_storage_provider()


@lru_cache
def get_transcription_provider_cached() -> TranscriptionProviderBase:
    """Get or create the transcription provider singleton."""
    return get_transcription_provider()


@lru_cache
def get_llm_provider_cached() -> LLMProviderBase:
    """Get or create the LLM provider singleton."""
    return get_llm_provider()


ProdtrackProviderDep = Annotated[
    ProdtrackProviderBase, Depends(get_prodtrack_provider_cached)
]

StorageProviderDep = Annotated[
    StorageProviderBase, Depends(get_storage_provider_cached)
]

TranscriptionProviderDep = Annotated[
    TranscriptionProviderBase, Depends(get_transcription_provider_cached)
]

LLMProviderDep = Annotated[LLMProviderBase, Depends(get_llm_provider_cached)]


@lru_cache
def get_transcription_service_cached() -> TranscriptionService:
    """Get or create the transcription service singleton."""
    return get_transcription_service()


TranscriptionServiceDep = Annotated[
    TranscriptionService, Depends(get_transcription_service_cached)
]


# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)


@lru_cache
def get_auth_provider_cached() -> Optional[AuthProviderBase]:
    """Get or create the auth provider singleton."""
    return get_auth_provider()


AuthProviderDep = Annotated[
    Optional[AuthProviderBase], Depends(get_auth_provider_cached)
]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    auth_provider: AuthProviderDep = None,
) -> str:
    """Validate the auth token and return the user's email.

    Returns the user's email from the validated token.
    Raises HTTPException 401 if token is missing or invalid.

    When AUTH_PROVIDER=none, authentication is skipped and a placeholder
    email is returned (for development/testing only).
    """
    auth_provider_type = os.getenv("AUTH_PROVIDER", "none")
    if auth_provider_type == "none":
        if credentials and credentials.credentials:
            return auth_provider.get_user_email(credentials.credentials)
        return "anonymous@localhost"

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = auth_provider.validate_token(credentials.credentials)
        # Safely access the email claim to avoid KeyError and return 401 on missing email
        email = claims.get("email") if isinstance(claims, dict) else None
        if not email:
            raise HTTPException(
                status_code=401,
                detail="Missing email claim in authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return email
    except ValueError as e:
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


CurrentUserDep = Annotated[str, Depends(get_current_user)]


# -----------------------------------------------------------------------------
# Lifecycle events
# -----------------------------------------------------------------------------


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    service = get_transcription_service()
    await service.init_providers()
    storage = service.storage_provider
    ensure_indexes = getattr(storage, "ensure_indexes", None)
    if callable(ensure_indexes):
        await ensure_indexes()
    await service.resubscribe_to_active_meetings()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown."""
    service = get_transcription_service()
    await service.close()


# -----------------------------------------------------------------------------
# Health endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/",
    tags=["Health"],
    summary="Root endpoint",
    description="Returns basic API information and version.",
    response_description="API information with name and version",
)
async def root():
    """Root endpoint returning API information."""
    return {"message": "DNA Backend API", "version": API_VERSION}


@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check if the API is running and healthy.",
    response_description="Health status of the API",
)
async def health():
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "healthy"}


@app.get(
    "/capabilities",
    tags=["Health"],
    summary="What this deployment supports",
    description=(
        "Optional pipelines this deployment is configured for. The front end asks once at "
        "start-up and hides the features that are not here."
    ),
    response_description="A flag per optional pipeline",
)
async def capabilities() -> dict[str, bool]:
    """What the front end may offer, decided by the deployment that has the pipeline.

    Whether meeting recordings can be played back is a fact about this installation — it needs a
    recorder, a collector and a share — and the back end is the side that knows. Mirroring it into
    a second front-end build flag meant two settings that had to agree, and a deployment where
    they disagreed showed either a tab whose every request 404s or no tab at all for recordings
    that exist. Asking removes the second setting rather than documenting it.
    """
    return {"recording_playback": recording_playback_enabled()}


@app.post(
    "/test/broadcast-transcript",
    tags=["Testing"],
    summary="Broadcast a synthetic transcript (dev-only).",
    include_in_schema=False,
)
async def test_broadcast_transcript(payload: dict) -> dict:
    """Dev-only endpoint for tests-vm/. Gated by DNA_TESTING_ENABLED=true.

    Forwards the JSON body verbatim to every WebSocket client — lets us
    assert the broadcast shape end-to-end without needing a real meeting.
    """
    if os.getenv("DNA_TESTING_ENABLED", "false").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="Not found")
    publisher = get_event_publisher()
    await publisher.ws_manager.broadcast(payload)
    return {"broadcasted": True, "clients": publisher.ws_manager.connection_count}


MOCK_THUMBNAILS_DIR = (
    Path(__file__).parent / "dna" / "prodtrack_providers" / "mock_data" / "thumbnails"
)
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
THUMBNAIL_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

ATTACHMENT_STORE_DIR = Path(os.getenv("ATTACHMENT_STORE_DIR", "/tmp/dna_attachments"))
ATTACHMENT_STORE_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/attachments", tags=["Attachments"])
async def upload_attachment(
    _: CurrentUserDep,
    file: UploadFile = File(...),
) -> dict:
    """Save an uploaded file and return its attachment ID."""
    attachment_id = str(uuid.uuid4())
    dest_dir = ATTACHMENT_STORE_DIR / attachment_id
    dest_dir.mkdir(parents=True)
    filename = file.filename or "attachment"
    dest_path = dest_dir / filename
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"id": attachment_id, "filename": filename}


@app.get(
    "/api/attachments/{attachment_id}",
    tags=["Attachments"],
    summary="Retrieve a staged attachment",
    response_class=FileResponse,
)
async def get_attachment(attachment_id: str, _: CurrentUserDep) -> FileResponse:
    """Return the image file for a staged attachment by ID."""
    attachment_dir = ATTACHMENT_STORE_DIR / attachment_id
    if not attachment_dir.exists():
        raise HTTPException(status_code=404, detail="Attachment not found")
    files = list(attachment_dir.iterdir())
    if not files:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = files[0]
    suffix = path.suffix.lower()
    media_type = THUMBNAIL_MEDIA_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.delete("/api/attachments/{attachment_id}", tags=["Attachments"])
async def delete_attachment(attachment_id: str, _: CurrentUserDep) -> dict:
    """Delete a staged attachment by ID."""
    attachment_dir = ATTACHMENT_STORE_DIR / attachment_id
    if not attachment_dir.exists():
        raise HTTPException(status_code=404, detail="Attachment not found")
    shutil.rmtree(attachment_dir)
    return {"deleted": attachment_id}


@app.get(
    "/api/mock-thumbnails/{version_id}",
    tags=["Versions"],
    summary="Serve mock thumbnail image",
    description="Returns a thumbnail image for a version from the mock dataset (when using mock prodtrack provider).",
    response_class=FileResponse,
)
async def get_mock_thumbnail(version_id: int):
    """Serve a thumbnail image from mock_data/thumbnails/ for the given version ID."""
    for ext in THUMBNAIL_EXTENSIONS:
        path = MOCK_THUMBNAILS_DIR / f"{version_id}{ext}"
        if path.is_file():
            media_type = THUMBNAIL_MEDIA_TYPES.get(ext, "image/jpeg")
            return FileResponse(path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Thumbnail not found")


# -----------------------------------------------------------------------------
# WebSocket endpoint
# -----------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time event streaming.

    Clients connect to this endpoint to receive real-time events such as:
    - transcript: Raw Vexa-shaped transcript ticks (flat envelope with
      `speaker`, `confirmed`, `pending`, `playlist_id`, `version_id`, `ts`).
      Consumed by the frontend `TranscriptManager`.
    - bot.status_changed: Bot status updates
    - transcription.completed / transcription.error: Transcription lifecycle events

    Most events use `{"type": "event.type", "payload": {...}}`. The
    `transcript` event is flat — the whole message IS the payload so it can
    be fed to `TranscriptManager.handleMessage()` without reshaping.
    """
    event_publisher = get_event_publisher()
    ws_manager = event_publisher.ws_manager

    await ws_manager.connect(websocket)
    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        await ws_manager.disconnect(websocket)


# -----------------------------------------------------------------------------
# Entity endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/version/{version_id}",
    tags=["Versions"],
    summary="Get a version by ID",
    description="Retrieve version information from the production tracking system.",
    response_model=Version,
)
async def get_version(
    version_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Version:
    """Get a version entity by its ID."""
    try:
        return cast(Version, provider.get_entity("version", version_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/playlist/{playlist_id}",
    tags=["Playlists"],
    summary="Get a playlist by ID",
    description="Retrieve playlist information including linked versions.",
    response_model=Playlist,
)
async def get_playlist(
    playlist_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Playlist:
    """Get a playlist entity by its ID."""
    try:
        return cast(Playlist, provider.get_entity("playlist", playlist_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/shot/{shot_id}",
    tags=["Shots"],
    summary="Get a shot by ID",
    description="Retrieve shot information from the production tracking system.",
    response_model=Shot,
)
async def get_shot(
    shot_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Shot:
    """Get a shot entity by its ID."""
    try:
        return cast(Shot, provider.get_entity("shot", shot_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/asset/{asset_id}",
    tags=["Assets"],
    summary="Get an asset by ID",
    description="Retrieve asset information from the production tracking system.",
    response_model=Asset,
)
async def get_asset(
    asset_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Asset:
    """Get an asset entity by its ID."""
    try:
        return cast(Asset, provider.get_entity("asset", asset_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/task/{task_id}",
    tags=["Tasks"],
    summary="Get a task by ID",
    description="Retrieve task information from the production tracking system.",
    response_model=Task,
)
async def get_task(
    task_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Task:
    """Get a task entity by its ID."""
    try:
        return cast(Task, provider.get_entity("task", task_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/note/{note_id}",
    tags=["Notes"],
    summary="Get a note by ID",
    description="Retrieve note information from the production tracking system.",
    response_model=Note,
)
async def get_note(
    note_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Note:
    """Get a note entity by its ID."""
    try:
        return cast(Note, provider.get_entity("note", note_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -----------------------------------------------------------------------------
# Entity creation endpoints (POST)
# -----------------------------------------------------------------------------


def _create_stub_entity(entity_type: str, entity_id: int) -> EntityBase:
    """Create a minimal entity stub for linking purposes."""
    entity_map = {
        "Version": Version,
        "Playlist": Playlist,
        "Shot": Shot,
        "Asset": Asset,
        "Task": Task,
        "Note": Note,
    }
    model_class = entity_map.get(entity_type)
    if model_class is None:
        raise ValueError(f"Unknown entity type: {entity_type}")

    if entity_type == "Playlist":
        return model_class(id=entity_id, code="stub")
    return model_class(id=entity_id, name="stub")


@app.post(
    "/note",
    tags=["Notes"],
    summary="Create a new note",
    description="Create a new note in the production tracking system.",
    response_model=Note,
    status_code=201,
)
async def create_note(
    request: CreateNoteRequest, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> Note:
    """Create a new note entity."""
    try:
        note_links = []
        if request.note_links:
            for link in request.note_links:
                note_links.append(_create_stub_entity(link.type, link.id))

        note = Note(
            id=0,
            subject=request.subject,
            content=request.content,
            project=request.project,
            note_links=note_links,
        )
        return cast(Note, provider.add_entity("note", note))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------------
# Find endpoint
# -----------------------------------------------------------------------------


@app.post(
    "/find",
    tags=["Entities"],
    summary="Find entities",
    description="Search for entities matching the given filters.",
    response_model=list[EntityBase],
)
async def find_entities(
    request: FindRequest, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> list[EntityBase]:
    """Find entities matching the given filters."""
    entity_type = request.entity_type.lower()

    if entity_type not in ENTITY_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported entity type: '{request.entity_type}'. "
            f"Supported types: {list(ENTITY_MODELS.keys())}",
        )

    try:
        filters = [f.model_dump() for f in request.filters]
        return provider.find(entity_type, filters)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/search",
    tags=["Entities"],
    summary="Search entities across multiple types",
    description="Unified search endpoint for @mentions and entity linking.",
    response_model=dict[str, list[SearchResult]],
)
async def search_entities(
    request: SearchRequest, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> dict[str, list[SearchResult]]:
    """Search for entities across multiple entity types."""
    # Validate entity types
    for entity_type in request.entity_types:
        if entity_type.lower() not in ENTITY_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported entity type: '{entity_type}'. "
                f"Supported types: {list(ENTITY_MODELS.keys())}",
            )

    try:
        results = provider.search(
            query=request.query,
            entity_types=[et.lower() for et in request.entity_types],
            project_id=request.project_id,
            limit=request.limit,
        )
        return {"results": results}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/version-statuses",
    tags=["Versions"],
    summary="Get valid version statuses",
    description="Get valid status options for versions from the production tracking system.",
    response_model=list[StatusOption],
)
async def get_version_statuses(
    provider: ProdtrackProviderDep,
    project_id: Optional[int] = None,
) -> list[StatusOption]:
    """Get valid status options for versions."""
    try:
        statuses = provider.get_version_statuses(project_id)
        return [StatusOption(**s) for s in statuses]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------------
# User endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/users/{user_email}",
    tags=["Users"],
    summary="Get user by email",
    description="Retrieve user information by their email address.",
    response_model=User,
)
async def get_user_by_email(
    user_email: str, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> User:
    """Get a user by their email address."""
    try:
        return provider.get_user_by_email(user_email)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -----------------------------------------------------------------------------
# Project endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/projects/user/{user_email}",
    tags=["Projects"],
    summary="Get projects for a user",
    description="Retrieve all projects accessible by the specified user email.",
    response_model=list[Project],
)
async def get_projects_for_user(
    user_email: str, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> list[Project]:
    """Get projects for a user by their email address."""
    try:
        return provider.get_projects_for_user(user_email)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/projects/{project_id}/playlists",
    tags=["Playlists"],
    summary="Get playlists for a project",
    description="Retrieve all playlists for the specified project.",
    response_model=list[Playlist],
)
async def get_playlists_for_project(
    project_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> list[Playlist]:
    """Get playlists for a project."""
    try:
        return provider.get_playlists_for_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/playlists/{playlist_id}/versions",
    tags=["Versions"],
    summary="Get versions for a playlist",
    description="Retrieve all versions in the specified playlist.",
    response_model=list[Version],
)
async def get_versions_for_playlist(
    playlist_id: int, provider: ProdtrackProviderDep, _: CurrentUserDep
) -> list[Version]:
    """Get versions for a playlist."""
    try:
        return provider.get_versions_for_playlist(playlist_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _versions_by_external_ref(
    provider: ProdtrackProviderBase, project_id: int, jts: list[int]
) -> dict[int, Version]:
    """The versions on a project carrying these external review ids, keyed by the id asked for.

    One query for the whole list, because the list is the point: a review is assembled by pasting
    the ids the review tool announced, and asking the tracking system once per id would turn a
    paste of forty into forty round trips.
    """
    matches = provider.find(
        "version",
        [
            {"field": "external_ref", "operator": "in", "value": jts},
            {
                "field": "project",
                "operator": "is",
                "value": {"type": "Project", "id": project_id},
            },
        ],
    )
    by_ref: dict[int, Version] = {}
    for match in cast(list[Version], matches):
        if match.external_ref is None:
            continue
        try:
            by_ref[int(match.external_ref)] = match
        except ValueError:
            # A site whose external ref is not a number has no business in this endpoint, but one
            # unparseable row should not take the rest of the paste down with it.
            continue
    return by_ref


@app.post(
    "/playlists/{playlist_id}/versions",
    tags=["Versions"],
    summary="Add versions to a playlist",
    description=(
        "Append versions to the end of a playlist, by the id the review tool announces for them "
        "(the JTS at SPI). Takes a list, so a pasted set of ids goes in at once; each is "
        "answered for separately. Versions already in the playlist keep their place and order."
    ),
    response_model=AddVersionsToPlaylistResponse,
    status_code=201,
)
async def add_versions_to_playlist(
    playlist_id: int,
    request: AddVersionsToPlaylistRequest,
    provider: ProdtrackProviderDep,
    _: CurrentUserDep,
) -> AddVersionsToPlaylistResponse:
    """Append versions to a playlist, resolving each by its external review id."""
    # The same id twice in a paste is one version, and would otherwise be reported twice.
    requested = list(dict.fromkeys(request.jts))

    try:
        playlist = cast(
            Playlist, provider.get_entity("playlist", playlist_id, resolve_links=False)
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found")

    project_id = (playlist.project or {}).get("id")
    if project_id is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Playlist {playlist_id} is not on a project, so there is nowhere to look "
                "versions up."
            ),
        )

    try:
        found = _versions_by_external_ref(provider, project_id, requested)
    except ValueError as e:
        # Chiefly the deployment having no external-ref field configured, which makes this
        # endpoint unusable rather than the request wrong -- say which it is.
        raise HTTPException(
            status_code=501,
            detail=(
                "This deployment cannot look versions up by review id: "
                f"{e}. Set PRODTRACK_VERSION_EXTERNAL_REF_FIELD to the field holding it."
            ),
        )

    try:
        appended = provider.add_versions_to_playlist(
            playlist_id, [found[ref].id for ref in requested if ref in found]
        )
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    was_appended = set(appended)
    outcomes = []
    for ref in requested:
        version = found.get(ref)
        if version is None:
            outcomes.append(AddVersionOutcome(jts=ref, status="not_found"))
            continue
        outcomes.append(
            AddVersionOutcome(
                jts=ref,
                status=(
                    "added" if version.id in was_appended else "already_in_playlist"
                ),
                version_id=version.id,
                version_name=version.name,
            )
        )

    return AddVersionsToPlaylistResponse(
        outcomes=outcomes, added_count=len(was_appended)
    )


@app.post(
    "/playlists/{playlist_id}/publish-notes",
    tags=["Playlists"],
    summary="Publish draft notes",
    description="Publish draft notes to the production tracking system.",
    response_model=PublishNotesResponse,
)
async def publish_notes(
    playlist_id: int,
    request: PublishNotesRequest,
    storage: StorageProviderDep,
    prodtrack: ProdtrackProviderDep,
    _: CurrentUserDep,
) -> PublishNotesResponse:
    """Publish draft notes to the production tracking system."""
    # 1. Get all draft notes for this playlist
    all_draft_notes = await storage.get_draft_notes_for_playlist(playlist_id)

    # 2. Filter and deduplicate notes
    # Group by (user, version) and keep only the most recently updated note
    from collections import defaultdict

    notes_by_key = defaultdict(list)
    for note in all_draft_notes:
        key = (note.user_email, note.version_id)
        notes_by_key[key].append(note)

    target_keys = {(t.user_email, t.version_id) for t in request.targets}

    notes_to_publish = []
    for key, notes in notes_by_key.items():
        # Sort by updated_at descending and take the most recent one
        most_recent = max(notes, key=lambda n: n.updated_at)

        if (most_recent.user_email, most_recent.version_id) not in target_keys:
            continue

        notes_to_publish.append(most_recent)

    # 3. Publish each note
    published_count = 0
    republished_count = 0
    failed_count = 0
    skipped_count = 0

    from datetime import datetime, timezone

    def _upload_attachments(sg_note_id: int, attachment_ids: list[str]) -> None:
        """Upload staged attachment files to a ShotGrid note and clean up local files."""
        for attachment_id in attachment_ids:
            attachment_dir = ATTACHMENT_STORE_DIR / attachment_id
            if not attachment_dir.exists():
                continue
            files = list(attachment_dir.iterdir())
            if not files:
                continue
            file_path = files[0]
            prodtrack.attach_file_to_note(
                note_id=sg_note_id,
                file_path=str(file_path),
                display_name=file_path.name,
            )
            shutil.rmtree(attachment_dir)

    for note in notes_to_publish:
        try:
            # Skip notes with no meaningful content to publish
            has_body = (note.content and note.content.strip()) or (
                note.subject and note.subject.strip()
            )
            if not has_body and not note.attachment_ids and not note.version_status:
                skipped_count += 1
                continue

            # Status-only change with no note body: update version status without
            # creating or publishing a note, and do not mark the draft as published.
            if not has_body and not note.attachment_ids and note.version_status:
                prodtrack.update_version_status(note.version_id, note.version_status)
                skipped_count += 1
                continue

            if note.published_note_id:
                if note.published and not note.edited and not note.attachment_ids:
                    # Still apply any pending version status change
                    if note.version_status:
                        prodtrack.update_version_status(
                            note.version_id, note.version_status
                        )
                    skipped_count += 1
                    continue

                if not note.published or note.edited:
                    success = prodtrack.update_note(
                        note_id=note.published_note_id,
                        content=note.content,
                        subject=note.subject,
                        version_id=note.version_id,
                        version_status=note.version_status or None,
                    )
                    if not success:
                        failed_count += 1
                        continue

                if note.attachment_ids:
                    _upload_attachments(note.published_note_id, note.attachment_ids)

                republished_count += 1
                update_data = DraftNoteUpdate(
                    published=True,
                    edited=False,
                    published_at=datetime.now(timezone.utc),
                    attachment_ids=[],
                )
                await storage.upsert_draft_note(
                    user_email=note.user_email,
                    playlist_id=note.playlist_id,
                    version_id=note.version_id,
                    data=update_data,
                )
                continue

            # Get links
            links = []
            if note.links:
                for link in note.links:
                    model_class = ENTITY_MODELS.get(link.entity_type)
                    if model_class:
                        links.append(model_class(id=link.entity_id))

            # Ensure playlist is included in links
            playlist_link_exists = any(
                isinstance(l, Playlist) and l.id == playlist_id for l in links
            )
            if not playlist_link_exists:
                links.append(_create_stub_entity("Playlist", playlist_id))

            # Ensure version's parent entity (Shot/Asset) is included in links
            version = prodtrack.get_entity(
                "version", note.version_id, resolve_links=False
            )
            if version and version.entity:
                entity_link_exists = any(
                    l.id == version.entity.id and l.type == version.entity.type
                    for l in links
                )
                if not entity_link_exists:
                    links.append(version.entity)

            note_id = prodtrack.publish_note(
                version_id=note.version_id,
                content=note.content,
                subject=note.subject,
                to_users=[],  # TODO: Parse to/cc
                cc_users=[],
                links=links,
                author_email=note.user_email,
                version_status=note.version_status or None,
            )

            if note.attachment_ids:
                _upload_attachments(note_id, note.attachment_ids)

            # Update draft note as published (clear attachment_ids after upload)
            update_data = DraftNoteUpdate(
                published=True,
                edited=False,
                published_at=datetime.now(timezone.utc),
                published_note_id=note_id,
                attachment_ids=[],
            )

            await storage.upsert_draft_note(
                user_email=note.user_email,
                playlist_id=note.playlist_id,
                version_id=note.version_id,
                data=update_data,
            )

            published_count += 1

        except Exception as e:
            print(f"Failed to publish note {note.id}: {e}")
            failed_count += 1

    return PublishNotesResponse(
        published_count=published_count,
        republished_count=republished_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        total=len(notes_to_publish),
    )


def _transcript_publish_enabled() -> bool:
    return os.getenv("DNA_ENABLE_TRANSCRIPT_PUBLISH", "false").lower() == "true"


@app.post(
    "/playlists/{playlist_id}/publish-transcript",
    tags=["Playlists", "Transcription"],
    summary="Publish a version's captured transcript",
    description=(
        "Push the stored transcript for a version to the production tracking "
        "system as a single custom-entity row. Idempotent via body_hash."
    ),
    response_model=PublishTranscriptResponse,
)
async def publish_transcript(
    playlist_id: int,
    request: PublishTranscriptRequest,
    storage: StorageProviderDep,
    prodtrack: ProdtrackProviderDep,
    current_user: CurrentUserDep,
) -> PublishTranscriptResponse:
    """Publish one version's transcript; skip when body_hash has not changed."""
    if not _transcript_publish_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    from dna.transcription_publish import build_transcript_payload

    metadata = await storage.get_playlist_metadata(playlist_id)
    if metadata is None or not metadata.meeting_id:
        raise HTTPException(
            status_code=422,
            detail="Playlist has no meeting associated yet",
        )
    if not metadata.platform:
        # Empty platform would be rejected downstream as an opaque SG schema
        # fault; surface a clean 422 instead.
        raise HTTPException(
            status_code=422,
            detail="Playlist metadata has no platform recorded",
        )

    segments = await storage.get_segments_for_version(playlist_id, request.version_id)
    if not segments:
        raise HTTPException(
            status_code=422,
            detail="No transcript segments stored for this version",
        )

    payload = build_transcript_payload(segments)
    if payload.segments_count == 0:
        # Segments existed but all were whitespace-only; refuse rather than
        # create an empty row.
        raise HTTPException(
            status_code=422,
            detail="All stored segments were empty; nothing to publish",
        )

    existing = await storage.get_published_transcript(
        playlist_id, request.version_id, metadata.meeting_id
    )
    if existing and existing.body_hash == payload.body_hash:
        return PublishTranscriptResponse(
            transcript_entity_id=existing.entity_id,
            outcome="skipped",
            skipped_reason="no_changes_since_last_publish",
            segments_count=payload.segments_count,
        )

    try:
        version = prodtrack.get_entity(
            "version", request.version_id, resolve_links=False
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Version.project is a dict {type, id, name}, not an object — don't try
    # project_ref.id.
    project_ref = getattr(version, "project", None)
    project_id = project_ref.get("id") if isinstance(project_ref, dict) else None
    if project_id is None:
        raise HTTPException(
            status_code=404,
            detail="Version has no project associated",
        )

    try:
        if existing:
            # Take entity_type from bookkeeping, not env — sites can migrate
            # the slot after the row is created, and the update must still
            # target the original entity.
            updated = prodtrack.update_transcript(
                entity_type=existing.entity_type,
                entity_id=existing.entity_id,
                body=payload.body,
                meeting_date=payload.meeting_date,
            )
            if not updated:
                # Raise (and skip the bookkeeping upsert below) so the next
                # call doesn't see a matching body_hash and incorrectly skip.
                raise HTTPException(
                    status_code=502,
                    detail="Failed to update transcript on the tracking system",
                )
            entity_id = existing.entity_id
            outcome = "updated"
        else:
            entity_id = prodtrack.publish_transcript(
                project_id=project_id,
                playlist_id=playlist_id,
                version_id=request.version_id,
                meeting_id=metadata.meeting_id,
                meeting_date=payload.meeting_date,
                platform=metadata.platform,
                body=payload.body,
            )
            outcome = "created"
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

    entity_type = os.getenv("SHOTGRID_TRANSCRIPT_ENTITY", "CustomEntity01")
    try:
        await storage.upsert_published_transcript(
            PublishedTranscriptUpdate(
                playlist_id=playlist_id,
                version_id=request.version_id,
                meeting_id=metadata.meeting_id,
                entity_type=entity_type,
                entity_id=entity_id,
                author_email=current_user,
                body_hash=payload.body_hash,
                segments_count=payload.segments_count,
            )
        )
    except Exception as e:
        # SG row exists but local bookkeeping didn't make it. The next call
        # with the same body would see existing=None and create a duplicate
        # SG row. Surface entity_id so an operator can reconcile manually,
        # and signal to the client that blind retry is unsafe.
        logger = logging.getLogger(__name__)
        logger.exception(
            "Transcript %s created on tracking system id=%s but local "
            "bookkeeping failed. Next publish will create a duplicate unless "
            "the SG row is removed or the bookkeeping row is written manually.",
            outcome,
            entity_id,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Transcript row {entity_id} was {outcome} on the tracking "
                f"system but local bookkeeping failed ({e.__class__.__name__}). "
                f"Do not retry blindly; reconcile the row manually."
            ),
        )

    return PublishTranscriptResponse(
        transcript_entity_id=entity_id,
        outcome=outcome,
        segments_count=payload.segments_count,
    )


# -----------------------------------------------------------------------------
# Email notes endpoint
# -----------------------------------------------------------------------------


@app.post(
    "/playlists/{playlist_id}/email-notes",
    tags=["Playlists", "Notes"],
    summary="Email notes for a playlist",
    description="Send all draft notes and transcripts for a playlist as a formatted HTML email.",
    status_code=204,
)
async def email_notes(
    playlist_id: int,
    request: EmailNotesRequest,
    storage: StorageProviderDep,
    prodtrack: ProdtrackProviderDep,
    current_user_email: CurrentUserDep,
) -> None:
    from dna.email_service import (
        InlineImage,
        build_notes_html,
        poster_cid,
        send_notes_email,
    )

    versions = prodtrack.get_versions_for_playlist(playlist_id)

    # Mirror the UI: include only the sender's own notes (manual + AI-inserted).
    # Notes synced in from ShotGrid live under their original authors' emails and
    # are never shown to this user, so filtering by the current user drops them.
    all_drafts = await storage.get_draft_notes_for_playlist(playlist_id)
    drafts_by_version: dict[int, list] = {}
    for d in all_drafts:
        if emails_match(d.user_email, current_user_email):
            drafts_by_version.setdefault(d.version_id, []).append(d)

    playlist_name = f"Playlist {playlist_id}"
    playlist_code = ""
    playlist_url: Optional[str] = None
    project_id: Optional[int] = None
    try:
        playlist = prodtrack.get_entity("playlist", playlist_id, resolve_links=False)
        if playlist and getattr(playlist, "code", None):
            playlist_name = playlist.code
            playlist_code = playlist.code
        if playlist and getattr(playlist, "project", None):
            project_id = playlist.project.get("id")
        # The playlist in the production tracker, for the reader who wants the versions
        # themselves rather than what was said about them. Absent on a provider that has no web
        # UI to point at, and the header simply omits the row.
        playlist_url = getattr(playlist, "prodtrack_detail_url", None)
    except Exception:
        pass

    project_name = ""
    if versions and versions[0].project:
        project_name = versions[0].project.get("name", "")
        if project_id is None:
            project_id = versions[0].project.get("id")

    # The show's short code, which the review URL prefers over its name. It is not on the
    # version's project link — that carries id, name and type — so it costs a lookup, and a failed
    # one only costs the readable form: the address then falls back to its id, which still
    # resolves. Sites whose ShotGrid projects have no tank_name fall back to the name instead.
    project_code = ""
    if project_id is not None:
        try:
            project = prodtrack.get_entity(
                "project", int(project_id), resolve_links=False
            )
            project_code = getattr(project, "code", "") or ""
        except Exception:
            pass

    subject = request.subject or playlist_name

    # Poster frames, carried IN the message rather than linked. The collector wrote them beside
    # the archive on the air-gapped host and pushed the bytes here; a mail client asking that host
    # for an image only works from inside the network, and Gmail's web client — which fetches
    # every image through a Google proxy — never does. Only versions this email is actually
    # writing about are attached, so a poster left over from a version since removed from the
    # playlist does not ride along.
    wanted = {version.id for version in versions}
    inline_images: list[InlineImage] = []
    poster_cids: dict[int, str] = {}
    try:
        for poster in await storage.get_recording_posters(playlist_id):
            if poster.version_id not in wanted or not poster.image:
                continue
            cid = poster_cid(playlist_id, poster.version_id)
            poster_cids[poster.version_id] = cid
            inline_images.append(
                InlineImage(
                    cid=cid,
                    data=poster.image,
                    filename=poster.filename or f"{cid}.jpg",
                    subtype=poster.content_type.split("/")[-1] or "jpeg",
                )
            )
    except Exception:
        # A thumbnail is a cue, not the message. The notes go out without pictures rather than
        # not at all.
        logging.getLogger(__name__).warning(
            "Playlist %s: could not load poster frames for the notes email",
            playlist_id,
            exc_info=True,
        )

    html_body = build_notes_html(
        playlist_name=playlist_name,
        project_name=project_name,
        sent_by=request.sent_by,
        versions=versions,
        drafts_by_version=drafts_by_version,
        review_url=review_url(playlist_id, playlist_code, project_code, project_name),
        playlist_url=playlist_url,
        poster_cids=poster_cids,
    )

    try:
        send_notes_email(
            to=request.to,
            subject=subject,
            html_content=html_body,
            cc=request.cc,
            inline_images=inline_images,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Draft Notes endpoints
# -----------------------------------------------------------------------------


async def _sync_published_notes(
    playlist_id: int,
    prodtrack: ProdtrackProviderBase,
    storage: StorageProviderBase,
):
    """Sync published notes from ShotGrid to local storage.

    Fetches notes via get_versions_for_playlist (which now populates notes).
    If multiple notes exist for the same version and author, only the most
    recent one is synced.
    """
    try:
        # 1. Get all versions for the playlist (now includes notes)
        versions = prodtrack.get_versions_for_playlist(playlist_id)
        if not versions:
            return

        # 2. Group by (version_id, author_email) and find latest
        # Map: (version_id, author_email) -> Note
        latest_notes: dict[tuple[int, str], Note] = {}

        for version in versions:
            if not version.notes:
                continue

            for note in version.notes:
                if not note.author or not note.author.email:
                    continue

                key = (version.id, note.author.email)
                existing = latest_notes.get(key)

                # If no existing note for this key, or current note is newer
                if not existing or note.id > existing.id:
                    latest_notes[key] = note

        # 3. Upsert selected notes to storage
        from datetime import datetime, timezone

        for (vid, email), note in latest_notes.items():
            update_data = DraftNoteUpdate(
                content=note.content or "",
                subject=note.subject or "",
                published=True,
                edited=False,
                published_at=datetime.now(timezone.utc),
                published_note_id=note.id,
            )

            await storage.upsert_published_note(
                user_email=email,
                playlist_id=playlist_id,
                version_id=vid,
                data=update_data,
            )

    except Exception as e:
        print(f"Error syncing published notes: {e}")


@app.get(
    "/playlists/{playlist_id}/draft-notes",
    tags=["Draft Notes"],
    summary="Get all draft notes for a playlist",
    description="Retrieve all users' draft notes for the specified playlist.",
    response_model=list[DraftNote],
)
async def get_playlist_draft_notes(
    playlist_id: int,
    provider: StorageProviderDep,
    prodtrack: ProdtrackProviderDep,
    _: CurrentUserDep,
) -> list[DraftNote]:
    """Get all draft notes for a playlist."""
    # Sync published notes first
    await _sync_published_notes(playlist_id, prodtrack, provider)
    return await provider.get_draft_notes_for_playlist(playlist_id)


@app.get(
    "/playlists/{playlist_id}/versions/{version_id}/draft-notes",
    tags=["Draft Notes"],
    summary="Get all draft notes for a version",
    description="Retrieve all users' draft notes for the specified playlist/version.",
    response_model=list[DraftNote],
)
async def get_all_draft_notes(
    playlist_id: int,
    version_id: int,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> list[DraftNote]:
    """Get all users' draft notes for this playlist/version."""
    return await provider.get_draft_notes_for_version(playlist_id, version_id)


@app.get(
    "/playlists/{playlist_id}/versions/{version_id}/draft-notes/{user_email}",
    tags=["Draft Notes"],
    summary="Get draft note for a user",
    description="Retrieve a specific user's draft note for the playlist/version.",
    response_model=Optional[DraftNote],
)
async def get_draft_note(
    playlist_id: int,
    version_id: int,
    user_email: str,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> Optional[DraftNote]:
    """Get a specific user's draft note."""
    return await provider.get_draft_note(user_email, playlist_id, version_id)


@app.put(
    "/playlists/{playlist_id}/versions/{version_id}/draft-notes/{user_email}",
    tags=["Draft Notes"],
    summary="Create or update a draft note",
    description="Create or update a user's draft note for the playlist/version.",
    response_model=DraftNote,
)
async def upsert_draft_note(
    playlist_id: int,
    version_id: int,
    user_email: str,
    data: DraftNoteUpdate,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> DraftNote:
    """Create or update a user's draft note."""

    return await provider.upsert_draft_note(user_email, playlist_id, version_id, data)


@app.delete(
    "/playlists/{playlist_id}/versions/{version_id}/draft-notes/{user_email}",
    tags=["Draft Notes"],
    summary="Delete a draft note",
    description="Delete a user's draft note for the playlist/version.",
    response_model=bool,
)
async def delete_draft_note(
    playlist_id: int,
    version_id: int,
    user_email: str,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> bool:
    """Delete a user's draft note."""
    deleted = await provider.delete_draft_note(user_email, playlist_id, version_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft note not found")
    return True


# -----------------------------------------------------------------------------
# Playlist Metadata endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/playlists/{playlist_id}/metadata",
    tags=["Playlist Metadata"],
    summary="Get playlist metadata",
    description="Retrieve metadata for a playlist including in-review version and meeting ID.",
    response_model=Optional[PlaylistMetadata],
)
async def get_playlist_metadata(
    playlist_id: int,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> Optional[PlaylistMetadata]:
    """Get playlist metadata."""
    return await provider.get_playlist_metadata(playlist_id)


@app.put(
    "/playlists/{playlist_id}/metadata",
    tags=["Playlist Metadata"],
    summary="Create or update playlist metadata",
    description="Create or update metadata for a playlist (in-review version and meeting ID).",
    response_model=PlaylistMetadata,
)
async def upsert_playlist_metadata(
    playlist_id: int,
    data: PlaylistMetadataUpdate,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> PlaylistMetadata:
    """Create or update playlist metadata."""
    return await provider.upsert_playlist_metadata(playlist_id, data)


@app.delete(
    "/playlists/{playlist_id}/metadata",
    tags=["Playlist Metadata"],
    summary="Delete playlist metadata",
    description="Delete metadata for a playlist.",
    response_model=bool,
)
async def delete_playlist_metadata(
    playlist_id: int,
    provider: StorageProviderDep,
    _: CurrentUserDep,
) -> bool:
    """Delete playlist metadata."""
    deleted = await provider.delete_playlist_metadata(playlist_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Playlist metadata not found")
    return True


def _playlist_reset_enabled() -> bool:
    return os.getenv("DNA_ENABLE_PLAYLIST_RESET", "false").lower() == "true"


@app.delete(
    "/playlists/{playlist_id}/data",
    tags=["Playlist Metadata"],
    summary="Forget everything stored about a playlist",
    description=(
        "Clears this playlist's segments, metadata, recording poster frames and (unless "
        "keep_notes) draft notes, so an end-to-end test can be re-run from scratch. Off unless "
        "DNA_ENABLE_PLAYLIST_RESET=true.\n\n"
        "Touches only DNA's own store. The production tracking system is never contacted: the "
        "notes and versions there are not DNA's to delete, only to mirror."
    ),
)
async def reset_playlist_data(
    playlist_id: int,
    provider: StorageProviderDep,
    _: CurrentUserDep,
    keep_notes: bool = False,
) -> dict[str, Any]:
    """Delete a playlist's stored transcript, metadata and draft notes.

    Exists because the recording host can be air-gapped from the database: everything else here
    could be cleared by hand beside Mongo, but a collector that only reaches this API had no way
    to reset the playlist it just recorded. One call, so a reset cannot half-finish across the
    link and leave a transcript behind that the next test then appends to.

    Gated off by default. Every other delete removes one row a person named; this removes a whole
    playlist's history, which is worth an explicit opt-in per deployment rather than being live
    everywhere the moment it ships.
    """
    if not _playlist_reset_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    deleted = await provider.delete_playlist_data(
        playlist_id, include_notes=not keep_notes
    )
    return {"playlist_id": playlist_id, "deleted": deleted, "kept_notes": keep_notes}


# -----------------------------------------------------------------------------
# User Settings endpoints
# -----------------------------------------------------------------------------


def _user_settings_to_response(settings: UserSettings) -> UserSettingsResponse:
    """Attach configured default note prompt for API clients (e.g. settings UI)."""
    return UserSettingsResponse(
        _id=settings.id,
        user_email=settings.user_email,
        note_prompt=settings.note_prompt,
        default_note_prompt=get_default_note_prompt(),
        regenerate_on_version_change=settings.regenerate_on_version_change,
        regenerate_on_transcript_update=settings.regenerate_on_transcript_update,
        sync_prodtrack_tab_on_version_change=(
            settings.sync_prodtrack_tab_on_version_change
        ),
        prodtrack_page_type=settings.prodtrack_page_type,
        updated_at=settings.updated_at,
        created_at=settings.created_at,
    )


def _empty_user_settings_response(user_email: str) -> UserSettingsResponse:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    default = get_default_note_prompt()
    return UserSettingsResponse(
        _id="",
        user_email=user_email,
        note_prompt="",
        default_note_prompt=default,
        regenerate_on_version_change=False,
        regenerate_on_transcript_update=False,
        sync_prodtrack_tab_on_version_change=True,
        updated_at=now,
        created_at=now,
    )


@app.get(
    "/users/{user_email}/settings",
    tags=["User Settings"],
    summary="Get user settings",
    description=(
        "Retrieve settings for a user. When the user has no saved document, "
        "returns default toggles and the configured default note prompt in "
        "`default_note_prompt`; `note_prompt` is empty until the user saves a custom prompt."
    ),
    response_model=UserSettingsResponse,
)
async def get_user_settings(
    user_email: str,
    provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> UserSettingsResponse:
    """Get user settings."""
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    stored = await provider.get_user_settings(user_email)
    if stored is None:
        return _empty_user_settings_response(user_email)
    return _user_settings_to_response(stored)


@app.put(
    "/users/{user_email}/settings",
    tags=["User Settings"],
    summary="Create or update user settings",
    description="Create or update settings for a user.",
    response_model=UserSettingsResponse,
)
async def upsert_user_settings(
    user_email: str,
    data: UserSettingsUpdate,
    provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> UserSettingsResponse:
    """Create or update user settings."""
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    updated = await provider.upsert_user_settings(user_email, data)
    return _user_settings_to_response(updated)


@app.delete(
    "/users/{user_email}/settings",
    tags=["User Settings"],
    summary="Delete user settings",
    description="Delete settings for a user.",
    response_model=bool,
)
async def delete_user_settings(
    user_email: str,
    provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> bool:
    """Delete user settings."""
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    deleted = await provider.delete_user_settings(user_email)
    if not deleted:
        raise HTTPException(status_code=404, detail="User settings not found")
    return True


@app.get(
    "/users/{user_email}/qc-checks",
    tags=["Note QC"],
    summary="List note QC checks",
    response_model=list[NoteQCCheck],
)
async def list_qc_checks(
    user_email: str,
    storage_provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> list[NoteQCCheck]:
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return await storage_provider.get_qc_checks(user_email)


@app.post(
    "/users/{user_email}/qc-checks",
    tags=["Note QC"],
    summary="Create a note QC check",
    response_model=NoteQCCheck,
    status_code=201,
)
async def create_qc_check(
    user_email: str,
    data: NoteQCCheckCreate,
    storage_provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> NoteQCCheck:
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return await storage_provider.create_qc_check(user_email, data)


@app.put(
    "/users/{user_email}/qc-checks/{check_id}",
    tags=["Note QC"],
    summary="Update a note QC check",
    response_model=NoteQCCheck,
)
async def update_qc_check(
    user_email: str,
    check_id: str,
    data: NoteQCCheckUpdate,
    storage_provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> NoteQCCheck:
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    updated = await storage_provider.update_qc_check(user_email, check_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="QC check not found")
    return updated


@app.delete(
    "/users/{user_email}/qc-checks/{check_id}",
    tags=["Note QC"],
    summary="Delete a note QC check",
    status_code=204,
)
async def delete_qc_check(
    user_email: str,
    check_id: str,
    storage_provider: StorageProviderDep,
    current_user: CurrentUserDep,
) -> None:
    if not emails_match(user_email, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    deleted = await storage_provider.delete_qc_check(user_email, check_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="QC check not found")


@app.post(
    "/playlists/{playlist_id}/versions/{version_id}/run-qc-checks",
    tags=["Note QC"],
    summary="Run note QC checks for a draft",
    response_model=RunQCChecksResponse,
)
async def run_qc_checks(
    playlist_id: int,
    version_id: int,
    body: RunQCChecksRequest,
    storage_provider: StorageProviderDep,
    prodtrack_provider: ProdtrackProviderDep,
    llm_provider: LLMProviderDep,
    current_user: CurrentUserDep,
) -> RunQCChecksResponse:
    # Authenticated callers may QC any draft in the playlist (same as publish-notes).
    # body.user_email identifies the draft owner, not the caller.
    draft = await storage_provider.get_draft_note(
        body.user_email, playlist_id, version_id
    )
    if draft is None:
        return RunQCChecksResponse(results=[])
    checks = await storage_provider.get_qc_checks(body.user_email)
    segments = await storage_provider.get_segments_for_version(playlist_id, version_id)
    transcript = TranscriptionProviderBase.build_transcript_text(segments)
    version = cast(
        Version,
        prodtrack_provider.get_entity("version", version_id, resolve_links=False),
    )
    results = await run_qc_checks_for_draft(
        checks=checks,
        draft=draft,
        transcript_text=transcript,
        version=version,
        prodtrack_provider=prodtrack_provider,
        llm_provider=llm_provider,
    )
    return RunQCChecksResponse(results=results)


# -----------------------------------------------------------------------------
# Transcription endpoints
# -----------------------------------------------------------------------------


@app.post(
    "/transcription/bot",
    tags=["Transcription"],
    summary="Dispatch a bot to a meeting",
    description="Start a transcription bot that joins the specified meeting.",
    response_model=BotSession,
    status_code=201,
)
async def dispatch_bot(
    request: DispatchBotRequest,
    http_request: Request,
    transcription_provider: TranscriptionProviderDep,
    storage_provider: StorageProviderDep,
    transcription_service: TranscriptionServiceDep,
    _: CurrentUserDep,
) -> BotSession:
    """Dispatch a transcription bot to a meeting."""
    dispatch_site = site_for_client(
        http_request.client.host if http_request.client else None
    )
    try:
        session = await transcription_provider.dispatch_bot(
            platform=request.platform,
            meeting_id=request.meeting_id,
            playlist_id=request.playlist_id,
            passcode=request.passcode,
            bot_name=request.bot_name,
            language=request.language,
            authenticated=request.authenticated,
            recording_enabled=request.recording_enabled,
        )

        await storage_provider.upsert_playlist_metadata(
            request.playlist_id,
            PlaylistMetadataUpdate(
                meeting_id=request.meeting_id,
                platform=request.platform.value,
                vexa_meeting_id=session.vexa_meeting_id,
                # What Vexa RESOLVED, not what was requested — and written alongside the meeting
                # id it describes. A meeting that is not being recorded switches the whole
                # recording path off for this playlist rather than leaving the collector to
                # rediscover, once every poll and forever, that there is nothing to fetch.
                recording_enabled=session.recording_enabled,
                # The side that asked for this recording owns collecting it. Its collector runs
                # beside the front end that dispatched, which is the host this request's peer
                # belongs to — so the media is archived where the player will look for it.
                collector_site=dispatch_site,
                transcription_paused=False,
                clear_resumed_at=True,
            ),
        )

        await transcription_service.subscribe_to_meeting(
            platform=request.platform.value,
            meeting_id=request.meeting_id,
            playlist_id=request.playlist_id,
        )

        # Segments are stored against the version in review. With none set, the bot joins, Vexa
        # transcribes, and DNA drops every segment on arrival — a run that looks entirely healthy
        # while keeping nothing. Say so at the one moment someone is watching.
        metadata = await storage_provider.get_playlist_metadata(request.playlist_id)
        session.saving_segments = bool(metadata and metadata.in_review is not None)
        if not session.saving_segments:
            session.warnings.append("no_version_in_review")
            logging.getLogger(__name__).warning(
                "Playlist %s: bot dispatched with no version in review — segments will be "
                "discarded until one is set",
                request.playlist_id,
            )

        event_publisher = get_event_publisher()
        await event_publisher.publish(
            EventType.BOT_STATUS_CHANGED,
            {
                "platform": request.platform.value,
                "meeting_id": request.meeting_id,
                "playlist_id": request.playlist_id,
                "status": "joining",
                "vexa_meeting_id": session.vexa_meeting_id,
                "saving_segments": session.saving_segments,
                "warnings": session.warnings,
            },
        )

        return session
    except TranscriptionUpstreamError as e:
        # Pass the transcription service's own status and message through. Flattening every
        # refusal into 400 threw away the only part anyone could act on: dispatching a second bot
        # into a meeting that already has one is a 409 with "already has an active bot", and it
        # was arriving as a 400 carrying an HTTP client's description of the status code.
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete(
    "/transcription/bot/{platform}/{meeting_id}",
    tags=["Transcription"],
    summary="Stop a transcription bot",
    description="Stop a transcription bot that is currently in a meeting.",
    response_model=bool,
)
async def stop_bot(
    platform: Platform,
    meeting_id: str,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> bool:
    """Stop a transcription bot."""
    try:
        event_publisher = get_event_publisher()
        await event_publisher.publish(
            EventType.BOT_STATUS_CHANGED,
            {
                "platform": platform.value,
                "meeting_id": meeting_id,
                "status": "stopping",
            },
        )

        return await transcription_provider.stop_bot(platform, meeting_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/transcription/bot/{platform}/{meeting_id}/status",
    tags=["Transcription"],
    summary="Get bot status",
    description="Get the current status of a transcription bot.",
    response_model=BotStatus,
)
async def get_bot_status(
    platform: Platform,
    meeting_id: str,
    transcription_provider: TranscriptionProviderDep,
    storage_provider: StorageProviderDep,
    _: CurrentUserDep,
    playlist_id: Optional[int] = None,
) -> BotStatus:
    """Get the status of a transcription bot."""
    try:
        status = await transcription_provider.get_bot_status(platform, meeting_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # A bot can be perfectly healthy while its transcript goes nowhere, so "is it working" has to
    # include whether anything is being kept.
    #
    # It is answerable only per PLAYLIST. A meeting id does not identify one — the same meeting
    # room gets reused across playlists, and whether segments are being stored is a property of
    # the playlist, not the room. Asked without `playlist_id` this stays None (unknown) rather
    # than guessing: picking an arbitrary playlist that shares the room produced a confident
    # warning about a playlist the caller was not even looking at.
    if playlist_id is not None:
        metadata = await storage_provider.get_playlist_metadata(playlist_id)
        if metadata is not None:
            status.saving_segments = metadata.in_review is not None
            if not status.saving_segments:
                status.warnings.append("no_version_in_review")
    return status


@app.get(
    "/transcription/transcript/{platform}/{meeting_id}",
    tags=["Transcription"],
    summary="Get transcript",
    description="Get the full transcript for a meeting.",
    response_model=Transcript,
)
async def get_transcript(
    platform: Platform,
    meeting_id: str,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> Transcript:
    """Get the transcript for a meeting."""
    try:
        return await transcription_provider.get_transcript(platform, meeting_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/transcription/segments/{playlist_id}/{version_id}",
    tags=["Transcription"],
    summary="Get segments for a version",
    description="Get all stored transcript segments for a specific playlist version.",
    response_model=list[StoredSegment],
)
async def get_segments_for_version(
    playlist_id: int,
    version_id: int,
    storage_provider: StorageProviderDep,
    _: CurrentUserDep,
) -> list[StoredSegment]:
    """Get all transcript segments for a version."""
    try:
        return await storage_provider.get_segments_for_version(playlist_id, version_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------------
# LLM endpoints
# -----------------------------------------------------------------------------


def _build_full_prompt(
    prompt: str,
    transcript: str,
    context: str,
    existing_notes: str,
    additional_instructions: str | None = None,
) -> str:
    """Build the full prompt with template values substituted."""
    result = prompt
    result = result.replace("{{ transcript }}", transcript)
    result = result.replace("{{transcript}}", transcript)
    result = result.replace("{{ context }}", context)
    result = result.replace("{{context}}", context)
    result = result.replace("{{ notes }}", existing_notes)
    result = result.replace("{{notes}}", existing_notes)
    if additional_instructions:
        result += f"\n\nAdditional Instructions: {additional_instructions}"
    return result


@app.post(
    "/generate-note",
    tags=["LLM"],
    summary="Generate an AI note suggestion",
    description="Generate a note suggestion using AI based on transcript and version context.",
    response_model=GenerateNoteResponse,
)
async def generate_note(
    request: GenerateNoteRequest,
    storage_provider: StorageProviderDep,
    prodtrack_provider: ProdtrackProviderDep,
    llm_provider: LLMProviderDep,
    _: CurrentUserDep,
) -> GenerateNoteResponse:
    """Generate an AI-powered note suggestion."""
    try:
        user_settings = await storage_provider.get_user_settings(request.user_email)
        prompt = (
            user_settings.note_prompt
            if user_settings and user_settings.note_prompt
            else get_default_note_prompt()
        )

        segments = await storage_provider.get_segments_for_version(
            request.playlist_id, request.version_id
        )
        transcript = TranscriptionProviderBase.build_transcript_text(segments)

        version = cast(
            Version,
            prodtrack_provider.get_entity(
                "version", request.version_id, resolve_links=False
            ),
        )
        context = ProdtrackProviderBase.build_version_context(version)

        draft_note = await storage_provider.get_draft_note(
            request.user_email, request.playlist_id, request.version_id
        )
        existing_notes = draft_note.content if draft_note else ""

        full_prompt = _build_full_prompt(
            prompt, transcript, context, existing_notes, request.additional_instructions
        )

        suggestion = await llm_provider.generate_note(
            prompt=prompt,
            transcript=transcript,
            context=context,
            existing_notes=existing_notes,
            additional_instructions=request.additional_instructions,
        )

        return GenerateNoteResponse(
            suggestion=suggestion,
            prompt=full_prompt,
            context=context,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Recording media relay (the airgap collector's read path) ─────────────────────────────────────
#
# Addressed by PLAYLIST: the collector knows playlists, and mapping one to a Vexa recording is
# DNA's job. Thin wrappers — the flow lives in dna/recording_media.py so it is coverage-measured.


@app.get(
    "/recordings/pending",
    tags=["Recordings"],
    summary="Playlists whose meeting recording has not been archived yet",
    description=(
        "One collector's work queue, newest first. A playlist appears while it has a meeting and "
        "no archive for THAT meeting — the same condition that makes its upstream copy "
        "undeletable, so the queue cannot drift out of step with the delete guard.\n\n"
        "`site` scopes the queue to the side that dispatched the meeting, so the collector "
        "running beside that front end is the one that archives it — otherwise the media lands on "
        "a host that is not the one serving playback. Omit it to get the unrouted jobs, which is "
        "the whole queue for a single-collector deployment. A named site and the unrouted set are "
        "exclusive, so no playlist is ever offered to two collectors."
    ),
)
async def list_pending_recordings(
    storage_provider: StorageProviderDep,
    _: CurrentUserDep,
    limit: int = 25,
    site: Optional[str] = None,
) -> dict:
    playlist_ids = await storage_provider.list_playlists_pending_archive(
        limit=limit, site=site
    )
    return {"playlist_ids": playlist_ids, "count": len(playlist_ids), "site": site}


@app.get(
    "/recordings/cuts/{playlist_id}",
    tags=["Recordings"],
    summary="Where each version was discussed in the meeting recording",
    description=(
        "Everything the player needs in one call: the media URL nginx serves, the recording's "
        "own start clock and WHICH anchor produced it, and per version the spans of the "
        "recording that discussed it.\n\n"
        "`status` distinguishes the several ways there can be nothing to play — `no_recording` "
        "(never recorded), `pending` (being recorded now), `archiving` (recorded, the collector "
        "has not finished), `no_segments` (recorded, but nothing was said against these "
        "versions) and `ready`. They are different situations and want different things from "
        "the viewer; collapsing them would render all four as the same blank box."
    ),
)
async def get_recording_cuts(
    playlist_id: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> dict:
    if not recording_playback_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    service = RecordingCutsService(transcription_provider, storage_provider)
    return await service.build(playlist_id)


@app.get(
    "/recordings/{playlist_id}/chunks",
    tags=["Recordings"],
    summary="List a playlist recording's parts",
    description=(
        "The per-part index for this playlist's meeting recording: seq, size and sha256 per part, "
        "plus `complete` and the recorder's start clock. Readable WHILE the meeting is still "
        "running, so a copy can be mirrored as it is produced. Pass `after` with the highest seq "
        "already held to poll for only what is new."
    ),
)
async def list_recording_chunks(
    playlist_id: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
    after: int = -1,
) -> dict:
    service = RecordingMediaService(transcription_provider, storage_provider)
    try:
        return await service.list_chunks(playlist_id, after=after)
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/recordings/{playlist_id}/chunks/{chunk_seq}",
    tags=["Recordings"],
    summary="Download one part of a playlist recording",
    description=(
        "One part's bytes, relayed verbatim. Responds with X-Chunk-Sha256 so the caller can "
        "verify the part it just received."
    ),
)
async def get_recording_chunk(
    playlist_id: int,
    chunk_seq: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> Response:
    service = RecordingMediaService(transcription_provider, storage_provider)
    try:
        data, sha256 = await service.get_chunk(playlist_id, chunk_seq)
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"X-Chunk-Sha256": sha256 or "", "X-Chunk-Seq": str(chunk_seq)},
    )


@app.get(
    "/recordings/{playlist_id}/audio",
    tags=["Recordings"],
    summary="Download a playlist recording's assembled audio master",
    description=(
        "The audio stream, whole. Unlike video it is not relayed part-by-part: it is far smaller "
        "and is wanted only at the moment the two streams are muxed. Responds with both streams' "
        "start clocks, since they do not begin together and the mux must pad by the difference."
    ),
)
async def get_recording_audio(
    playlist_id: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> Response:
    service = RecordingMediaService(transcription_provider, storage_provider)
    try:
        data, meta = await service.get_audio(playlist_id)
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=data,
        media_type="audio/webm",
        headers={
            "X-Audio-Start-Time-Utc": meta.get("start_time_utc") or "",
            "X-Video-Start-Time-Utc": meta.get("video_start_time_utc") or "",
            "X-Audio-Duration-Seconds": str(meta.get("duration_seconds") or ""),
        },
    )


@app.post(
    "/recordings/{playlist_id}/archived",
    tags=["Recordings"],
    summary="Record that the recording has been durably archived",
    description=(
        "Declare where the assembled media now lives and its sha256. This is what later permits "
        "deleting the upstream copy — deletion is refused until it is recorded."
    ),
)
async def record_recording_archive(
    playlist_id: int,
    body: RecordingArchiveRequest,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> dict:
    service = RecordingMediaService(transcription_provider, storage_provider)
    try:
        return await service.record_archive(
            playlist_id,
            body.network_path,
            body.sha256,
            recording_id=body.recording_id,
        )
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ArchiveRecordingMismatch as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        # A path that is not relative to the share root. Refused rather than normalised: the
        # value becomes a URL, and guessing what a malformed one meant is how a player ends up
        # pointed outside the share.
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/recordings/{playlist_id}/archive-path",
    tags=["Recordings"],
    summary="Where this playlist's recording should be archived, and what to call it",
    description=(
        "The path RELATIVE to the share root that the collector should write this recording to: "
        "`<show>/lib.recording/pix/ref/dna/<YYYYMMDD>/<playlist code>_<start>_Recording.mp4`.\n\n"
        "Answered here rather than decided by the collector because the two facts the name is "
        "built from — the show the playlist belongs to and what the playlist is called — live in "
        "the tracking system, which the airgapped side cannot reach. The date directory and the "
        "timestamp are the MEETING's, in studio-local time, so the answer does not change when "
        "the collector restarts.\n\n"
        "`suffix` is for the one case the collector cannot resolve alone: a destination that "
        "already exists. Rather than overwrite a file that may be the only copy of a meeting, it "
        "asks again with a distinguishing suffix.\n\n"
        "409 when the name cannot be worked out — no show, no playlist name, no start clock. "
        "That is a retryable state, not a verdict: nothing has been archived or deleted."
    ),
)
async def get_recording_archive_path(
    playlist_id: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    prodtrack_provider: ProdtrackProviderDep,
    _: CurrentUserDep,
    suffix: str = "",
) -> dict:
    service = ArchiveDestinationService(
        prodtrack_provider,
        RecordingMediaService(transcription_provider, storage_provider),
    )
    try:
        return await service.relative_path(playlist_id, suffix=suffix)
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ArchiveDestinationUnknown as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post(
    "/recordings/{playlist_id}/blocked",
    tags=["Recordings"],
    summary="Report that this recording cannot be archived without someone acting",
    description=(
        "For the failures a retry will never clear on its own — today, a show whose recording "
        "directory does not exist on the share. The reason is held against the playlist and "
        "shown in the player, which otherwise repeats 'still being collected' forever: true, and "
        "indistinguishable from a slow collection.\n\n"
        "Not for ordinary transient failures. The collector retries every pass, so a reason that "
        "appears and clears on its own would flicker in front of a viewer who can do nothing "
        "with it either way. Cleared automatically when an archive is recorded."
    ),
)
async def report_recording_blocked(
    playlist_id: int,
    body: RecordingBlockedRequest,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> dict:
    service = RecordingMediaService(transcription_provider, storage_provider)
    return await service.report_blocked(playlist_id, body.reason)


def _poster_max_bytes() -> int:
    """The cap on one poster. A 320×180 JPEG is ~30 kB; half a megabyte is a wide margin around
    that and still small enough that a wrong caller cannot fill the database with it."""
    try:
        return int(os.getenv("RECORDING_POSTER_MAX_BYTES", 512 * 1024))
    except ValueError:
        return 512 * 1024


@app.post(
    "/recordings/{playlist_id}/posters/{version_id}",
    tags=["Recordings"],
    summary="Store one shot's poster frame from the meeting recording",
    description=(
        "A JPEG still of the moment this version came up in the meeting, posted by the collector "
        "after it has archived the recording. The body is the image itself; `filename` names the "
        "copy the collector left on the share.\n\n"
        "DNA keeps no copy of the recording, and keeps these on purpose. The notes email is "
        "composed here and EMBEDS the thumbnail in the message, because a mail client fetching "
        "an image from the share only works from inside the network — Gmail's web client asks a "
        "Google proxy to fetch it, and that proxy cannot reach an internal host. A few tens of "
        "kB per shot is what makes the picture arrive."
    ),
)
async def upload_recording_poster(
    playlist_id: int,
    version_id: int,
    request: Request,
    storage_provider: StorageProviderDep,
    _: CurrentUserDep,
    filename: Optional[str] = None,
) -> dict:
    image = await request.body()
    if not image:
        raise HTTPException(status_code=400, detail="Empty poster body")
    limit = _poster_max_bytes()
    if len(image) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Poster is {len(image)} bytes; the limit is {limit}",
        )

    # The recording it is a still OF is not the caller's to assert: the archive that was just
    # recorded names it, so it is read from there. A poster that outlived its meeting is then
    # visible as one, rather than looking current.
    metadata = await storage_provider.get_playlist_metadata(playlist_id)
    poster = await storage_provider.upsert_recording_poster(
        playlist_id,
        version_id,
        image,
        content_type=request.headers.get("content-type") or "image/jpeg",
        filename=filename,
        recording_id=metadata.archived_recording_id if metadata else None,
    )
    return {
        "playlist_id": playlist_id,
        "version_id": version_id,
        "filename": poster.filename,
        "bytes": len(image),
    }


@app.delete(
    "/recordings/{playlist_id}",
    tags=["Recordings"],
    summary="Purge the upstream copy of a playlist's recording",
    description=(
        "Deletes the recording from Vexa, leaving the meeting and its transcript. REFUSED with "
        "409 unless an archive has been recorded first — the archived copy is the only other one."
    ),
)
async def delete_recording_upstream(
    playlist_id: int,
    storage_provider: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> dict:
    service = RecordingMediaService(transcription_provider, storage_provider)
    try:
        return await service.delete_upstream(playlist_id)
    except RecordingNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ArchiveNotConfirmed as e:
        raise HTTPException(status_code=409, detail=str(e))


# -----------------------------------------------------------------------------
# Artist review page
# -----------------------------------------------------------------------------


@app.get(
    "/review/resolve/{project_slug}/{playlist_slug}",
    tags=["Review"],
    summary="Resolve a name-shaped review address to a playlist",
    description=(
        "Turns `/review/<project>/<playlist>` into a playlist id. Playlist names are not unique "
        '— a show runs "Dailies" every day it screens one — so this never guesses: an '
        "unambiguous name answers with `playlist_id` set, and a reused one answers with "
        "`playlist_id` null and every candidate in `matches`, newest first, for the page to "
        "offer. 404 means no playlist of that name exists in a project this user can see."
    ),
    response_model=ReviewResolution,
)
async def resolve_review_address(
    project_slug: str,
    playlist_slug: str,
    prodtrack: ProdtrackProviderDep,
    current_user_email: CurrentUserDep,
) -> ReviewResolution:
    try:
        return resolve_playlist(
            prodtrack, current_user_email, project_slug, playlist_slug
        )
    except ReviewPlaylistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/review/link/{playlist_id}",
    tags=["Review"],
    summary="Where a playlist's artist page is, and the fragment for each shot",
    description=(
        "The address only — no notes, no transcript, no cut list. It is what the reviewing tool "
        'needs to offer "open the artist view" beside its production-tracking button, and it '
        "is asked for rather than worked out in the browser because the page, the notes email "
        "and that button must agree on every slug. A second implementation in TypeScript would "
        "agree right up until one of them changed.\n\n"
        "Every shot's anchor comes back at once, so walking the playlist's versions does not "
        "re-ask: the answer is about the playlist, not the version being looked at."
    ),
    response_model=ReviewLink,
)
async def get_review_link(
    playlist_id: int,
    prodtrack: ProdtrackProviderDep,
    _: CurrentUserDep,
) -> ReviewLink:
    return build_review_link(playlist_id, prodtrack)


@app.get(
    "/review/playlists/{playlist_id}",
    tags=["Review"],
    summary="The artist-facing view of one playlist",
    description=(
        "Every shot in the playlist with the notes people wrote about it, the transcript filed "
        "against it, and the spans of the meeting recording that discussed it — in one response. "
        "Read-only, and assembled server-side because the page shows the whole playlist at once: "
        "asking per shot would be four requests apiece.\n\n"
        "Notes are the ones written in DNA, from every author. The empty note ShotGrid seeds "
        "against each version when a playlist is created is excluded, and so is the notes "
        "email's filter to whoever pressed send — an artist is not the sender."
    ),
    response_model=ReviewPlaylist,
)
async def get_review_playlist(
    playlist_id: int,
    prodtrack: ProdtrackProviderDep,
    storage: StorageProviderDep,
    transcription_provider: TranscriptionProviderDep,
    _: CurrentUserDep,
) -> ReviewPlaylist:
    try:
        return await build_review_playlist(
            playlist_id, prodtrack, storage, transcription_provider
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
