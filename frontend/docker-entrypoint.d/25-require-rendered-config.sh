#!/bin/sh
# Fail the container if the server block was never rendered.
#
# The stock 20-envsubst-on-templates.sh checks that its output directory is writable and, when it
# is not, logs one line and RETURNS 0. nginx then starts with no server block — an `include` glob
# matching nothing is not an error — and answers nothing on 8080, or serves the stock welcome page
# if any default config survived. Both look like a broken app rather than a misconfigured mount,
# and under an arbitrary uid (OpenShift assigns one per namespace) that directory not being
# writable is the single likeliest thing to go wrong.
#
# So the render is checked here instead: present and non-empty, or the container does not start.
# A pod that crash-loops with this message names its own cause; a pod serving 404s does not.
set -e

out="${NGINX_ENVSUBST_OUTPUT_DIR:-/etc/nginx/conf.d}"
rendered="$out/default.conf"

if [ ! -s "$rendered" ]; then
    echo "$0: FATAL $rendered is missing or empty — the server block was not rendered." >&2
    echo "$0: envsubst writes there because NGINX_ENVSUBST_OUTPUT_DIR=$out;" \
         "running as $(id -u):$(id -g), which must be able to write it." >&2
    exit 1
fi
