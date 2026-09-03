#!/bin/bash
# Run a built image locally, the way the cluster will run it, before pushing.
# Usage: ./docker/airgap/oc-run.sh {ui|collector}
#
# The point is the UID. OpenShift assigns an arbitrary, high, non-root uid per namespace, and both
# images behave differently under one: nginx cannot write /var/run or /var/cache, and the
# collector's startup probe checks it can write what it is about to be trusted with. Running as
# 1000710000 here is what turns "it worked on my machine" into a test of the thing that will
# actually happen.
#
#   HOST_PORT=8090   host port for the ui (default 8090)
#   RUN_UID=...      override the simulated uid
set -euo pipefail

DOCKER="${DOCKER:-docker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"

oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector}" >&2; exit 1; }
oc_load_env "$SCRIPT_DIR" "$REPO_ROOT"

VERSION="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
RUN_UID="${RUN_UID:-1000710000}"
HOST_PORT="${HOST_PORT:-8090}"
NAME="dna-${APP}-octest"
BASE="${APP_BASE_PATH:-}"

$DOCKER rm -f "$NAME" >/dev/null 2>&1 || true

if [ "$APP" = "ui" ]; then
    $DOCKER run -d --name "$NAME" -p "${HOST_PORT}:8080" --user "${RUN_UID}:0" \
        -e APP_BASE_PATH="$BASE" \
        -e BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:9}" \
        -e REVIEW_SESSIONS_URL="${REVIEW_SESSIONS_URL:-http://127.0.0.1:9}" \
        -e RECORDING_NETWORK_PATH="${RECORDING_NETWORK_PATH:-/shots}" \
        ${NGINX_UID:+-e NGINX_UID="$NGINX_UID"} \
        ${NGINX_SHARE_GID:+-e NGINX_SHARE_GID="$NGINX_SHARE_GID"} \
        "${IMAGE}:${VERSION}"

    sleep 2
    echo
    echo "Running as uid ${RUN_UID} on http://localhost:${HOST_PORT}${BASE}/"
    echo
    for path in "${BASE}/healthz" "${BASE}/" "${BASE}/review/id/1"; do
        printf '  %-28s %s\n' "$path" \
            "$($DOCKER run --rm --network host curlimages/curl:latest -s -o /dev/null -w '%{http_code}' \
                "http://localhost:${HOST_PORT}${path}" 2>/dev/null || \
               curl -s -o /dev/null -w '%{http_code}' "http://localhost:${HOST_PORT}${path}")"
    done
    echo
    echo "  Expect 200 for all three. The startup log should show envsubst writing to /tmp and"
    echo "  25-require-rendered-config.sh passing; anything else means the config was not rendered."
    echo
    echo "  Logs:  docker logs -f ${NAME}"
    echo "  Stop:  docker rm -f ${NAME}"
else
    echo "Running the collector as uid ${RUN_UID} against ${BACKEND_URL:-<unset>}."
    echo "It should log the writability probe on BOTH mounts and then poll; if it exits, the"
    echo "message names which directory it could not write, which is the point of that probe."
    echo
    $DOCKER run --rm --name "$NAME" --user "${RUN_UID}:0" \
        -e DNA_API_URL="${BACKEND_URL:-http://127.0.0.1:9}" \
        -e DNA_API_TOKEN="${DNA_API_TOKEN:-}" \
        -e COLLECTOR_STAGING_DIR=/staging \
        -e RECORDING_NETWORK_PATH="${RECORDING_NETWORK_PATH:-/shots}" \
        ${RECORDING_ARCHIVE_DIR:+-e RECORDING_ARCHIVE_DIR="$RECORDING_ARCHIVE_DIR"} \
        -e COLLECTOR_POLL_SECONDS="${COLLECTOR_POLL_SECONDS:-10}" \
        -v "dna-octest-staging:/staging" \
        -v "dna-octest-shots:${RECORDING_NETWORK_PATH:-/shots}" \
        "${IMAGE}:${VERSION}"
fi
