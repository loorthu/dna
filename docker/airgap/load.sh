#!/usr/bin/env bash
# Load DNA images on the air-gapped prod server.
# Usage:  ./docker/airgap/load.sh [tag]
# Next:   ./docker/airgap/up.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

DIST="$SCRIPT_DIR/dist"
TAG="${1:-${DNA_TAG:-$(cat "$DIST/DNA_TAG" 2>/dev/null || echo airgap)}}"
BUNDLE="$DIST/dna-images-$TAG.tar.gz"

if [ ! -f "$BUNDLE" ]; then
  echo "Error: bundle not found: $BUNDLE (copy dist/*.gz from the build machine)." >&2
  exit 1
fi

echo "==> Loading images from $BUNDLE ..."
gunzip -c "$BUNDLE" | docker load

echo ""
docker images | grep -E "dna-(backend|frontend)|mongo" || true
echo ""
echo "Next:  ./docker/airgap/up.sh $TAG"
