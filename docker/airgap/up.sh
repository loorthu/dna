#!/usr/bin/env bash
# Start the DNA FRONTEND on prod. nginx serves the SPA and reverse-proxies
# /api + /ws to the DNA backend at BACKEND_URL (which runs on another host).
#
# Build first (./docker/airgap/build.sh) or load a transferred image (./load.sh).
#
# Usage:  ./docker/airgap/up.sh [tag]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "Error: docker/airgap/.env not found (cp .env.example .env and fill in)." >&2
  exit 1
fi

TAG="${1:-${DNA_TAG:-airgap}}"
export DNA_TAG="$TAG"
get() { grep -E "^$1=" "$SCRIPT_DIR/.env" | head -1 | cut -d= -f2- | tr -d ' '; }

echo "==> Starting DNA frontend (DNA_TAG=$TAG)..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.frontend.yml" up -d --no-build

echo ""
echo "==> DNA frontend is up."
echo "    Open:       http://<this-host>:$(get DNA_FRONTEND_PORT || echo 8081)"
echo "    Proxies to: $(get BACKEND_URL)   (backend API + WS)"
echo "    Stop:       ./docker/airgap/down.sh"
