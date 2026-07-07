#!/bin/bash
# Ensure exactly one Vexa browser_session is running and print its VNC URL.
# If multiple active sessions exist, keeps the most recent and stops the rest.
# Use this to get the URL where you authenticate with Google — that session
# is then shared by all authenticated meeting bots via CDP.
#
# Usage: ./browser-session.sh

set -e

VEXA_API_URL="http://localhost:18056"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve the real user's home even when invoked via sudo
REAL_HOME=$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)
VEXA_ENV="$REAL_HOME/Documents/git/vexa/.env"

# Prefer the DNA user token (docker-compose.local.yml) — browser_sessions are
# created under that user's account, not the Vexa admin account.
VEXA_API_KEY=$(grep 'VEXA_API_KEY=' "$SCRIPT_DIR/docker-compose.local.yml" 2>/dev/null | cut -d= -f2)
if [[ -z "$VEXA_API_KEY" ]]; then
    VEXA_API_KEY=$(grep -E '^VEXA_API_KEY=' "$VEXA_ENV" 2>/dev/null | cut -d= -f2)
fi
if [[ -z "$VEXA_API_KEY" ]]; then
    echo "ERROR: Could not find VEXA_API_KEY in docker-compose.local.yml or $VEXA_ENV"
    exit 1
fi

_get_sessions() {
    curl -sf "$VEXA_API_URL/meetings" -H "X-API-Key: $VEXA_API_KEY" 2>/dev/null \
    | python3 -c "
import sys, json
sessions = []
for m in json.load(sys.stdin).get('meetings', []):
    if m.get('platform') == 'browser_session' and m.get('status') == 'active' and m.get('bot_container_id'):
        sessions.append((m['id'], m['bot_container_id'], m.get('native_meeting_id', '')))
for s in sorted(sessions, key=lambda x: x[0], reverse=True):
    print(f'{s[0]}\t{s[1]}\t{s[2]}')
" 2>/dev/null || true
}

# --- Cull redundant sessions, keep most recent ---
echo "==> Checking for active browser_sessions..."
SESSIONS=$(_get_sessions)
if [[ -z "$SESSIONS" ]]; then
    SESSION_COUNT=0
else
    SESSION_COUNT=$(echo "$SESSIONS" | wc -l | tr -d ' ')
fi

if [[ "$SESSION_COUNT" -gt 1 ]]; then
    echo "    Found $SESSION_COUNT sessions — keeping most recent, stopping others..."
    while IFS=$'\t' read -r id container native_id; do
        [[ -z "$id" ]] && continue
        echo "    Stopping redundant session: meeting $id ($container)"
        curl -sf -X DELETE "$VEXA_API_URL/bots/browser_session/$native_id" \
            -H "X-API-Key: $VEXA_API_KEY" > /dev/null 2>&1 || true
        docker stop "$container" 2>/dev/null || true
    done <<< "$(echo "$SESSIONS" | tail -n +2)"
    SESSIONS=$(echo "$SESSIONS" | head -1)
    SESSION_COUNT=1
fi

# --- Use existing or create new ---
if [[ "$SESSION_COUNT" -eq 1 ]]; then
    CONTAINER=$(echo "$SESSIONS" | cut -f2)
    MEETING_ID=$(echo "$SESSIONS" | cut -f1)
    echo "    Using existing session: meeting $MEETING_ID ($CONTAINER)"
else
    echo "    None found. Creating browser_session..."
    curl -sf -X POST "$VEXA_API_URL/bots" \
        -H "X-API-Key: $VEXA_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"mode": "browser_session"}' > /dev/null

    echo "    Waiting for container to start..."
    for i in $(seq 1 20); do
        SESSIONS=$(_get_sessions)
        CONTAINER=$(echo "$SESSIONS" | head -1 | cut -f2)
        [[ -n "$CONTAINER" ]] && break
        sleep 2
    done

    if [[ -z "$CONTAINER" ]]; then
        echo "ERROR: browser_session did not become active after 40s."
        echo "       Check: docker logs \$(docker ps -q --filter name=browser-session | head -1)"
        exit 1
    fi
    echo "    Container started: $CONTAINER"
fi

# --- Get container IP ---
IP=$(docker inspect "$CONTAINER" 2>/dev/null | python3 -c "
import sys, json
nets = json.load(sys.stdin)[0]['NetworkSettings']['Networks']
for net in nets.values():
    ip = net.get('IPAddress', '')
    if ip:
        print(ip)
        break
" 2>/dev/null || true)

if [[ -z "$IP" ]]; then
    echo "ERROR: Could not get IP for container '$CONTAINER'."
    exit 1
fi

echo ""
echo "    VNC URL: http://$IP:6080/vnc_auto.html"
echo ""
echo "    Open this in your browser and log into Google."
echo "    All authenticated meeting bots will share this Chrome session."
