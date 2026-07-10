#!/usr/bin/env bash
# Stop the DNA frontend on prod.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Stopping DNA frontend..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.frontend.yml" down

echo "Done."
