#!/bin/bash
# Create or update a DNA Secret in the OpenShift `sg` namespace.
# Usage: ./docker/airgap/oc-secret.sh {ui|collector} [--diff] [--namespace=<ns>]
#
# WHAT THIS IS: the compose file's `environment:` block, for the cluster.
#
# docker-compose.frontend.yml takes one .env and hands each container the subset it needs, under
# the names that container expects — BACKEND_URL reaches the collector as DNA_API_URL, and
# COLLECTOR_UID/GID reach nginx as NGINX_UID/NGINX_SHARE_GID, because they are one identity
# described once. This script does exactly that for two Secrets instead of two containers, off the
# same file. The names are not drift; they are the same mapping, and changing one without the
# other is what breaks a deployment.
#
# WHY AN ALLOWLIST, not sg-admin's `grep -v ^VITE_`: that works when one .env feeds one pod. This
# .env also carries build mechanics (DNA_TAG, NPM_REGISTRY, PIP_*) and a backend flag, and it
# feeds two pods. A blocklist would quietly ship the next key somebody adds to both.
#
# Idempotent — `oc create ... --dry-run=client | oc apply` upserts whether or not it exists.
#
# After applying, restart the Deployment: envFrom is read at pod start, not live.
#   ./docker/airgap/oc-rollout.sh <app>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/oc-common.sh"

oc_resolve_app "${1:-}" || { echo "Usage: $0 {ui|collector} [--diff]" >&2; exit 1; }
shift

DIFF_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --diff) DIFF_ONLY=1; shift ;;
        --namespace=*) OC_NAMESPACE="${1#*=}"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

oc_load_env "$SCRIPT_DIR" "$REPO_ROOT"

# What each pod actually reads at RUNTIME, as "SECRET_KEY=SOURCE_KEY".
#
# Nothing VITE_* appears in either: those are baked into the bundle at build time and are already
# in the browser by the time a pod starts. Putting them in a Secret would imply they could be
# changed there, which is the misunderstanding most likely to waste an afternoon.
case "$APP" in
    ui)
        # nginx substitutes these into default.conf.template at container start.
        KEYS=(
            BACKEND_URL=BACKEND_URL
            REVIEW_SESSIONS_URL=REVIEW_SESSIONS_URL
            RECORDING_NETWORK_PATH=RECORDING_NETWORK_PATH
            APP_BASE_PATH=APP_BASE_PATH
            # One share, one identity: nginx must SERVE as the uid that WROTE the files, because
            # the NFS server discounts supplementary groups and knows only the primary uid/gid.
            NGINX_UID=COLLECTOR_UID
            NGINX_SHARE_GID=COLLECTOR_GID
        )
        ;;
    collector)
        KEYS=(
            # The collector talks to the backend DIRECTLY, not through the UI's nginx: it is a
            # server-side client, and there is no reason to add a proxy hop to a few hundred MB.
            DNA_API_URL=BACKEND_URL
            DNA_API_TOKEN=DNA_API_TOKEN
            RECORDING_NETWORK_PATH=RECORDING_NETWORK_PATH
            RECORDING_ARCHIVE_DIR=RECORDING_ARCHIVE_DIR
            RECORDING_ARCHIVE_TIMEZONE=RECORDING_ARCHIVE_TIMEZONE
            COLLECTOR_POLL_SECONDS=COLLECTOR_POLL_SECONDS
            COLLECTOR_MAX_PLAYLISTS=COLLECTOR_MAX_PLAYLISTS
            COLLECTOR_SITE=COLLECTOR_SITE
            RECORDING_POSTER_LEAD_SECONDS=RECORDING_POSTER_LEAD_SECONDS
            LOG_LEVEL=LOG_LEVEL
        )
        ;;
esac

# Fixed in the cluster rather than read from .env: the staging PVC's mount path is a property of
# the manifest, not of the host deployment, where it is a named docker volume.
declare -A FIXED=()
[ "$APP" = "collector" ] && FIXED[COLLECTOR_STAGING_DIR]=/staging

# An UNSET source key is omitted so the image's own default applies. An empty-but-set one is kept:
# empty is meaningful for several of these (DNA_API_TOKEN empty means the backend runs without
# auth; APP_BASE_PATH empty means the root).
ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"
trap 'rm -f "$ENV_FILE"' EXIT

INCLUDED=()
OMITTED=()
for pair in "${KEYS[@]}"; do
    target="${pair%%=*}"; source_key="${pair#*=}"
    if [ -n "${!source_key+set}" ]; then
        printf '%s=%s\n' "$target" "${!source_key}" >> "$ENV_FILE"
        INCLUDED+=("$target")
    else
        OMITTED+=("$target (from $source_key)")
    fi
done
for target in "${!FIXED[@]}"; do
    printf '%s=%s\n' "$target" "${FIXED[$target]}" >> "$ENV_FILE"
    INCLUDED+=("$target")
done

# Key NAMES only, never values — the transcript and the shell history are both places a secret
# must not land (see the credential rule in sg-admin/CLAUDE.md).
echo "Keys for ${SECRET} (namespace ${OC_NAMESPACE}):"
printf '  %s\n' "${INCLUDED[@]}"
if [ ${#OMITTED[@]} -gt 0 ]; then
    echo "Not set, so left to the image's default:"
    printf '  %s\n' "${OMITTED[@]}"
fi

if [ "$DIFF_ONLY" = "1" ]; then
    echo
    echo "Keys currently in ${SECRET}:"
    if oc get secret "$SECRET" -n "$OC_NAMESPACE" >/dev/null 2>&1; then
        oc get secret "$SECRET" -n "$OC_NAMESPACE" \
            -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' | sort | sed 's/^/  /'
    else
        echo "  (does not exist yet — apply will create it)"
    fi
    exit 0
fi

oc_require_login

echo
echo "Applying ${SECRET} in namespace ${OC_NAMESPACE} ..."
oc create secret generic "$SECRET" \
    --from-env-file="$ENV_FILE" \
    --dry-run=client -o yaml \
    | oc apply -n "$OC_NAMESPACE" -f -

echo
echo "Done. Restart the deployment to pick it up (envFrom is read at pod start):"
echo "  ./docker/airgap/oc-rollout.sh ${APP}"
