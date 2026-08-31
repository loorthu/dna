#!/bin/bash
# Wipe DNA's record of one playlist -- this host's recordings AND the backend's database --
# so an end-to-end test can be re-run from scratch.
#
# Built for the air-gapped recording host: the ONLY thing it needs of the backend is the
# HTTP API on one port. No SSH, no database ports, no shell on the other side. It therefore
# also works unchanged from the backend box itself (BACKEND_URL=http://localhost:8000).
#
# *** THIS SCRIPT NEVER TOUCHES SHOTGRID. ***
# It calls DNA's API and deletes local files. Notes and versions in ShotGrid are production
# data that DNA only mirrors; deleting the local mirror is safe, deleting the ShotGrid side
# is not, and is not offered here.
#
# REQUIREMENT: the backend must run with DNA_ENABLE_PLAYLIST_RESET=true, which turns on
# DELETE /playlists/{id}/data. It is off by default, so a deployment that has not opted in
# answers 404 and this script stops with an explanation.
#
# NO DATABASE BACKUP IS POSSIBLE FROM HERE. Over the API there is no way to dump Mongo, so
# the backend half of this reset is irreversible from the recording host. If you want a
# safety copy, take it on the backend box (docker exec dna-mongo mongodump ...) first.
#
# Usage:
#   ./reset-playlist-data.sh <playlist_id>                  # local recordings + backend data
#   ./reset-playlist-data.sh <playlist_id> --dry-run        # survey only, change nothing
#   ./reset-playlist-data.sh <playlist_id> --keep-notes     # spare draft notes
#   ./reset-playlist-data.sh <playlist_id> --purge-upstream # also drop Vexa's copy of the media
#   ./reset-playlist-data.sh <playlist_id> --yes            # skip the confirmation prompt
#
# What it CANNOT do from an air-gapped host: purge Vexa's Postgres/MinIO wholesale. Those
# listen on the backend's loopback. --purge-upstream uses the API's per-playlist endpoint,
# which is the only part reachable over the link.

set -euo pipefail

# --- Configuration (override via environment) ---

# Nothing below needs setting by hand on a host that runs a collector: the deployment
# already states all of it, and re-typing it here is how a reset ends up pointed at a
# different share or backend than the collector it is meant to match. Values are
# DISCOVERED from the running collector container, then from docker/airgap/.env.
# An explicit environment variable always wins.
COLLECTOR_CONTAINER="${COLLECTOR_CONTAINER:-dna-collector}"
ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)/docker/airgap/.env}"
CURL_OPTS="${CURL_OPTS:---max-time 30}"

BACKEND_URL="${BACKEND_URL:-}"
RECORDINGS_DIR="${RECORDINGS_DIR:-}"
STAGING_VOLUME="${STAGING_VOLUME:-}"
COLLECTOR_SITE="${COLLECTOR_SITE:-}"
declare -A SOURCE=()
# Remember what the caller set before discovery runs, so the banner can say so.
for _v in BACKEND_URL RECORDINGS_DIR STAGING_VOLUME COLLECTOR_SITE; do
  [ -n "${!_v}" ] && SOURCE[$_v]="environment"
done

_coll_env() {  # value of one env var inside the collector container
  docker inspect "$COLLECTOR_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | sed -n "s/^$1=//p" | head -1
}
_env_file() { # value of one key in the deployment's .env
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -1 | sed 's/[[:space:]]*$//'
}
_set() {      # _set VAR value origin -- only when VAR is still empty
  local var="$1" val="$2" origin="$3"
  [ -n "$val" ] || return 0
  [ -z "${!var}" ] || return 0
  printf -v "$var" '%s' "$val"
  SOURCE[$var]="$origin"
}

if docker inspect "$COLLECTOR_CONTAINER" >/dev/null 2>&1; then
  _set BACKEND_URL     "$(_coll_env DNA_API_URL)"             "collector $COLLECTOR_CONTAINER"
  _set RECORDINGS_DIR  "$(_coll_env RECORDING_NETWORK_PATH)"  "collector $COLLECTOR_CONTAINER"
  _set COLLECTOR_SITE  "$(_coll_env COLLECTOR_SITE)"          "collector $COLLECTOR_CONTAINER"
  # The staging volume is whatever is mounted at the collector's own staging dir --
  # its name is project-prefixed by compose, so it must be read, never assumed.
  STAGING_DIR_IN="$(_coll_env COLLECTOR_STAGING_DIR)"; STAGING_DIR_IN="${STAGING_DIR_IN:-/staging}"
  _set STAGING_VOLUME "$(docker inspect "$COLLECTOR_CONTAINER" \
      --format "{{range .Mounts}}{{if eq .Destination \"$STAGING_DIR_IN\"}}{{.Name}}{{end}}{{end}}" 2>/dev/null)" \
      "collector $COLLECTOR_CONTAINER"
fi

_set BACKEND_URL    "$(_env_file BACKEND_URL)"            "$ENV_FILE"
_set RECORDINGS_DIR "$(_env_file RECORDING_NETWORK_PATH)" "$ENV_FILE"
_set COLLECTOR_SITE "$(_env_file COLLECTOR_SITE)"         "$ENV_FILE"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
: "${SOURCE[BACKEND_URL]:=fallback default}"

# --- Arguments ---

PLAYLIST=""
DRY_RUN=0; KEEP_NOTES=0; PURGE_UPSTREAM=0; ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=1 ;;
    --keep-notes)     KEEP_NOTES=1 ;;
    --purge-upstream) PURGE_UPSTREAM=1 ;;
    --yes|-y)         ASSUME_YES=1 ;;
    -h|--help)        sed -n '2,32p' "$0"; exit 0 ;;
    -*)               echo "Unknown option: $arg" >&2; exit 2 ;;
    *)
      if [ -n "$PLAYLIST" ]; then echo "Unexpected argument: $arg" >&2; exit 2; fi
      PLAYLIST="$arg" ;;
  esac
done

if ! [[ "$PLAYLIST" =~ ^[0-9]+$ ]]; then
  echo "Usage: $(basename "$0") <playlist_id> [--dry-run] [--keep-notes] [--purge-upstream] [--yes]" >&2
  echo "A numeric playlist id is required -- this script never guesses which playlist to wipe." >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 2; }

# api <METHOD> <PATH> -> sets $API_STATUS and $API_BODY.
# Deliberately NOT returning the body on stdout: callers would then write `x=$(api ...)`,
# which runs this in a subshell and silently discards the status, so a 404 reads as
# whatever the previous call left behind. That mistake deleted local files while the
# backend kept its data, so the status is only ever set in the caller's own shell.
API_STATUS=""
API_BODY=""
api() {
  local tmp
  tmp=$(mktemp)
  # No `|| echo 000`: on a connection failure curl ALSO writes 000 via -w, and the two
  # concatenate into "000000", which matches no case below.
  API_STATUS=$(curl -s $CURL_OPTS -X "$1" -o "$tmp" -w '%{http_code}' "$BACKEND_URL$2" 2>/dev/null) || true
  [ -n "$API_STATUS" ] || API_STATUS="000"
  API_BODY=$(cat "$tmp")
  rm -f "$tmp"
}

# --- Preflight: is the backend actually there? ---

api GET /health
if [ "$API_STATUS" != "200" ]; then
  cat >&2 <<MSG
Backend not reachable at $BACKEND_URL (HTTP $API_STATUS).

  That address came from: ${SOURCE[BACKEND_URL]:-environment}

  If it names a container (e.g. http://dna-backend:8000), it is resolvable only on the
  compose network -- which is correct for the collector but not from a host shell. On the
  backend box itself use http://localhost:8000; from the recording host use the address
  in docker/airgap/.env, which is already the real one.

      BACKEND_URL=http://<backend-host>:8000 $(basename "$0") $PLAYLIST

  Nothing has been deleted.
MSG
  exit 3
fi

echo "==> Reset playlist $PLAYLIST"
echo "    backend:    $BACKEND_URL   (HTTP only -- no ssh, no database ports)"
echo "                from ${SOURCE[BACKEND_URL]:-environment}"
echo "    recordings: ${RECORDINGS_DIR:-<unset>}"
echo "                from ${SOURCE[RECORDINGS_DIR]:-environment}"
echo "    staging:    ${STAGING_VOLUME:-<none found>}"
echo "                from ${SOURCE[STAGING_VOLUME]:-environment}"
if [ -z "$RECORDINGS_DIR" ]; then
  echo >&2
  echo "No recordings directory discovered: no '$COLLECTOR_CONTAINER' container here and no" >&2
  echo "RECORDING_NETWORK_PATH in $ENV_FILE. Set RECORDINGS_DIR, or run where the collector is." >&2
  exit 3
fi
echo

# --- Survey ---
# Only /playlists/{id}/metadata is read, which is answered from DNA's own store. The
# draft-notes endpoint is deliberately NOT called: reading it runs the ShotGrid sync, which
# would re-create the very note mirrors we are about to delete.

api GET "/playlists/$PLAYLIST/metadata"
META="$API_BODY"
ARCHIVE_NAME="-"; ARCHIVE_SITE="-"
if [ "$API_STATUS" = "200" ]; then
  ARCHIVE_NAME=$(printf '%s' "$META" | grep -o '"recording_network_path":"[^"]*"' | cut -d'"' -f4 || true)
  ARCHIVE_SITE=$(printf '%s' "$META" | grep -o '"collector_site":"[^"]*"' | cut -d'"' -f4 || true)
  [ -n "$ARCHIVE_NAME" ] || ARCHIVE_NAME="-"
  [ -n "$ARCHIVE_SITE" ] || ARCHIVE_SITE="-"
fi

mapfile -t MEDIA < <(find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "playlist-${PLAYLIST}-*" 2>/dev/null | sort)
STAGED=0
if docker volume inspect "$STAGING_VOLUME" >/dev/null 2>&1; then
  # Use the collector's OWN image: on an air-gapped host there may be no other image to pull.
  HELPER=$(docker inspect -f '{{.Config.Image}}' "$COLLECTOR_CONTAINER" 2>/dev/null || echo "")
  # ...as the collector's OWN uid. /staging is sticky (drwxrwxrwt), so only the owner of a
  # state file may unlink it, and the image's default user is not necessarily the one the
  # deployment runs as (COLLECTOR_UID/GID override it). Running as the image default made
  # the rm fail silently while this script still reported the files as deleted.
  HELPER_USER=$(docker inspect -f '{{.Config.User}}' "$COLLECTOR_CONTAINER" 2>/dev/null || echo "")
  HELPER_AS=(); [ -n "$HELPER_USER" ] && HELPER_AS=(--user "$HELPER_USER")
  if [ -n "$HELPER" ]; then
    STAGED=$(docker run --rm "${HELPER_AS[@]}" -v "$STAGING_VOLUME":/staging "$HELPER" \
               sh -c "ls /staging/${PLAYLIST}-*.state.json 2>/dev/null | wc -l" 2>/dev/null || echo 0)
  fi
fi

echo "  THIS HOST ($(hostname -s))"
printf '    %-28s %s\n' "recordings" "${#MEDIA[@]}   ($RECORDINGS_DIR)"
for f in "${MEDIA[@]}"; do printf '        %s\n' "$(basename "$f")"; done
printf '    %-28s %s\n' "staging state" "$STAGED"
[ -d "$RECORDINGS_DIR" ] || echo "    !! $RECORDINGS_DIR does not exist -- set RECORDINGS_DIR to the real share"

echo
echo "  BACKEND (via API)"
if [ "$ARCHIVE_NAME" != "-" ]; then
  printf '    %-28s %s\n' "archive recorded as" "$ARCHIVE_NAME (site '$ARCHIVE_SITE')"
  if [ ! -f "$RECORDINGS_DIR/$(basename "$ARCHIVE_NAME")" ]; then
    echo "    !! that file is NOT on this host -- it was archived by the '$ARCHIVE_SITE' collector."
    echo "       Clearing the backend record here orphans it; run this script on that host too."
  fi
else
  printf '    %-28s %s\n' "playlist metadata" "none stored"
fi
echo "    segments + metadata + draft notes will be cleared by DELETE /playlists/$PLAYLIST/data"
[ "$KEEP_NOTES" -eq 1 ] && echo "    (draft notes KEPT: --keep-notes)"
[ "$PURGE_UPSTREAM" -eq 1 ] && echo "    Vexa's own copy of the media will be dropped too (--purge-upstream)"
echo "    counts are reported by that call; there is no way to preview them over the API"

echo
echo "  ShotGrid: NOT TOUCHED. This script makes no ShotGrid calls."
echo "  No database backup is possible over the API -- the backend half is irreversible."

if [ "$DRY_RUN" -eq 1 ]; then
  echo; echo "==> --dry-run: nothing was changed."; exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  read -r -p "Delete the above for playlist $PLAYLIST? [y/N] " reply
  case "$reply" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted."; exit 1 ;; esac
fi

# --- Stop the local collector so it cannot re-poll mid-delete ---

COLL_UP=0
if [ -n "$(docker ps -q -f name="^${COLLECTOR_CONTAINER}$" 2>/dev/null)" ]; then
  COLL_UP=1; echo; echo "==> Stopping $COLLECTOR_CONTAINER"
  docker stop "$COLLECTOR_CONTAINER" >/dev/null
fi

# --- Backend first: if it fails, stop with the local files still intact ---

echo; echo "==> Backend"

if [ "$PURGE_UPSTREAM" -eq 1 ]; then
  api DELETE "/recordings/$PLAYLIST"; BODY="$API_BODY"
  case "$API_STATUS" in
    200) echo "    upstream media  dropped" ;;
    404) echo "    upstream media  none to drop" ;;
    409) echo "    upstream media  REFUSED (409): no archive recorded, so this is the only copy" ;;
    *)   echo "    upstream media  unexpected HTTP $API_STATUS: $BODY" ;;
  esac
fi

QS=""; [ "$KEEP_NOTES" -eq 1 ] && QS="?keep_notes=true"
api DELETE "/playlists/$PLAYLIST/data$QS"; BODY="$API_BODY"
case "$API_STATUS" in
  200) echo "    reset           $BODY" ;;
  404)
    [ "$COLL_UP" -eq 1 ] && docker start "$COLLECTOR_CONTAINER" >/dev/null
    cat >&2 <<MSG

DELETE /playlists/$PLAYLIST/data returned 404.

  The endpoint is off unless the backend runs with DNA_ENABLE_PLAYLIST_RESET=true.
  (A wrong BACKEND_URL would have failed the health check, so this is almost certainly
  the flag.) Nothing was deleted on either side; the collector has been restarted.
MSG
    exit 4 ;;
  *)
    [ "$COLL_UP" -eq 1 ] && docker start "$COLLECTOR_CONTAINER" >/dev/null
    echo >&2; echo "Backend reset failed (HTTP $API_STATUS): $BODY" >&2
    echo "Nothing was deleted on this host either; the collector has been restarted." >&2
    exit 5 ;;
esac

# --- Then this host's files ---

echo
echo "==> This host"
find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "playlist-${PLAYLIST}-*" -delete 2>/dev/null || true
echo "    recordings      ${#MEDIA[@]} deleted"
STAGED_LEFT="$STAGED"
if [ -n "${HELPER:-}" ]; then
  docker run --rm "${HELPER_AS[@]}" -v "$STAGING_VOLUME":/staging "$HELPER" \
    sh -c "rm -f /staging/${PLAYLIST}-*.state.json" >/dev/null 2>&1 || true
  # Count again rather than trusting the rm: it runs in another container, as another user,
  # against a sticky directory, and every one of those can refuse without saying so.
  STAGED_LEFT=$(docker run --rm "${HELPER_AS[@]}" -v "$STAGING_VOLUME":/staging "$HELPER" \
                  sh -c "ls /staging/${PLAYLIST}-*.state.json 2>/dev/null | wc -l" 2>/dev/null || echo "?")
fi
if [ "$STAGED_LEFT" = "0" ]; then
  echo "    staging state   $STAGED deleted"
else
  echo "    staging state   !! $STAGED_LEFT of $STAGED could NOT be deleted"
  echo "                    /staging is sticky; these belong to another uid than ${HELPER_USER:-the image default}."
fi

[ "$COLL_UP" -eq 1 ] && { echo; echo "==> Restarting $COLLECTOR_CONTAINER"; docker start "$COLLECTOR_CONTAINER" >/dev/null; }

# --- Verify ---

echo; echo "==> Verify"
api GET "/playlists/$PLAYLIST/metadata"
# The endpoint is Optional[PlaylistMetadata]: absent metadata is 200 with a body of `null`,
# not a 404, so the body is what says whether anything is left.
if [ "$API_STATUS" = "404" ] || [ -z "$API_BODY" ] || [ "$API_BODY" = "null" ]; then
  echo "    backend metadata  gone"
else
  echo "    backend metadata  STILL PRESENT (HTTP $API_STATUS): $API_BODY"
fi
echo "    recordings here   $(find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "playlist-${PLAYLIST}-*" 2>/dev/null | wc -l) left"
SITE="$ARCHIVE_SITE"; [ "$SITE" = "-" ] && SITE=""
api GET "/recordings/pending?limit=25&site=$SITE"
echo "    pending queue     $API_BODY  (site='$SITE')"

echo; echo "==> Done. ShotGrid was not contacted."
