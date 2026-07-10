#!/usr/bin/env bash
# Start the DNA stack (mongo + backend + frontend) from built (or loaded) images.
# DNA reaches Vexa over the network at VEXA_API_URL — Vexa runs on a different
# host, so there's no shared docker network to wait on.
#
# Build first (./docker/airgap/build.sh) or load transferred images (./load.sh).
#
# Usage:  ./docker/airgap/up.sh [tag]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "Error: docker/airgap/.env not found." >&2
  echo "  cp docker/airgap/.env.example docker/airgap/.env  and fill in secrets." >&2
  exit 1
fi

TAG="${1:-${DNA_TAG:-airgap}}"
export DNA_TAG="$TAG"

get() { grep -E "^$1=" "$SCRIPT_DIR/.env" | head -1 | cut -d= -f2- | tr -d ' '; }

echo "==> Starting DNA stack (DNA_TAG=$TAG)..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.prod.yml" up -d --no-build

echo ""
echo "==> DNA is up."
echo "    Backend:   http://<this-host>:$(get DNA_API_PORT || echo 8000)"
echo "    Frontend:  http://<this-host>:$(get DNA_FRONTEND_PORT || echo 8081)"
echo "    Vexa API:  $(get VEXA_API_URL)"
echo "    Stop:      ./docker/airgap/down.sh"
