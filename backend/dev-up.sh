#!/bin/bash
# Bring up the DNA dev stack, connecting to the full Vexa stack running separately.
# Start Vexa first: cd ~/Documents/git/vexa && make -f deploy/compose/Makefile up
# Usage:
#   ./dev-up.sh    # start DNA services

set -e
cd "$(dirname "$0")"

VEXA_API_PORT=18056   # external host port (internal is 8000)
VEXA_ADMIN_TOKEN="changeme"

COMPOSE="docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -f docker-compose.local.vexa.yml"

# --- Start ---

echo "==> Starting DNA services..."
$COMPOSE up -d

# --- Wait for Vexa API ---

echo "==> Waiting for Vexa API to be ready (port $VEXA_API_PORT)..."
for i in $(seq 1 40); do
  if curl -sf "http://localhost:$VEXA_API_PORT/" > /dev/null 2>&1; then
    echo "    Vexa API is ready."
    break
  fi
  if [[ $i -eq 40 ]]; then
    echo "    ERROR: Vexa API did not become ready. Is the Vexa stack running?"
    echo "    Start it with: cd ~/Documents/git/vexa && make -f deploy/compose/Makefile up"
    exit 1
  fi
  sleep 3
done

# --- Bootstrap Vexa user + token ---

USER_EMAIL="dna-local@example.com"
USER_NAME="DNA Local Dev"

# Check if the token already in docker-compose.local.yml still works with full scope.
# We validate against /meetings (requires browser scope) not just /bots/status (bot scope only),
# so a token with insufficient scopes gets regenerated rather than silently reused.
CURRENT_TOKEN=$(grep 'VEXA_API_KEY=' docker-compose.local.yml 2>/dev/null | cut -d= -f2- | tr -d ' ' || true)
if [[ -n "$CURRENT_TOKEN" ]] && curl -sf "http://localhost:$VEXA_API_PORT/meetings" \
    -H "X-API-Key: $CURRENT_TOKEN" > /dev/null 2>&1; then
  echo "==> Vexa token is valid, skipping bootstrap."
else
  echo "==> Bootstrapping Vexa user and API token..."

  # Create or retrieve user
  USER_RESPONSE=$(curl -sf -X POST "http://localhost:$VEXA_API_PORT/admin/users" \
    -H "X-Admin-API-Key: $VEXA_ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"$USER_EMAIL\", \"name\": \"$USER_NAME\"}")
  USER_ID=$(echo "$USER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "    User: $USER_EMAIL (id=$USER_ID)"

  # Create a new token
  TOKEN_RESPONSE=$(curl -sf -X POST \
    "http://localhost:$VEXA_API_PORT/admin/users/$USER_ID/tokens?scopes=bot,browser,tx&name=dna-local" \
    -H "X-Admin-API-Key: $VEXA_ADMIN_TOKEN")
  NEW_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
  echo "    Token: $NEW_TOKEN"

  # Write token into docker-compose.local.yml
  sed -i "s|VEXA_API_KEY=.*|VEXA_API_KEY=$NEW_TOKEN|" docker-compose.local.yml
  echo "    Updated VEXA_API_KEY in docker-compose.local.yml"

  # Restart DNA API so it picks up the new token
  echo "==> Restarting DNA API to apply new token..."
  $COMPOSE restart api
fi

# --- Done ---

echo ""
echo "==> Stack is up."
echo "    DNA API:       http://localhost:8000"
echo "    DNA Frontend:  http://localhost:5173"
echo "    Vexa API:      http://localhost:$VEXA_API_PORT"
echo "    Vexa Dashboard: http://localhost:3001"
