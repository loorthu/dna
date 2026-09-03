# Shared by the oc-* scripts. Sourced, not run.
#
# One place for the two things every one of them needs: what an app is CALLED in the cluster, and
# the layered env files it is configured from.

# The `sg` namespace's naming, matching the sibling sg-admin apps
# (image sg-admin-<app> -> Deployment sg-<app> -> Service sg-<app>-service -> Secret secret-sg-<app>).
#
# The collector has no Service because it has no listener: it is a poll loop with an outbound HTTP
# client and two mounts, and nothing in the cluster ever calls it.
oc_resolve_app() {
    case "$1" in
        ui)
            APP=ui
            IMAGE=dna-ui
            DEPLOYMENT=sg-dna
            SERVICE=sg-dna-service
            SECRET=secret-sg-dna
            ;;
        collector)
            APP=collector
            IMAGE=dna-collector
            DEPLOYMENT=sg-dna-collector
            SERVICE=
            SECRET=secret-sg-dna-collector
            ;;
        *)
            echo "Unknown app '$1'. Expected: ui | collector" >&2
            return 1
            ;;
    esac
}

# The deployment's configuration, layered lowest-priority first — the same order build.sh and
# up.sh use, and the reason .env.openshift can be four lines instead of a second copy of .env.
#
# `set -a` turns a plain KEY=value file into exports, which is what the build args and the Secret
# writer both read. Values are never echoed: see the credential rule in sg-admin/CLAUDE.md.
oc_load_env() {
    local script_dir="$1" repo_root="$2"
    set -a
    # shellcheck disable=SC1091
    [ -f "$repo_root/frontend/packages/app/.env" ] && . "$repo_root/frontend/packages/app/.env"
    # shellcheck disable=SC1091
    [ -f "$script_dir/.env" ] && . "$script_dir/.env"
    # shellcheck disable=SC1091
    [ -f "$script_dir/.env.openshift" ] && . "$script_dir/.env.openshift"
    set +a
}

oc_require_login() {
    if ! oc whoami >/dev/null 2>&1; then
        echo "Error: not logged in to OpenShift. Run 'oc login' first." >&2
        return 1
    fi
}

OC_NAMESPACE="${OC_NAMESPACE:-sg}"
