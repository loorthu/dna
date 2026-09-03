#!/bin/bash
# Build a DNA image for the OpenShift `sg` namespace.
# Usage: ./docker/airgap/oc-build.sh {ui|collector}
#
# Reads docker/airgap/VERSION for the tag, and .env + .env.openshift for the build args — the
# same two-file layering build.sh and up.sh use, so the backend address, the share paths and the
# Artifactory registries are inherited rather than restated.
#
# Not `docker compose build`: the collector needs a BuildKit NAMED CONTEXT (--build-context) to
# take its collection logic from the backend package, and compose cannot pass one. That is also
# why these images cannot be built by an OpenShift BuildConfig.

set -euo pipefail

DOCKER="${DOCKER:-docker}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"

oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector}" >&2; exit 1; }
oc_load_env "$SCRIPT_DIR" "$REPO_ROOT"

VERSION="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"

# Base images through Artifactory. The public names are the Dockerfile defaults, so this is the
# only place the mirror is named for a cluster build.
REGISTRY_MIRROR="${REGISTRY_MIRROR:-docker.artifactory.spimageworks.com}"

echo "==> Building dna-${APP}:${VERSION} (linux/amd64)"

if [ "$APP" = "ui" ]; then
    # Every VITE_* is baked in HERE and cannot be changed afterwards; the runtime half of the
    # config reaches the pod through secret-sg-dna instead. Passed explicitly rather than with a
    # loop so an unset one is visibly empty rather than silently absent.
    $DOCKER build --platform linux/amd64 \
        --build-arg NODE_IMAGE="${REGISTRY_MIRROR}/node:20-alpine" \
        --build-arg NGINX_IMAGE="${REGISTRY_MIRROR}/nginx:alpine" \
        --build-arg NPM_REGISTRY="${NPM_REGISTRY:-}" \
        --build-arg VITE_BASE_PATH="${VITE_BASE_PATH:-}" \
        --build-arg VITE_API_BASE_URL="${VITE_API_BASE_URL:-}" \
        --build-arg VITE_WS_URL="${VITE_WS_URL:-}" \
        --build-arg VITE_AUTH_PROVIDER="${VITE_AUTH_PROVIDER:-none}" \
        --build-arg VITE_GOOGLE_CLIENT_ID="${VITE_GOOGLE_CLIENT_ID:-}" \
        --build-arg VITE_FEATURE_FOLLOW_ALONG="${VITE_FEATURE_FOLLOW_ALONG:-}" \
        --build-arg VITE_FOLLOW_ALONG_BROKER_URL="${VITE_FOLLOW_ALONG_BROKER_URL:-}" \
        --build-arg VITE_FOLLOW_ALONG_TOPIC="${VITE_FOLLOW_ALONG_TOPIC:-}" \
        --build-arg VITE_FOLLOW_ALONG_SESSIONS_URL="${VITE_FOLLOW_ALONG_SESSIONS_URL:-}" \
        --build-arg VITE_FEATURE_NOTE_QC="${VITE_FEATURE_NOTE_QC:-false}" \
        --build-arg VITE_FEATURE_TRANSCRIPT_PUBLISH="${VITE_FEATURE_TRANSCRIPT_PUBLISH:-false}" \
        --build-arg VITE_FEATURE_NOTE_LINKS="${VITE_FEATURE_NOTE_LINKS:-false}" \
        --build-arg VITE_FEATURE_NOTE_SUBJECT="${VITE_FEATURE_NOTE_SUBJECT:-false}" \
        -f "$REPO_ROOT/frontend/Dockerfile" \
        -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" \
        "$REPO_ROOT/frontend"
else
    # --build-context dna=... is the whole reason this is `docker build`. It puts the backend's
    # recording_collector.py and recording_posters.py in the image, so the collector runs the same
    # code the backend test suite covers rather than a vendored copy that drifts.
    DOCKER_BUILDKIT=1 $DOCKER build --platform linux/amd64 \
        --build-context dna="$REPO_ROOT/backend/src/dna" \
        --build-arg PYTHON_IMAGE="${REGISTRY_MIRROR}/python:3.11-slim" \
        --build-arg PIP_INDEX_URL="${PIP_INDEX_URL:-}" \
        --build-arg PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-}" \
        -f "$REPO_ROOT/collector/Dockerfile" \
        -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" \
        "$REPO_ROOT/collector"
fi

echo
echo "Built ${IMAGE}:${VERSION}"
echo "  Smoke-test:  ./docker/airgap/oc-run.sh ${APP}"
echo "  Then push:   ./docker/airgap/oc-push.sh ${APP}"
