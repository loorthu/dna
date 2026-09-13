#!/usr/bin/env bash
# Build the DNA images, for the host deployment or for the OpenShift cluster.
#
# Usage:
#   ./docker/airgap/build.sh                    # host, both images
#   ./docker/airgap/build.sh host collector     # host, one image
#   ./docker/airgap/build.sh cluster            # cluster, both images
#   ./docker/airgap/build.sh cluster ui         # cluster, one image
#
# Next:  host    -> ./docker/airgap/up.sh
#        cluster -> ./docker/airgap/run.sh <app>   (smoke test)
#                   ./docker/airgap/push.sh <app>
#
# ONE build path for both targets. Both build the same Dockerfiles from the same sources; what
# differs is the image name, the tag, the platform and the base-image mirror, and all four live in
# docker-compose.cluster.yml. There used to be a separate oc-build.sh spelling out every VITE_*
# build arg a second time, and its copy of the defaults had already drifted from compose's.
#
# CONFIGURATION is layered, upstream first, and the layering is the only real difference between
# the two targets:
#
#   host     frontend/packages/app/.env   then  docker/airgap/.env
#   cluster  frontend/packages/app/.env   then  docker/airgap/.env   then  .env.openshift
#
# The last definition of a repeated key wins, which is how .env.openshift changes the four keys the
# cluster mounts under a path prefix without restating the rest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET="${1:-host}"
case "$TARGET" in
    host|cluster) shift || true ;;
    ui|collector) TARGET=host ;;          # `build.sh collector` means the host one
    *) echo "Usage: $0 [host|cluster] [ui|collector]" >&2; exit 1 ;;
esac

# Service names in the compose file, which are not the app names the cluster uses: the cluster's
# front end is `ui` (Deployment sg-dna) and compose's service is `frontend`.
SERVICES=()
case "${1:-all}" in
    all)              SERVICES=(frontend collector) ;;
    ui|frontend)      SERVICES=(frontend) ;;
    collector)        SERVICES=(collector) ;;
    *) echo "Unknown app '${1}'. Expected: ui | collector" >&2; exit 1 ;;
esac

APP_ENV="$REPO_ROOT/frontend/packages/app/.env"
[ -f "$SCRIPT_DIR/.env" ] || {
    echo "Error: $SCRIPT_DIR/.env not found. cp .env.example .env and fill it in." >&2; exit 1; }
[ -f "$APP_ENV" ] || {
    echo "Error: $APP_ENV not found." >&2
    echo "       It is the upstream home for VITE_*; create it with:" >&2
    echo "         cp frontend/packages/app/.env.example frontend/packages/app/.env" >&2; exit 1; }

ENV_FILES=(--env-file "$APP_ENV" --env-file "$SCRIPT_DIR/.env")
COMPOSE_FILES=(-f "$SCRIPT_DIR/docker-compose.frontend.yml")

if [ "$TARGET" = "cluster" ]; then
    [ -f "$SCRIPT_DIR/.env.openshift" ] && ENV_FILES+=(--env-file "$SCRIPT_DIR/.env.openshift")
    COMPOSE_FILES+=(-f "$SCRIPT_DIR/docker-compose.cluster.yml")
    # The cluster tags by release, not by a moving label. Exported rather than passed as a build
    # arg because it is the compose `image:` that needs it, not the Dockerfile.
    DNA_TAG="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
    export DNA_TAG
    export REGISTRY_MIRROR="${REGISTRY_MIRROR:-docker.artifactory.spimageworks.com}"
    echo "==> Building for the CLUSTER (tag $DNA_TAG, via $REGISTRY_MIRROR)"
else
    echo "==> Building for the HOST deployment (tag ${DNA_TAG:-airgap})"
fi
LAYERS="$SCRIPT_DIR/.env"
[ "$TARGET" = "cluster" ] && LAYERS="$LAYERS + .env.openshift"
echo "    services    : ${SERVICES[*]}"
echo "    VITE_* from : $APP_ENV"
echo "    overrides   : $LAYERS"
echo

docker compose "${ENV_FILES[@]}" "${COMPOSE_FILES[@]}" build "${SERVICES[@]}"

echo
if [ "$TARGET" = "cluster" ]; then
    echo "Built for the cluster at tag ${DNA_TAG}."
    echo "  Smoke-test:  ./docker/airgap/run.sh <ui|collector>"
    echo "  Then push:   ./docker/airgap/push.sh <ui|collector>"
else
    echo "Built for the host deployment (tag ${DNA_TAG:-airgap})."
    echo "  Next:  ./docker/airgap/up.sh"
fi
