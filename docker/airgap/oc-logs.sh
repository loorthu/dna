#!/bin/bash
# Follow a DNA deployment's logs.
# Usage: ./docker/airgap/oc-logs.sh {ui|collector} [--tail=N] [--namespace=<ns>]
#
# For the collector this is the primary instrument: it has no port, so there is no health endpoint
# to ask and the log is the only thing that says whether it is working.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"
oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector}" >&2; exit 1; }
shift
TAIL=100
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tail=*) TAIL="${1#*=}"; shift ;;
        --namespace=*) OC_NAMESPACE="${1#*=}"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done
oc_require_login
oc logs -f --tail="$TAIL" "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE"
