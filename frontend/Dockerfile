# Base images. Declared here, before the first FROM, because that is the only scope an ARG used
# by a FROM is read from. The args let a site pull the same images through its own registry mirror
# rather than Docker Hub, which is what an internal build host usually needs.
#
# nginx stays ALPINE whatever the mirror: docker-entrypoint.d/20-serve-as-share-user.sh is BusyBox
# `adduser`/`addgroup`, which a Debian-based nginx image does not have.
ARG NODE_IMAGE=node:20-alpine
ARG NGINX_IMAGE=nginx:alpine

# Stage 1: Build the application
FROM ${NODE_IMAGE} AS builder

WORKDIR /app

# Copy package files including lock file
COPY package.json package-lock.json ./
COPY packages/core/package*.json ./packages/core/
COPY packages/app/package*.json ./packages/app/

# Optional internal npm mirror for corporate / air-gapped builds where the build
# host can't reach the public registry. Default (empty) uses the public registry.
ARG NPM_REGISTRY=
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi

# Use npm install (not ci) so Rollup/Vite optional native bindings are resolved for the
# container platform (linux/amd64 in CI). npm ci can fail with MODULE_NOT_FOUND for
# @rollup/rollup-linux-*-musl due to optional dependency resolution (npm/cli#4828).
RUN npm install --include=dev || (sleep 30 && npm install --include=dev) || (sleep 60 && npm install --include=dev)
# Copy source code
COPY packages/core/ ./packages/core/
COPY packages/app/ ./packages/app/

# Build arguments for API URLs and authentication (baked into the static build)
ARG VITE_API_BASE_URL
ARG VITE_WS_URL
# Where the app is mounted. Empty/unset means the root, which is every deployment except one
# serving DNA under a prefix beside other tools. Vite bakes it into every asset URL and re-exposes
# it as import.meta.env.BASE_URL; the runtime half is APP_BASE_PATH in default.conf.template, and
# the two must agree.
ARG VITE_BASE_PATH
ARG VITE_AUTH_PROVIDER=google
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_FEATURE_FOLLOW_ALONG
ARG VITE_FOLLOW_ALONG_BROKER_URL
ARG VITE_FOLLOW_ALONG_TOPIC
ARG VITE_FOLLOW_ALONG_SESSIONS_URL
ARG VITE_FEATURE_NOTE_QC
ARG VITE_FEATURE_TRANSCRIPT_PUBLISH
ARG VITE_FEATURE_NOTE_LINKS
ARG VITE_FEATURE_NOTE_SUBJECT
ARG VITE_FEATURE_TRANSCRIPTION
ARG VITE_FEATURE_IN_REVIEW
ARG VITE_FEATURE_AI
ARG VITE_PRODTRACK_TAB_SYNC_EXTENSION_ID
ARG VITE_PRODTRACK_TAB_SYNC_INSTALL_URL

# Set environment variables for build
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_URL=$VITE_WS_URL
ENV VITE_BASE_PATH=$VITE_BASE_PATH
ENV VITE_AUTH_PROVIDER=$VITE_AUTH_PROVIDER
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_FEATURE_FOLLOW_ALONG=$VITE_FEATURE_FOLLOW_ALONG
ENV VITE_FOLLOW_ALONG_BROKER_URL=$VITE_FOLLOW_ALONG_BROKER_URL
ENV VITE_FOLLOW_ALONG_TOPIC=$VITE_FOLLOW_ALONG_TOPIC
ENV VITE_FOLLOW_ALONG_SESSIONS_URL=$VITE_FOLLOW_ALONG_SESSIONS_URL
ENV VITE_FEATURE_NOTE_QC=$VITE_FEATURE_NOTE_QC
ENV VITE_FEATURE_TRANSCRIPT_PUBLISH=$VITE_FEATURE_TRANSCRIPT_PUBLISH
ENV VITE_FEATURE_NOTE_LINKS=$VITE_FEATURE_NOTE_LINKS
ENV VITE_FEATURE_NOTE_SUBJECT=$VITE_FEATURE_NOTE_SUBJECT
ENV VITE_FEATURE_TRANSCRIPTION=$VITE_FEATURE_TRANSCRIPTION
ENV VITE_FEATURE_IN_REVIEW=$VITE_FEATURE_IN_REVIEW
ENV VITE_FEATURE_AI=$VITE_FEATURE_AI
ENV VITE_PRODTRACK_TAB_SYNC_EXTENSION_ID=$VITE_PRODTRACK_TAB_SYNC_EXTENSION_ID
ENV VITE_PRODTRACK_TAB_SYNC_INSTALL_URL=$VITE_PRODTRACK_TAB_SYNC_INSTALL_URL

# Build the application (vite handles transpilation, skip tsc type checking)
WORKDIR /app/packages/app
RUN npx vite build

# Stage 2: Serve with nginx
FROM ${NGINX_IMAGE}

# nginx server block as a TEMPLATE — the base image runs envsubst on it at container start,
# substituting ${BACKEND_URL} (the reverse-proxy target for /api and /ws), ${APP_BASE_PATH} and
# the rest. Output lands in NGINX_ENVSUBST_OUTPUT_DIR (set below), which our nginx.conf includes.
COPY default.conf.template /etc/nginx/templates/default.conf.template

# Runs before nginx starts (the base image sources everything in here). Runs the workers as the
# identity that owns the recordings share when NGINX_UID/NGINX_SHARE_GID are set — see the script
# for why neither `group_add` nor a supplementary group is enough.
COPY docker-entrypoint.d/20-serve-as-share-user.sh /docker-entrypoint.d/20-serve-as-share-user.sh

# Runs after the envsubst step and refuses to start if the server block was not rendered — see the
# script for why that failure is otherwise silent.
COPY docker-entrypoint.d/25-require-rendered-config.sh /docker-entrypoint.d/25-require-rendered-config.sh

# Copy built files from builder stage
COPY --from=builder /app/packages/app/dist /usr/share/nginx/html

# Where the app is mounted, read by default.conf.template. Declared EMPTY rather than left unset:
# envsubst only replaces variables present in the environment, so an unset one would leave the
# literal ${APP_BASE_PATH} in the rendered config and nginx would refuse to start.
ENV APP_BASE_PATH=

# ── Running under an arbitrary, non-root UID (OpenShift assigns one per namespace) ─────────────
#
# Render the templates into /tmp instead of /etc/nginx/conf.d. The stock
# 20-envsubst-on-templates.sh checks that its output directory is writable and, when it is not,
# logs an error and CARRIES ON — so nginx starts and serves the stock welcome page instead of DNA.
# A world-writable output directory removes that failure rather than depending on file modes.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/nginx-conf.d

# nginx.conf must then include /tmp rather than conf.d, and the pid and the worker temp
# directories have to leave /var/run and /var/cache, which the arbitrary UID cannot write.
COPY nginx.conf /etc/nginx/nginx.conf

# The workers still spill request bodies and proxied responses to /var/cache/nginx. An arbitrary
# UID is always in GID 0, so group-owning these is what makes them writable without knowing it.
RUN mkdir -p /tmp/nginx-conf.d \
    && chmod 1777 /tmp/nginx-conf.d \
    && chgrp -R 0 /var/cache/nginx /etc/nginx \
    && chmod -R g=u /var/cache/nginx /etc/nginx

# Expose port 8080 (Cloud Run expects this)
EXPOSE 8080

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
