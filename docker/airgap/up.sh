#!/usr/bin/env bash
# Start the DNA stack on prod from pre-loaded images (never builds/pulls).
# Start the Vexa stack FIRST — DNA's api joins Vexa's vexa_vexa network.
#
# Usage:  ./docker/airgap/up.sh [tag]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "Error: docker/airgap/.env not found." >&2
  echo "  cp docker/airgap/.env.example docker/airgap/.env  and fill in secrets." >&2
  exit 1
fi

TAG="${1:-${DNA_TAG:-$(cat "$SCRIPT_DIR/dist/DNA_TAG" 2>/dev/null || echo airgap)}}"
export DNA_TAG="$TAG"

# DNA's api attaches to the Vexa network. Fail clearly if Vexa isn't up.
if ! docker network inspect vexa_vexa >/dev/null 2>&1; then
  echo "Error: docker network 'vexa_vexa' not found." >&2
  echo "  Start the Vexa stack first:  (in the vexa repo) ./docker/airgap/up.sh" >&2
  exit 1
fi

echo "==> Starting DNA stack (DNA_TAG=$TAG)..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.prod.yml" up -d --no-build

echo ""
echo "==> DNA is up."
echo "    Backend:   http://localhost:$(grep -E '^DNA_API_PORT=' "$SCRIPT_DIR/.env" | cut -d= -f2 || echo 8000)"
echo "    Frontend:  http://localhost:$(grep -E '^DNA_FRONTEND_PORT=' "$SCRIPT_DIR/.env" | cut -d= -f2 || echo 8081)"
echo "    Stop:      ./docker/airgap/down.sh"
