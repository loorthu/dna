#!/bin/bash
# Tear down the full DNA + Vexa dev stack.
# Usage:
#   sudo ./dev-down.sh          # stop and remove containers (keep volumes)
#   sudo ./dev-down.sh --clean  # also wipe all images, build cache, and volumes (full reset)

set -e
cd "$(dirname "$0")"

COMPOSE="docker compose \
  -f docker-compose.yml \
  -f docker-compose.vexa.yml \
  -f docker-compose.local.yml \
  -f docker-compose.local.vexa.yml"

if [[ "$1" == "--clean" ]]; then
  echo "==> Stopping containers and removing volumes..."
  $COMPOSE down -v
  echo "==> Removing all Docker images and build cache..."
  docker system prune -af
else
  echo "==> Stopping and removing containers (volumes preserved)..."
  $COMPOSE down
fi

echo "==> Done."
