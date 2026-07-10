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
[ -f "$SCRIPT_DIR/.env" ] || {
    echo "Error: $SCRIPT_DIR/.env not found. cp .env.example .env and fill it in." >&2; exit 1; }

echo "==> Building DNA frontend via compose (build args from .env)..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.frontend.yml" build

echo ""
echo "Build complete:  dna-frontend  (tag = DNA_TAG from .env)"
echo "Next:  ./docker/airgap/up.sh"
