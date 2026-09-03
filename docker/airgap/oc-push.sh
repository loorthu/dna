#!/bin/bash
# Push a built DNA image to Artifactory for the OpenShift `sg` namespace.
# Usage: ./docker/airgap/oc-push.sh {ui|collector}
#
# Run ./docker/airgap/oc-build.sh <app> first — this only tags and pushes.
# Only the VERSIONED tag is pushed, never :latest — releases are immutable, and ArgoCD deploys by
# tag, so a moving :latest would make "which image is running" unanswerable.
#
# Override the registry base with: REGISTRY=<host>/<namespace> ./docker/airgap/oc-push.sh <app>
#
# No `docker login` here. Run it once beforehand if your registry needs it; `docker push` uses the
# cached credentials.

set -euo pipefail

DOCKER="${DOCKER:-docker}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"

oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector}" >&2; exit 1; }

VERSION="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
REGISTRY="${REGISTRY:-docker-local.artifactory.spimageworks.com/gitlab/spi/dev/infrastructure/web}"
REGISTRY_TAG="${REGISTRY}/${IMAGE}:${VERSION}"

if ! $DOCKER image inspect "${IMAGE}:${VERSION}" >/dev/null 2>&1; then
    echo "Error: ${IMAGE}:${VERSION} not found locally. Run ./docker/airgap/oc-build.sh ${APP} first." >&2
    exit 1
fi

echo "Tagging ${IMAGE}:${VERSION} -> ${REGISTRY_TAG}"
$DOCKER tag "${IMAGE}:${VERSION}" "${REGISTRY_TAG}"
echo "Pushing ${REGISTRY_TAG}"
$DOCKER push "${REGISTRY_TAG}"

cat <<EOF

Push complete: ${REGISTRY_TAG}

The sg namespace is managed by ArgoCD. Do NOT 'oc set image' — it will be reconciled back.
To deploy, ask the platform team to set the image tag in:

  https://gitlab.spimageworks.com/spi/dev/dev-ops/k8s-sg

  deployment: ${DEPLOYMENT}
  image:      ${REGISTRY_TAG}
EOF
