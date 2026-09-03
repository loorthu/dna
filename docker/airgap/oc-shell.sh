#!/bin/bash
# Open a shell in a DNA pod.
# Usage: ./docker/airgap/oc-shell.sh {ui|collector} [--namespace=<ns>]
#
# What it is usually for: proving the mounts. Both pods need /shots AND /net, because the show
# directories under the share are symlinks onto each show's own volume — `ls -L` on a known
# archive is the check, and a dangling link here is the failure that looks like a missing file.
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
oc exec -it "deployment/${DEPLOYMENT}" -n "$OC_NAMESPACE" -- \
    sh -c 'command -v bash >/dev/null && exec bash || exec sh'
