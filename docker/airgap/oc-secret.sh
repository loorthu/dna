#!/bin/bash
# Create or update a DNA Secret in the OpenShift `sg` namespace.
# Usage: ./docker/airgap/oc-secret.sh {ui|collector} [--diff] [--namespace=<ns>]
#
# WHAT THIS IS: the compose file's `environment:` block, for the cluster.
#
# docker-compose.frontend.yml takes one .env and hands each container the subset it needs. This
# script does the same for two Secrets instead of two containers, off the same file.
#
# A key is spelled the SAME in .env, in the Secret, and in the container that reads it. There is no
# rename step and there should never be one: a value that arrives under a second name is a value
# somebody has to be told about, and the earlier mapping (BACKEND_URL -> DNA_API_URL,
# COLLECTOR_UID -> NGINX_UID) cost more in confusion than the neutral names were worth. If a new
# consumer wants a different spelling, change the consumer.
#
# WHY AN ALLOWLIST, not sg-admin's `grep -v ^VITE_`: that works when one .env feeds one pod. This
# .env also carries build mechanics (DNA_TAG, NPM_REGISTRY, PIP_*) and a backend flag, and it
# feeds two pods. A blocklist would quietly ship the next key somebody adds to both.
#
# Idempotent — `oc create ... --dry-run=client | oc apply` upserts whether or not it exists.
#
# After applying, restart the Deployment: envFrom is read at pod start, not live.
#   ./docker/airgap/oc.sh rollout <app>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/common.sh"

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
# REQUIRED keys are written ALWAYS, empty when .env does not set them. OPTIONAL keys are written
# only when set. The difference is not style, it is what stops a pod refusing to start:
#
#   Error: couldn't find key DNA_API_TOKEN in Secret sg/secret-sg-dna-collector
#
# The k8s-sg Deployments name keys one at a time (`env: valueFrom: secretKeyRef:`), and such a
# reference to a key the Secret lacks is a CreateContainerConfigError, not a fallback. This script
# used to omit every unset key, so a value nobody had set became a pod nobody could start. The
# sibling apps never hit it because they write their whole .env, empty values included.
#
# So: everything a manifest may name lives in REQUIRED and is always present. OPTIONAL is for keys
# a manifest must NOT name — extras that appear only for a site that wants them, which are inert
# under either consumption style. Adding a key here is safe; promoting one to REQUIRED is a
# two-sided change until the manifests move to `envFrom: secretRef:` (see INSTALL_OPEN_SHIFT.md).
OPTIONAL=()
case "$APP" in
    ui)
        # nginx substitutes these into default.conf.template at container start. The first three
        # have NO default in the image: unset, envsubst leaves a literal ${VAR} and nginx refuses
        # the config, so they must reach the pod even empty.
        REQUIRED=(
            BACKEND_URL
            REVIEW_SESSIONS_URL
            RECORDING_NETWORK_PATH
            APP_BASE_PATH
            # The same site name the collector below reads: nginx sends it as X-DNA-Site on every
            # dispatch, which is what routes the recording to this namespace's own collector.
            COLLECTOR_SITE
            # One share, one identity: nginx must SERVE as the uid that WROTE the files, because
            # the NFS server discounts supplementary groups and knows only the primary uid/gid.
            # Same two keys the collector's `user:` takes, which is why they are not nginx-specific.
            # On OpenShift the SCC pins runAsUser and the entrypoint can only warn on a mismatch —
            # they are a consistency check there, and the mechanism on the host deployment.
            COLLECTOR_UID
            COLLECTOR_GID
        )
        ;;
    collector)
        REQUIRED=(
            # The collector talks to the backend DIRECTLY, not through the UI's nginx: it is a
            # server-side client, and there is no reason to add a proxy hop to a few hundred MB.
            # Same key the UI gets, and the bare address either way — nginx strips the path prefix
            # before proxying, so nothing downstream ever sees /dna/api.
            #
            # Wrong or missing, this is the quietest failure in either image: the collector polls
            # its own localhost forever, logs a retry per pass, and stays "healthy" with no HTTP
            # probe to contradict it. Hence required, not defaulted.
            BACKEND_URL
            RECORDING_NETWORK_PATH
            RECORDING_ARCHIVE_DIR
            COLLECTOR_SITE
        )
        # Tuning knobs live in the code's own defaults (poll 10s, queue 25, poster lead 2s,
        # LOG_LEVEL INFO). They are NOT listed even as optional: a site that needs one adds it
        # here and to the manifest together, deliberately.
        #
        # RECORDING_ARCHIVE_TIMEZONE is not here either, and that is a fix rather than a trim: it
        # is read by archive_timezone() -> archive_name(), which runs in the BACKEND. The collector
        # asks the backend for its archive name over HTTP, so the key did nothing on this pod. It
        # belongs on the backend service — see docker-compose.prod.yml.
        ;;
esac

# Fixed in the cluster rather than read from .env: the staging PVC's mount path is a property of
# the manifest, not of the host deployment, where it is a named docker volume.
declare -A FIXED=()
[ "$APP" = "collector" ] && FIXED[COLLECTOR_STAGING_DIR]=/staging

ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"
trap 'rm -f "$ENV_FILE"' EXIT

INCLUDED=()
DEFAULTED=()
OMITTED=()

# Required: always written. `${!key-}` is an unset key read as empty rather than an error, which
# is the whole point — the key exists in the Secret either way, and empty is a meaningful value
# for several (APP_BASE_PATH empty means the root; COLLECTOR_SITE empty means the unrouted queue).
for key in "${REQUIRED[@]}"; do
    printf '%s=%s\n' "$key" "${!key-}" >> "$ENV_FILE"
    if [ -n "${!key+set}" ]; then
        INCLUDED+=("$key")
    else
        DEFAULTED+=("$key")
    fi
done

# Optional: written only when the site set one.
for key in "${OPTIONAL[@]}"; do
    if [ -n "${!key+set}" ]; then
        printf '%s=%s\n' "$key" "${!key}" >> "$ENV_FILE"
        INCLUDED+=("$key")
    else
        OMITTED+=("$key")
    fi
done
for target in "${!FIXED[@]}"; do
    printf '%s=%s\n' "$target" "${FIXED[$target]}" >> "$ENV_FILE"
    INCLUDED+=("$target")
done

# Key NAMES only, never values — the transcript and the shell history are both places a secret
# must not land (see the credential rule in sg-admin/CLAUDE.md).
echo "Keys for ${SECRET} (namespace ${OC_NAMESPACE}):"
[ ${#INCLUDED[@]} -gt 0 ] && printf '  %s\n' "${INCLUDED[@]}"
# Written, but with nothing behind them. Not a warning — empty is the supported value for most of
# these — but it is what to look at first when a pod starts and behaves as though unconfigured.
if [ ${#DEFAULTED[@]} -gt 0 ]; then
    echo "Written empty (not set in .env):"
    printf '  %s\n' "${DEFAULTED[@]}"
fi
if [ ${#OMITTED[@]} -gt 0 ]; then
    echo "Not set, so left out entirely — the image's own default applies:"
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
echo "  ./docker/airgap/oc.sh rollout ${APP}"
