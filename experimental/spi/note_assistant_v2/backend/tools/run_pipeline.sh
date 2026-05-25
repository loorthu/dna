#!/usr/bin/env bash
# Process a Google Meet recording against a ShotGrid playlist.
#
# Usage:
#   ./run_pipeline.sh <gdrive_url> <sg_playlist_url> [options]
#
# Required:
#   gdrive_url        Google Drive URL of the recording
#   sg_playlist_url   ShotGrid playlist URL or ID
#
# Options:
#   --project NAME        Project name slug (default: zorr)
#   --subject TEXT        Email subject (default: "<PROJECT> Dailies YYYY-MM-DD")
#   --recipient EMAIL     Recipient email (default: EMAIL_SENDER from .env)
#   --model MODEL         LLM model (default: gemini-2.5-pro)
#   --version-pattern PAT Regex for version detection (default: <project>-(\d+))
#
# Examples:
#   ./run_pipeline.sh \
#     "https://drive.google.com/file/d/ABC123/view" \
#     "https://spi.shotgrid.autodesk.com/page/60800#Playlist_436533"
#
#   ./run_pipeline.sh \
#     "https://drive.google.com/file/d/ABC123/view" \
#     "https://spi.shotgrid.autodesk.com/page/60800#Playlist_436533" \
#     --project kpop \
#     --subject "KPOP Dailies 05-18-26"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/.."
# Locate python: prefer the repo venv (5 levels up from tools/), fall back to system python3
_VENV_PYTHON="${SCRIPT_DIR}/../../../../../.venv/bin/python3"
if [[ -x "$_VENV_PYTHON" ]]; then
    PYTHON="$_VENV_PYTHON"
else
    PYTHON="$(command -v python3)"
fi

# ---------------------------------------------------------------------------
# Parse positional args
# ---------------------------------------------------------------------------
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <gdrive_url> <sg_playlist_url> [--project NAME] [--subject TEXT] [--recipient EMAIL] [--model MODEL] [--version-pattern PAT]" >&2
    exit 1
fi

GDRIVE_URL="$1"
SG_PLAYLIST_URL="$2"
shift 2

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT="zorr"
SUBJECT=""
RECIPIENT=""
MODEL="gemini-2.5-pro"
VERSION_PATTERN=""
GMEET_AND_SG_CSV=""

# ---------------------------------------------------------------------------
# Parse optional flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)          PROJECT="$2";          shift 2 ;;
        --subject)          SUBJECT="$2";          shift 2 ;;
        --recipient)        RECIPIENT="$2";        shift 2 ;;
        --model)            MODEL="$2";            shift 2 ;;
        --version-pattern)  VERSION_PATTERN="$2";  shift 2 ;;
        --gmeet-and-sg-csv) GMEET_AND_SG_CSV="$2"; shift 2 ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Load specific vars from .env (full source is unsafe due to unquoted values)
# ---------------------------------------------------------------------------
ENV_FILE="${BACKEND_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    _read_env() { grep "^${1}=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
    EMAIL_SENDER="$(_read_env EMAIL_SENDER)"
    GMEET_THUMBNAIL_URL="$(_read_env GMEET_THUMBNAIL_URL)"
fi

# ---------------------------------------------------------------------------
# Derive defaults that depend on project name or .env values
# ---------------------------------------------------------------------------
PROJECT_UPPER="${PROJECT^^}"  # uppercase for display

if [[ -z "$SUBJECT" ]]; then
    SUBJECT="${PROJECT_UPPER} Dailies $(date +%m-%d-%y)"
fi

if [[ -z "$RECIPIENT" ]]; then
    RECIPIENT="${EMAIL_SENDER:-}"
    if [[ -z "$RECIPIENT" ]]; then
        echo "Error: no recipient email. Set EMAIL_SENDER in .env or pass --recipient." >&2
        exit 1
    fi
fi

if [[ -z "$VERSION_PATTERN" ]]; then
    VERSION_PATTERN="${PROJECT}-(\d+)"
fi

# Expand {project} placeholder in GMEET_THUMBNAIL_URL if set
THUMBNAIL_URL="${GMEET_THUMBNAIL_URL:-}"
if [[ -n "$THUMBNAIL_URL" ]]; then
    THUMBNAIL_URL="${THUMBNAIL_URL//\{project\}/${PROJECT}}"
fi

# ---------------------------------------------------------------------------
# Set up logging
# ---------------------------------------------------------------------------
mkdir -p "${BACKEND_DIR}/logs"
LOG="${BACKEND_DIR}/logs/${PROJECT}_$(date +%Y%m%d_%H%M%S).log"

# ---------------------------------------------------------------------------
# Build and launch the command
# ---------------------------------------------------------------------------
CMD=(
    "$PYTHON" -u
    "${SCRIPT_DIR}/process_gmeet_recording.py"
    "$GDRIVE_URL"
    "$SG_PLAYLIST_URL"
    "$RECIPIENT"
    --version-pattern "$VERSION_PATTERN"
    --version-column jts
    --model "$MODEL"
    --email-subject "$SUBJECT"
    --drive-url "$GDRIVE_URL"
    --output "${BACKEND_DIR}/media"
    --project "$PROJECT"
    --verbose
)

if [[ -n "$THUMBNAIL_URL" ]]; then
    CMD+=(--thumbnail-url "$THUMBNAIL_URL")
fi

if [[ -n "$GMEET_AND_SG_CSV" ]]; then
    CMD+=(--combined-csv "$GMEET_AND_SG_CSV")
fi

echo "========================================"
echo "  Project:    $PROJECT"
echo "  Subject:    $SUBJECT"
echo "  Recipient:  $RECIPIENT"
echo "  Model:      $MODEL"
echo "  Recording:  $GDRIVE_URL"
echo "  SG Playlist: $SG_PLAYLIST_URL"
echo "  Log:        $LOG"
echo "========================================"
echo ""

PYTHONUNBUFFERED=1 "${CMD[@]}" 2>&1 | tee "$LOG"
