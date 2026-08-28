# DNA deployment — backend here, frontend on air-gapped prod

DNA's **backend needs internet** (Gemini summarization, Gmail), so it runs on an
internet-connected machine alongside vexa. The **frontend runs on the air-gapped
prod host** and reverse-proxies API + WebSocket back to that backend — so the
end user's browser only ever talks to prod (no CORS, no direct access to the
backend host needed).

```
  browser ──http──▶  prod frontend (nginx, :8081)
                        │  /api/*      ──proxy────▶  DNA backend  (this machine :8000)
                        │  /ws         ──proxy────▶  DNA backend  /ws
                        │  /recordings/ ─serves───   the recordings share (local, Range)
                        └  /           ──serves───   the SPA

                     collector (same host)
                        └  pulls each meeting's media through the DNA backend,
                           writes it to the share, then releases the upstream copy
```

## Backend (this internet machine)

Runs via the normal dev stack (`backend/dev-up.sh`) — it already has the
ShotGrid/Gemini/Vexa config and reaches vexa. It listens on `:8000`, which must
be reachable from the prod host (the frontend proxies to it).

## Frontend (air-gapped prod host)

`docker/airgap/` builds & runs **only** the frontend (nginx + static SPA).

### One-time: two env files, layered

The scripts read **two** files, upstream's first and this deployment's second.
Compose takes the last definition of a repeated key, so `docker/airgap/.env`
overrides only what the deployment genuinely changes and inherits the rest:

```sh
# 1. upstream's home for VITE_* — the ASWF-documented step
cp frontend/packages/app/.env.example frontend/packages/app/.env
#    set VITE_FEATURE_FOLLOW_ALONG / VITE_FOLLOW_ALONG_* here, once

# 2. this deployment's overrides + build mechanics
cp docker/airgap/.env.example docker/airgap/.env
# set BACKEND_URL=http://<backend-host>:8000  (e.g. 160.33.19.70:8000)
#     RECORDING_NETWORK_PATH = the real share mount
#     NPM_REGISTRY = Artifactory (to build on prod)
```

**No credentials go in `docker/airgap/.env`.** They live where the ASWF upstream
expects them — backend secrets inline in `backend/docker-compose.local.yml`
(from its tracked `example.` copy), frontend config in
`frontend/packages/app/.env`, vexa's in that repo's `deploy/compose/.env`. So a
credential arriving from upstream has exactly one home, and no value is written
in two places where the copies could drift.

One limit worth knowing: layering shares the **value**, not the **declaration**.
Compose passes only the build args `docker-compose.frontend.yml` lists under
`args:`, so a brand-new `VITE_*` from upstream needs one line added there before
it reaches the image — but never a second copy of its value.

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

## Meeting recordings

`collector/` (at the repo root — it belongs to the recording feature, not to this
deployment, which only wires it up) runs alongside the frontend and takes custody of each meeting's
recording: it mirrors the media out of Vexa through the DNA backend while the meeting runs, muxes
the audio in, writes the finished MP4 to `RECORDING_NETWORK_PATH`, records it in DNA, and only
then deletes the upstream copy. nginx serves that same path at `/recordings/`, so playback is a
local file with native Range support — no proxy hop, and seeking is free.

Set `RECORDING_NETWORK_PATH` in `.env` to the real mount before starting: it is used inside both
containers *and* recorded in DNA as the file's location, so it has to be the same string
everywhere. See `collector/README.md` for the ordering guarantee and how it resumes.

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
