#!/bin/bash
# Restart a DNA deployment in the sg namespace and wait for the rollout.
# Usage: ./docker/airgap/oc-rollout.sh {ui|collector} [--namespace=<ns>]
#
# Run after oc-secret.sh: envFrom is read at pod start, not live.
#
# This restarts the RUNNING image. It does not deploy a new one — the sg namespace is ArgoCD-
# managed, so a new tag has to be set in the k8s-sg repo (oc-push.sh prints where).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"
oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector}" >&2; exit 1; }
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --namespace=*) OC_NAMESPACE="${1#*=}"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done
oc_require_login
echo "Restarting deployment/${DEPLOYMENT} in namespace ${OC_NAMESPACE} ..."
oc rollout restart "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
oc rollout status "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
