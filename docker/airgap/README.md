# DNA deployment — backend here, frontend on air-gapped prod

DNA's **backend needs internet** (Gemini summarization, Gmail), so it runs on an
internet-connected machine alongside vexa. The **frontend runs on the air-gapped
prod host** and reverse-proxies API + WebSocket back to that backend — so the
end user's browser only ever talks to prod (no CORS, no direct access to the
backend host needed).

```
  browser ──http──▶  prod frontend (nginx, :8081)
                        │  /api/*  ─────proxy────▶  DNA backend  (this machine :8000)
                        │  /ws     ─────proxy────▶  DNA backend  /ws
                        └  /       ─────serves────  the SPA
```

## Backend (this internet machine)

Runs via the normal dev stack (`backend/dev-up.sh`) — it already has the
ShotGrid/Gemini/Vexa config and reaches vexa. It listens on `:8000`, which must
be reachable from the prod host (the frontend proxies to it).

## Frontend (air-gapped prod host)

`docker/airgap/` builds & runs **only** the frontend (nginx + static SPA).

### One-time: .env
```sh
cp docker/airgap/.env.example docker/airgap/.env
# set BACKEND_URL=http://<backend-host>:8000  (e.g. 160.33.19.70:8000)
#     NPM_REGISTRY = Artifactory (to build on prod)
```

### Build on prod (Artifactory) + run
```sh
cd ~/dna && git pull <your-remote> bot-authentication
./docker/airgap/build.sh      # docker compose build, npm via Artifactory
./docker/airgap/up.sh         # nginx serving SPA + proxying to BACKEND_URL
```
Open `http://<prod-host>:8081`. Stop with `./docker/airgap/down.sh`.

### Or transfer a prebuilt image
On an internet machine (leave `NPM_REGISTRY` empty → public):
`./docker/airgap/build.sh && ./docker/airgap/save.sh` → copy `dist/*` → prod
`./docker/airgap/load.sh && ./docker/airgap/up.sh`.

## How the wiring works
- **`VITE_API_BASE_URL=/api`** (relative) — the SPA calls `/api/...`; nginx
  proxies `/api/` → `${BACKEND_URL}/` (prefix stripped).
- **`VITE_WS_URL`** empty — the app derives `ws://<page-host>/ws`; nginx proxies
  `/ws` → `${BACKEND_URL}/ws` (with upgrade headers).
- **`BACKEND_URL`** is a **runtime** env (nginx `envsubst`), so you can repoint
  the backend without rebuilding the image.

## Notes
- No CORS config needed — the browser sees a single origin (the frontend).
- Confirm the prod host can reach the backend: `curl http://<backend-host>:8000/health`.
- `node:20-alpine` frontend build can occasionally hit the Rollup musl bug; the
  Dockerfile retries, else switch that stage to `node:20-slim`.
- `docker-compose.prod.yml` (all-in-one: mongo+api+frontend on one host) is kept
  for reference but isn't used in this split.
