# Stage 1: Build the application
FROM node:20-alpine AS builder

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

# Set environment variables for build
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_URL=$VITE_WS_URL
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

# Build the application (vite handles transpilation, skip tsc type checking)
WORKDIR /app/packages/app
RUN npx vite build

# Stage 2: Serve with nginx
FROM nginx:alpine

# nginx server block as a TEMPLATE — the base image runs envsubst on it at
# container start, substituting ${BACKEND_URL} (the reverse-proxy target for
# /api and /ws). Output lands in /etc/nginx/conf.d/default.conf, which the base
# nginx.conf already includes.
COPY default.conf.template /etc/nginx/templates/default.conf.template

# Runs before nginx starts (the base image sources everything in here). Puts the worker user in
# the share's group when NGINX_SHARE_GID is set — see the script for why group_add cannot.
COPY docker-entrypoint.d/20-join-share-group.sh /docker-entrypoint.d/20-join-share-group.sh

# Copy built files from builder stage
COPY --from=builder /app/packages/app/dist /usr/share/nginx/html

# Expose port 8080 (Cloud Run expects this)
EXPOSE 8080

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
