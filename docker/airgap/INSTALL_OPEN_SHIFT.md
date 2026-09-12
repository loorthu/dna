# Install & Deploy — OpenShift (`sg` namespace)

DNA's front end on OpenShift, at `https://sg.spimageworks.com/dna/`, beside the other ShotGrid
admin tools. Two pods:

- **`sg-dna`** — nginx serving the SPA and reverse-proxying the API, the WebSocket and the review
  player's session directory. Also serves archived recordings straight off the share.
- **`sg-dna-collector`** — a headless worker that mirrors each meeting recording out of Vexa
  *through* the DNA backend, writes the finished MP4 to the share, and only then releases the
  upstream copy.

**The DNA backend does not move.** It runs on the internet-connected host (it needs Gemini and
Gmail) and both pods reach out to it. There is no `sg`-namespace backend to deploy.

This repo builds and pushes the images. It does **not** contain manifests: the `sg` namespace is
ArgoCD-managed from <https://gitlab.spimageworks.com/spi/dev/dev-ops/k8s-sg>, which the platform
team owns. This document is the interface between the two.

---

## Architecture

```
sg.spimageworks.com
  /dna/  ──▶  sg-admin-proxy  ──▶  sg-dna-service:8080  ──▶  sg-dna pod
                                                                │  /dna/api/  ──▶ DNA backend :8000  (off-cluster)
                                                                │  /dna/ws    ──▶ DNA backend /ws
                                                                │  /dna/recordings/ ─ served off the share
                                                                └  /dna/      ──▶ the SPA

sg-dna-collector pod  ──▶ DNA backend :8000   (pulls each recording)
                      └─▶ the share            (writes the archive)
```

`/dna/` reaches the pod **with the prefix intact** — nothing strips it. nginx matches on the full
path, and the SPA's own asset URLs are built with the same prefix at build time.

---

## What the platform team needs

### `sg-dna` (UI)

| Item | Value |
|---|---|
| Image | `docker-local.artifactory.spimageworks.com/gitlab/spi/dev/infrastructure/web/dna-ui:<version>` |
| Container port | `8080` (nginx) |
| Service | `sg-dna-service` → 8080 |
| App sub-path | `/dna/` |
| Liveness / readiness | `GET /dna/healthz` — HTTP 200 |
| Probe timing | `initialDelaySeconds: 10`, `periodSeconds: 30`, `timeoutSeconds: 10`, `failureThreshold: 3` |
| `runAsUser` / `runAsGroup` | **Pinned to the share's uid:gid** — see [The uid](#the-uid-both-pods) |
| Volumes | `/shots` and `/net`, **read-only**, at those exact paths — see [The mounts](#the-mounts-both-pods) |
| `envFrom` | `secretRef: secret-sg-dna` |
| Replicas | Any — stateless |

Secret keys (`secret-sg-dna`), all written by `./docker/airgap/oc-secret.sh ui`:

**All seven are always present**, written empty when `.env` does not set them. The Secret's key
set is fixed and does not vary with the operator's `.env` — see [Setting them](#setting-them).

| Key | What it is | If it were missing |
|---|---|---|
| `BACKEND_URL` | the DNA backend, e.g. `http://<backend-host>:8000` | nginx `[emerg] unknown "backend_url" variable` — **crash-loop** |
| `REVIEW_SESSIONS_URL` | the review player's session directory | **crash-loop**, same mechanism. The image defaults it to a dead local port, so unset means "feature off", not "pod down" |
| `RECORDING_NETWORK_PATH` | the share ROOT — nginx aliases `/dna/recordings/` onto it | **crash-loop**, same mechanism |
| `APP_BASE_PATH` | `/dna`. Empty means the root | safe — the image declares it empty |
| `COLLECTOR_SITE` | this deployment's name, sent as `X-DNA-Site` on every bot dispatch, which routes the recording to the collector below. Same value in both Secrets; unique across every DNA deployment | safe — the image declares it empty; empty means the unrouted queue |
| `COLLECTOR_UID` | the share's uid — nginx SERVES as the identity that WROTE the files | no uid switch. On OpenShift the SCC pins `runAsUser` and the entrypoint only warns, so here these are a consistency check rather than the mechanism |
| `COLLECTOR_GID` | the share's gid | as above |

### `sg-dna-collector`

| Item | Value |
|---|---|
| Image | `…/dna-collector:<version>` |
| Container port | **none** — no listener, no Service, nothing in the cluster calls it |
| Probes | **No HTTP probe is possible.** Either none, or an `exec` on the staging directory. It refuses to start when misconfigured (below), so a crash-loop is the signal. |
| Replicas / strategy | **`1` / `Recreate`** — see [Not scalable](#not-scalable) |
| `runAsUser` / `runAsGroup` | **Pinned to the share's uid:gid** |
| Volumes | `/shots` and `/net`, **read-write**, at those exact paths; plus an RWO PVC at `/staging` |
| `envFrom` | `secretRef: secret-sg-dna-collector` |

Secret keys (`secret-sg-dna-collector`), written by `./docker/airgap/oc-secret.sh collector`:

**All five are always present**, written empty when `.env` does not set them.

| Key | What it is | If it were missing |
|---|---|---|
| `BACKEND_URL` | the DNA backend (the collector calls it directly, not via nginx) | **the quietest failure in either image**: falls back to `http://localhost:8000`, polls itself forever, logs a retry per pass, and stays "healthy" — there is no HTTP probe to contradict it |
| `RECORDING_NETWORK_PATH` | the share root | clean crash-loop from `_require_reachable`, naming the setting |
| `RECORDING_ARCHIVE_DIR` | where a show's recordings are filed, with `{show}` as the placeholder | falls back to `<root>/{show}` — files land in a layout the site did not choose |
| `COLLECTOR_SITE` | which side's recordings this collector archives | empty means the unrouted queue. Harmless with one collector; silent cross-wiring with more than one |
| `COLLECTOR_STAGING_DIR` | fixed at `/staging` — the PVC mount path is a property of the manifest, so the script hardcodes it and it is not read from `.env` | n/a |

**Deliberately not here.** These reach the collector through nothing and are not in its Secret:

- `RECORDING_ARCHIVE_TIMEZONE` — read by `archive_timezone()` → `archive_name()`, which runs in
  the **backend**. The collector asks the backend for its archive name over HTTP, so the key did
  nothing on this pod. It belongs on the backend service.
- `DNA_API_TOKEN` — DNA authenticates people, not programs. Every route resolves a bearer token to
  a *user* through the configured provider, so there is nothing a headless collector can present.
  The key was unvalidated under `AUTH_PROVIDER=none` and would have 401'd under `google`. Turning
  auth on needs a machine-auth design first; a static string in a Secret was never one.
- `COLLECTOR_POLL_SECONDS`, `COLLECTOR_MAX_PLAYLISTS`, `RECORDING_POSTER_LEAD_SECONDS`,
  `LOG_LEVEL` — tuning knobs whose defaults live in the code that reads them (10s, 25, 2s, `INFO`).
  A site that needs one adds it to `OPTIONAL` in `oc-secret.sh` **and** to the Deployment together.

### Setting them

Both Secrets are written from `docker/airgap/.env` layered with `.env.openshift`. **Every key is
spelled the same in all three places** — in `.env`, in the Secret, and in the container that reads
it — so what you set is what lands. There is no rename step. `COLLECTOR_STAGING_DIR` is the single
exception, and it is not read from `.env` at all: the script fixes it at `/staging`.

Four values feed **both** Secrets, so editing one for one pod also changes the other:

- `BACKEND_URL` — the backend's real address in both cases, never `/dna/api`. nginx strips the
  path prefix before proxying, and the collector calls the backend directly.
- `COLLECTOR_SITE` — **must** match across the two: nginx stamps it as `X-DNA-Site` and that
  header is what routes the recording to this namespace's collector.
- `RECORDING_NETWORK_PATH` — the share root, for the pod that writes it and the pod that serves it.
- `COLLECTOR_UID` / `COLLECTOR_GID` — one identity: the collector runs as it, and nginx serves as
  it. They reach the UI Secret too, which is why they are not named for either container.

### The Secret's key set is fixed

**Every key listed above is always written, empty when `.env` does not set it.** The key set is a
property of this repo, not of the operator's `.env`, so a manifest can rely on it.

That is a change, and it was made for a reason worth recording. The script used to omit any key
`.env` had not set, which produced:

```
Error: couldn't find key DNA_API_TOKEN in Secret sg/secret-sg-dna-collector
```

That is the kubelet, not the app. The Deployments name keys one at a time
(`env: valueFrom: secretKeyRef:`), and such a reference to an absent key is a
`CreateContainerConfigError` — the pod never starts. A value nobody had set became a pod nobody
could start. The sibling apps in this namespace never hit it, because they write their whole
`.env` including empty values.

> **Please switch to `envFrom: secretRef:`** — what the tables above have always specified, and
> what `sg-reports` and `sg-api` already do. With `envFrom`, extra keys are inert and absent ones
> harmless, so DNA's configuration surface can change without a manifest edit. Until then, every
> key added to or removed from a Secret is a two-sided change that must land on both sides
> together.

Nothing `VITE_*` appears in either Secret. Those are baked into the JS bundle at build time and are
already in the browser before a pod starts; a Secret cannot change them. Repointing the front end
means a rebuild and a new image tag, not a Secret edit and a rollout.

### Both pods

**Egress to the DNA backend** (`160.33.19.70:8000`). The collector pulls whole recordings through
it — expect **200–400 MB per meeting**.

---

## The three things that will decide whether this works

### The mounts (both pods)

Both pods need **`/shots` and `/net`, mounted at those exact absolute paths.**

`/shots/<show>/lib.recording/...` is a **symlink** onto the volume that show lives on:

```
/shots/kpop/lib.recording/pix/ref/dna/misc_srgbref8_mp4
  -> /net/vol1208/shots/kpop/lib.recording/pix/ref/dna/misc_srgbref8_mp4/
```

Mounting the share alone is not enough: the link resolves inside the container and its target does
not exist there, so the collector finds the directory unreachable and archives nothing, and nginx
serves 404s for files that are plainly on the host.

The paths must be **identical inside and outside**, because the same string is the share root for
nginx, for the collector, and for the relative path stored in Mongo as each recording's location.
Mounting at `/data` would break playback for every recording ever made.

> If the volumes underneath automount, a plain bind will not see them appear after the pod starts.
> Either mount the specific volumes, or make `/net` rshared on the node and request propagation.

**No other app in the `sg` namespace uses a persistent volume today** — DNA needs three across two
pods. Please say early if this is not something the cluster can offer, because it changes the shape
of the deployment rather than a detail of it.

### The uid (both pods)

Both pods must run with **the share's uid:gid as their PRIMARY identity** — `nonroot-v2` or a
custom SCC bound to the service account, with `runAsUser` and `runAsGroup` set. The default
`restricted-v2` arbitrary uid will not read or write the share.

`fsGroup` and `supplementalGroups` **do not work here.** The share is NFS, and the server discounts
the supplementary group list the client sends, deriving groups from the uid at its own end. This
was established twice, on the real share, with everything apparently correct (0644 files in 0755
directories):

1. `group_add` on the container — discarded. nginx's workers call `initgroups()` before `setuid()`,
   which replaces the supplementary list.
2. Adding the nginx user to the group — the worker genuinely carried the gid and nginx **still**
   logged `open(...) failed (13: Permission denied)`, because the server has never heard of uid 101.

What the share honours is the primary identity: `2443:20` and `65534:20` both read the file, and in
both gid 20 was primary. So the UI pod serves **as the identity that wrote the files** — which is
why the UI Secret carries `COLLECTOR_UID`/`COLLECTOR_GID` rather than a number chosen separately:
it is one identity, named for the side that writes, and nginx reads the very same two keys.

The image's own `USER 1000:1000` is the unprivileged default for a plain `docker run`; the SCC
overrides it, and the entrypoint says so in the log either way.

> The staging PVC keeps the ownership it is created with. Changing the uid later means recreating
> it — and abandoning any half-mirrored meeting inside, so do it between meetings.

### Not scalable

The collector is a **singleton per site**. Archive filenames and staging state are per-playlist
files in shared directories, so two collectors on one site double-fetch and race: each takes every
job, both mirror the same meeting, and the loser is left holding a partial mirror it can never
finish. That is not hypothetical — `backend/src/dna/site_routing.py` exists because it happened.

`replicas: 1`, `strategy: Recreate`. If a second collector ever runs anywhere, give each deployment
its own `COLLECTOR_SITE` — in **both** of its Secrets, the UI's and the collector's. Nothing is
configured on the backend: the front end names its side on each dispatch and its collector asks for
that name, so a site is one string in one place. Leave it empty everywhere and every collector
shares the unrouted queue, which is the race this exists to prevent.

---

## Routing

`sg.spimageworks.com/` is terminated by the `sg-admin-proxy` edge pod, which fans out to per-app
Services. DNA needs a block there, in the **sg-admin** repo
(`docker/proxy/proxy-locations.conf`), alongside the existing apps:

```nginx
location = /dna { absolute_redirect off; return 301 /dna/; }
location /dna/  { proxy_pass http://sg-dna-service:8080; }
```

`proxy_pass` with no URI part forwards the path unchanged, which is what DNA's nginx expects.
Bump `docker/proxy/VERSION` and roll that image.

**Sequence it after** `sg-dna` and `sg-dna-service` exist, or `/dna/` answers 502.

---

## Building and pushing

Requires Artifactory access and `docker login docker-local.artifactory.spimageworks.com`.

```bash
./docker/airgap/oc-build.sh ui
./docker/airgap/oc-run.sh   ui          # runs as uid 1000710000 — the OpenShift case
./docker/airgap/oc-push.sh  ui

./docker/airgap/oc-build.sh collector
./docker/airgap/oc-push.sh  collector
```

Configuration comes from `docker/airgap/.env` layered with `docker/airgap/.env.openshift` — the
same file the host deployment uses, plus the four keys the cluster changes. Bump
`docker/airgap/VERSION` before a release; only the versioned tag is pushed, never `:latest`.

The images are built by hand rather than by an OpenShift `BuildConfig` because the collector needs
a BuildKit **named build context** (`--build-context dna=backend/src/dna`) to take its collection
logic from the backend package, which the Docker build strategy cannot pass. This is the same model
`sg-admin` uses.

## Secrets and rollouts

```bash
./docker/airgap/oc-secret.sh ui --diff     # key names only, never values
./docker/airgap/oc-secret.sh ui
./docker/airgap/oc-rollout.sh ui           # envFrom is read at pod start, not live
./docker/airgap/oc-logs.sh collector
```

## Deploying a new image

**The `sg` namespace is managed by ArgoCD. Do not `oc set image`** — it will be reconciled back to
whatever the GitOps repo says. Ask the platform team to set the tag in
<https://gitlab.spimageworks.com/spi/dev/dev-ops/k8s-sg>; `oc-push.sh` prints the deployment name
and the full image path to hand over.

---

## Verifying a deployment

1. `https://sg.spimageworks.com/dna/` loads. In the network tab: assets under `/dna/`, the API
   under `/dna/api/`, and a WebSocket to `wss://sg.spimageworks.com/dna/ws`.
2. `./docker/airgap/oc-shell.sh ui`, then `ls -L` a known archive under `/shots`. A dangling
   symlink here means `/net` is missing — the failure that otherwise looks like a missing file.
3. `./docker/airgap/oc-logs.sh collector` shows the writability probe passing on **both** mounts,
   then the poll loop.
4. One real meeting end to end: mirrored, muxed, written under the show's dated directory, recorded
   in DNA, upstream copy released, and the Recording tab plays it back **with seeking** — Range
   requests served by nginx off the mount, not proxied.
5. Confirm the archive move used its copy fallback. The staging PVC and the share are different
   filesystems, so `os.replace` raises `EXDEV` and `shutil.copyfile` runs. That branch has only a
   unit test behind it, and this is the first deployment where it is the normal path.

## Known open questions

- **Follow Along is `ws://`, and this page is `https://`.** `VITE_FOLLOW_ALONG_BROKER_URL`
  (`ws://mq1.spimageworks.com:61614/stomp`) is opened **by the browser**. That works from a
  plain-HTTP host; from `https://sg.spimageworks.com/dna/` browsers block it as mixed content.
  Needs a `wss://` broker endpoint or a same-origin proxy. Only bites if Follow Along is enabled —
  the feature is unavailable unless both broker and topic are set.
- **`DNA_APP_BASE_URL` is one value on a shared backend.** Notes emails build review links from it.
  Pointing it at `https://sg.spimageworks.com/dna` changes the links for every front end that
  backend serves.
- **Auth.** DNA runs with `VITE_AUTH_PROVIDER=none` — no sign-in — while its neighbours on
  `sg.spimageworks.com` sit behind the shared Okta `sg-auth` service. DNA has `none` and Google
  OAuth, and no Okta path. Worth deciding before it goes live on that hostname.
