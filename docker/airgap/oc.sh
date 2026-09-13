#!/usr/bin/env bash
# Talk to the running pods in the OpenShift `sg` namespace.
#
# Usage: ./docker/airgap/oc.sh {rollout|logs|shell} {ui|collector} [--namespace=<ns>] [--tail=N]
#
#   rollout   restart the Deployment and wait for it. Needed after oc-secret.sh, because
#             envFrom/secretKeyRef are read at pod start, not live.
#   logs      follow the log (--tail=N, default 100)
#   shell     interactive shell in the pod. Usually for proving the mounts — both pods need
#             /shots AND /net, because a show's directory is a symlink onto its own volume.
#
# One script rather than three: oc-rollout.sh, oc-logs.sh and oc-shell.sh were the same fifteen
# lines of app resolution, namespace parsing and login checking wrapped around a single `oc` verb.
# oc-secret.sh stays separate — it builds a Secret from layered .env files and is a different job.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/common.sh"

usage() {
    echo "Usage: $0 {rollout|logs|shell} {ui|collector} [--namespace=<ns>] [--tail=N]" >&2
    exit 1
}

VERB="${1:-}"
case "$VERB" in
    rollout|logs|shell) shift ;;
    *) usage ;;
esac

oc_resolve_app "${1:-}" || usage
shift

TAIL=100
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tail=*) TAIL="${1#*=}"; shift ;;
        --namespace=*) OC_NAMESPACE="${1#*=}"; shift ;;
        *) echo "Unknown arg: $1" >&2; usage ;;
    esac
done

oc_require_login

case "$VERB" in
    rollout)
        echo "Restarting deployment/${DEPLOYMENT} in namespace ${OC_NAMESPACE} ..."
        oc rollout restart "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
        oc rollout status "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
        ;;
    logs)
        oc logs -f --tail="$TAIL" "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
        ;;
    shell)
        # bash if the image has it, sh otherwise: the ui is Alpine, the collector is Debian-slim.
        oc exec -it "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE" -- \
            sh -c 'command -v bash >/dev/null && exec bash || exec sh'
        ;;
esac
