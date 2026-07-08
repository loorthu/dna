#!/usr/bin/env bash
# Stop the DNA stack on prod. Add --volumes to also delete the mongo data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

EXTRA=""
[ "${1:-}" = "--volumes" ] && EXTRA="--volumes"

echo "==> Stopping DNA stack..."
docker compose --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.prod.yml" down $EXTRA

echo "Done."
