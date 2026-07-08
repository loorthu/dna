# DNA air-gapped deployment

Build the DNA backend + frontend images on an internet-connected machine, ship
one tar to an air-gapped prod server, and run there. DNA connects to the Vexa
stack over Docker's shared `vexa_vexa` network, so **bring Vexa up first**.

## What gets shipped

`dist/dna-images-<tag>.tar.gz` — `dna-backend`, `dna-frontend`, `mongo:7`.

Default tag is `airgap` (override by passing a tag arg to any script, or setting
`DNA_TAG` in `.env`).

## One-time: create your .env

```sh
cp docker/airgap/.env.example docker/airgap/.env
# Edit: ShotGrid / Gemini / Vexa keys, and the VITE_* frontend URLs.
```

⚠️ The **frontend is a static build** — `VITE_API_BASE_URL` / `VITE_WS_URL` are
baked in at build time and must be URLs the end user's **browser** can reach on
prod (e.g. `http://<prod-host>:8000`), not `localhost` inside the container.

## On the build machine (has internet)

```sh
cd ~/Documents/git/dna
docker pull mongo:7                # if not already present
./docker/airgap/build.sh           # builds dna-backend + dna-frontend
./docker/airgap/save.sh            # -> docker/airgap/dist/dna-images-<tag>.tar.gz
```

## On the prod server (air-gapped)

Prereqs: Docker + compose v2. The **Vexa stack must already be running** (it
creates the `vexa_vexa` network).

```sh
cd ~/dna                                   # repo checkout from your fork
cp /path/to/dna.env docker/airgap/.env     # your secrets
mkdir -p docker/airgap/gmail-credentials   # drop client_secret.json + token.json here
./docker/airgap/load.sh
./docker/airgap/up.sh
```

Stop with `./docker/airgap/down.sh` (add `--volumes` to wipe mongo).

## Notes vs. the dev compose

- The dev `backend/docker-compose.yml` bind-mounts `./src` for hot-reload and
  bakes secrets inline. This prod compose (`docker-compose.prod.yml`) does
  neither: it runs the built image and pulls all config from `.env`.
- `--no-build` / `pull_policy: never` guarantee it only uses the loaded images.
- Gmail credentials are mounted read-only from
  `${GMAIL_CREDENTIALS_HOST_DIR}` (default `docker/airgap/gmail-credentials/`).
