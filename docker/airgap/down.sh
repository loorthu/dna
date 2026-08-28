#!/usr/bin/env bash
# Stop the DNA frontend on prod.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_ENV="$REPO_ROOT/frontend/packages/app/.env"

# Same layering as up.sh (see docker/airgap/.env). `down` only needs enough
# interpolation to resolve the project's names, but an unset VITE_* would warn —
# so include the app's .env when it is there, and stop cleanly when it is not.
ENV_FILES=()
[ -f "$APP_ENV" ] && ENV_FILES+=(--env-file "$APP_ENV")
ENV_FILES+=(--env-file "$SCRIPT_DIR/.env")

echo "==> Stopping DNA frontend..."
docker compose "${ENV_FILES[@]}" \
  -f "$SCRIPT_DIR/docker-compose.frontend.yml" down

echo "Done."
