#!/usr/bin/env bash
# Build the DNA images (dna-backend + dna-frontend) via compose.
#
# All build args come from docker/airgap/.env:
#   - On the air-gapped prod host: set PIP_INDEX_URL / PIP_TRUSTED_HOST / NPM_REGISTRY
#     to the internal Artifactory so pip/npm resolve without public internet.
#   - To build on an internet-connected machine (for save/transfer): leave those
#     empty and pip/npm use the public registries.
#   - VITE_* are baked into the frontend at build time — point them at URLs the
#     end user's BROWSER can reach on prod.
#
# Usage:  ./docker/airgap/build.sh
# Next:   ./docker/airgap/up.sh          (run it here)
#     or  ./docker/airgap/save.sh        (package the images to transfer elsewhere)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/.env" ] || {
    echo "Error: $SCRIPT_DIR/.env not found. cp .env.example .env and fill it in." >&2; exit 1; }

echo "==> Building DNA images via compose (build args from .env)..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.prod.yml" build

echo ""
echo "Build complete:  dna-backend / dna-frontend  (tag = DNA_TAG from .env)"
echo "Next:  ./docker/airgap/up.sh    (or ./docker/airgap/save.sh to transfer prebuilt images)"
