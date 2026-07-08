#!/usr/bin/env bash
# Build DNA backend + frontend images for air-gapped deployment.
# Run on a machine WITH internet.
#
# Produces:  dna-backend:<tag>   dna-frontend:<tag>   (tag default: airgap)
#
# The frontend is a static Vite build — its API URLs are baked in at BUILD time
# from the VITE_* values in docker/airgap/.env, so they must point at URLs the
# end user's browser can reach on prod.
#
# Usage:  ./docker/airgap/build.sh [tag]
# Next:   ./docker/airgap/save.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

# Load .env for DNA_TAG and the VITE_* frontend build args.
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a; . "$SCRIPT_DIR/.env"; set +a
else
  echo "WARNING: $SCRIPT_DIR/.env not found — frontend will build with empty API URLs." >&2
  echo "         cp docker/airgap/.env.example docker/airgap/.env  and edit it." >&2
fi

TAG="${1:-${DNA_TAG:-airgap}}"
PLATFORM="linux/amd64"

echo "==> Building DNA air-gap images (tag: $TAG)"

echo "==> [1/2] dna-backend"
docker build --platform "$PLATFORM" \
  -t "dna-backend:$TAG" \
  -f backend/Dockerfile backend

echo ""
echo "==> [2/2] dna-frontend  (API base: ${VITE_API_BASE_URL:-<unset>})"
docker build --platform "$PLATFORM" \
  -t "dna-frontend:$TAG" \
  --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL:-}" \
  --build-arg "VITE_WS_URL=${VITE_WS_URL:-}" \
  --build-arg "VITE_AUTH_PROVIDER=${VITE_AUTH_PROVIDER:-none}" \
  --build-arg "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID:-}" \
  -f frontend/Dockerfile frontend

echo ""
echo "Build complete: dna-backend:$TAG  dna-frontend:$TAG"
echo "Next:  ./docker/airgap/save.sh $TAG"
