# DNA air-gapped deployment

Runs DNA (backend + frontend + mongo) as **two independent images** on an
air-gapped host. **Vexa runs on a different machine** — DNA reaches it over the
network via `VEXA_API_URL`.

Two ways to get the images:
- **Build on the prod host** using the internal Artifactory (default here), or
- **Transfer** prebuilt images (`save.sh` → copy → `load.sh`).

## Images

| Image | What |
|---|---|
| `dna-backend` | FastAPI/uvicorn API (port 8000) |
| `dna-frontend` | nginx serving the static Vite build (port 8080 → host 8081) |
| `mongo:7` | DNA's database |

## One-time: create your .env

```sh
cp docker/airgap/.env.example docker/airgap/.env
# Fill in: ShotGrid/Gemini keys, VEXA_API_URL (the vexa host), VEXA_API_KEY,
# the Artifactory mirrors (for building on prod), and the VITE_* browser URLs.
```

Key settings for the split topology:
- `VEXA_API_URL=http://<vexa-host>:18056` — where vexa runs (e.g. `160.33.19.70`).
- `VEXA_API_KEY` — mint it on the **vexa** host: `./docker/airgap/mint-token.sh`.
- `VITE_API_BASE_URL=http://<dna-host>:8000` — baked into the frontend; must be
  reachable by the **end user's browser** (e.g. `http://bear0315:8000`).
- `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` / `NPM_REGISTRY` — Artifactory, for building on prod.

## Build on prod (Artifactory)

```sh
cd ~/dna
mkdir -p docker/airgap/gmail-credentials   # drop client_secret.json + token.json here
./docker/airgap/build.sh      # docker compose build, pip/npm via Artifactory
./docker/airgap/up.sh         # start mongo + backend + frontend
```

## Or transfer prebuilt images

On an internet machine (leave the Artifactory vars empty so pip/npm use public):
```sh
./docker/airgap/build.sh && ./docker/airgap/save.sh   # -> dist/dna-images-<tag>.tar.gz
```
Copy `dist/*` to prod, then:
```sh
./docker/airgap/load.sh && ./docker/airgap/up.sh
```

Stop with `./docker/airgap/down.sh` (add `--volumes` to wipe mongo).

## Notes
- **No shared docker network with vexa** — DNA calls vexa over the network, so
  the prod host just needs routable access to `VEXA_API_URL`.
- **Frontend URL is baked at build time.** If the browser-facing host/port
  changes, rebuild the frontend.
- **CORS:** the frontend is a separate origin (`:8081`) from the API (`:8000`);
  if the browser is blocked, set `CORS_ORIGINS=http://<dna-host>:8081` in `.env`.
- Gmail credentials mount read-only from `docker/airgap/gmail-credentials/`.
