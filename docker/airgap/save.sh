#!/usr/bin/env bash
# Save DNA images into a transferable bundle in docker/airgap/dist/.
# Produces:  dist/dna-images-<tag>.tar.gz  (dna-backend, dna-frontend, mongo:7)
#
# Usage:  ./docker/airgap/save.sh [tag]
# Next:   copy dist/* to prod, then ./docker/airgap/load.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

[ -f "$SCRIPT_DIR/.env" ] && { set -a; . "$SCRIPT_DIR/.env"; set +a; }
TAG="${1:-${DNA_TAG:-airgap}}"
DIST="$SCRIPT_DIR/dist"
mkdir -p "$DIST"

IMAGES=( "dna-backend:$TAG" "dna-frontend:$TAG" "mongo:7" )

echo "==> Images to save:"
printf '      %s\n' "${IMAGES[@]}"

missing=0
for img in "${IMAGES[@]}"; do
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "    MISSING: $img"; missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "Error: run ./docker/airgap/build.sh first (and 'docker pull mongo:7' if needed)." >&2
  exit 1
fi

OUT="$DIST/dna-images-$TAG.tar"
echo "==> Saving -> $OUT.gz"
docker save -o "$OUT" "${IMAGES[@]}"
gzip -f "$OUT"
echo "$TAG" > "$DIST/DNA_TAG"
chmod 644 "$DIST"/*.gz "$DIST/DNA_TAG" 2>/dev/null || true

echo ""
echo "Export complete:"
ls -lh "$DIST"/*.gz
echo ""
echo "Transfer dist/* (and your docker/airgap/.env) to prod, then:"
echo "  ./docker/airgap/load.sh  &&  ./docker/airgap/up.sh"
