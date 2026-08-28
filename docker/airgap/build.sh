#!/usr/bin/env bash
# Build the DNA FRONTEND image (nginx serving the SPA + reverse-proxy).
# The backend + mongo run on ANOTHER host (with internet) — not built here.
#
# Build args come from docker/airgap/.env:
#   - NPM_REGISTRY -> internal Artifactory for building on the air-gapped host
#     (leave empty to build on an internet-connected machine for transfer).
#   - VITE_* are baked into the static bundle (VITE_API_BASE_URL=/api is relative).
#
# Usage:  ./docker/airgap/build.sh
# Next:   ./docker/airgap/up.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_ENV="$REPO_ROOT/frontend/packages/app/.env"

[ -f "$SCRIPT_DIR/.env" ] || {
    echo "Error: $SCRIPT_DIR/.env not found. cp .env.example .env and fill it in." >&2; exit 1; }
[ -f "$APP_ENV" ] || {
    echo "Error: $APP_ENV not found." >&2
    echo "       It is the upstream home for VITE_*; create it with:" >&2
    echo "         cp frontend/packages/app/.env.example frontend/packages/app/.env" >&2; exit 1; }

# Layered, upstream first: the app's own .env supplies every VITE_* (so a new one
# added upstream needs no change here), and docker/airgap/.env then overrides the
# handful whose deployed value differs. Compose takes the LAST definition of a
# repeated key, so order matters.
echo "==> Building DNA frontend via compose..."
echo "    VITE_* from : $APP_ENV"
echo "    overrides   : $SCRIPT_DIR/.env"
docker compose --env-file "$APP_ENV" --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.frontend.yml" build

echo ""
echo "Build complete:  dna-frontend  (tag = DNA_TAG from .env)"
echo "Next:  ./docker/airgap/up.sh"
