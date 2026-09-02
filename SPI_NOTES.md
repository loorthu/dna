# SPI notes — running the meeting-recording work at Imageworks

Site-specific operational knowledge: our hosts, our mounts, our package mirrors, and what was
measured on them. Kept apart from `.cursor/plans/meeting_recording_playback.plan.md`, which is the
design and belongs to the project, so the plan can be read (or contributed upstream) without
carrying Imageworks' network in it.

Its sibling on the Vexa side is that repository's `SPI_TODO.md`.

**What belongs here:** hostnames, IPs, mount paths, internal registry URLs, credentials handling,
machine-specific build recipes, and measurements taken on our hardware. **What does not:** how the
feature is designed or why — that is the plan.

---

## Where this stands (2026-08-25)

Phases 1–6 are done and verified on the DMZ box, which turned out to BE the internet-side prod
host rather than a stand-in for one — so the clock-skew worry that shaped the advice below does
not apply here: the bot and meeting-api genuinely share a host in production.

Still only provable on the air-gapped host: link bandwidth for a few hundred MB per meeting,
mount permissions and path identity, and resume across a genuinely slow transfer. Phase 7 (the
player) is not built.

The two sections that follow were written earlier, from a laptop, and are kept as the record of
what was known then — read their "phase 6 is next" framing as history, not as instruction.

---

## Deploying to the studio hosts

Phases 1–5 are built, committed and verified — but **verified on one laptop**, where
every host shares a clock, a filesystem and a loopback network. That is exactly the
environment in which this design's hardest failure modes cannot appear. Hence the
recommendation: **stand this up on the real hosts before building phase 6.**

### Why prod before phase 6, not after

Phase 6 computes `video_in = segment_wall_time − recording_t0`. `recording_t0` is the
bot's own clock on the Vexa host; the segment timestamps come from meeting-api. On one
laptop those are the same clock, so **Risk 5 (clock skew) is invisible by construction**
and a green phase 6 here would prove nothing about prod. Build it where the clocks can
actually disagree, or expect to verify it twice.

Risk 3 is also still open. The collector was designed for a slow, intermittent link —
resumable, per-part, verified — and has never met one. Everything measured so far ran
over loopback.

### What was NOT verifiable from the laptop

Roughly in order of how likely each is to bite:

1. **`_move`'s copy fallback is the production path.** In `recording_collector.py`,
   staging and the archive were one filesystem locally, so `os.replace` always
   succeeded. On prod the archive is a network mount, `os.replace` raises `EXDEV`, and
   the `shutil.copyfile` branch runs. It is the path that will always execute in
   production and the only one in the flow with just a unit test behind it.
2. **Does Artifactory mirror Debian?** The whole `imageio-ffmpeg`-instead-of-apt
   decision was made because that could not be checked from outside. If Artifactory
   *does* carry a deb mirror, apt was available all along and the wheel is merely a
   smaller, equally valid choice. Either way the collector image now has to prove it
   builds on prod (`PIP_INDEX_URL` → Artifactory) or be carried in via
   `save.sh`/`load.sh`.
3. **Mount permissions and path identity.** `RECORDING_NETWORK_PATH` is used *inside*
   the collector, *inside* nginx, and is recorded in Mongo as the file's location. All
   three must be the same string. The collector writes as root in-container; nginx must
   be able to read what it wrote.
4. **Link characteristics** — bandwidth and stability for ~200–400 MB per meeting.
5. **Clock agreement** between the Vexa host and meeting-api (see above).

### Suggested order

1. **Look before assuming** — establish what is actually running on each host.
2. **Deploy the internet side first.** The collector is inert until the backend it
   calls has `/recordings/pending` and `/recordings/{playlist_id}/audio`. That means
   the DNA backend on the DMZ box, plus the rebuilt Vexa bot image (it carries both the
   audio-anchor and leave-when-alone fixes).
3. **Stand up the collector on the airgapped host** against the real mount, and find
   out whether it builds there or must be transferred.
4. **One live meeting end to end,** measuring the link while it runs.
5. **Then phase 6**, against real clocks.

Steps 2 and 3 are where surprises are expected, and they are far cheaper to hit now
than with two more phases stacked on top.

### Deploying — the short version

Operational detail (image build order, the four places the VPN breaks TLS, how to run
the tests, the live test loop) is in `meeting_recording_playback.notes.md`. The
essentials:

- **DNA backend** bind-mounts `./src`, so a code change needs only
  `docker restart dna-backend`. A *recreate* is safe too: `VEXA_API_KEY` and the
  ShotGrid credentials are written inline in `backend/docker-compose.local.yml`
  (the upstream convention — that gitignored file is a copy of the tracked
  `example.docker-compose.local.yml`), so compose no longer depends on whatever
  happened to be exported in the shell that first started the stack.
- **Collector image** — `docker compose build` cannot pass `--build-context`, so build
  it with `docker build` (exact invocation in the notes). On prod, point
  `PIP_INDEX_URL`/`PIP_TRUSTED_HOST` at Artifactory.
- **`RECORDING_NETWORK_PATH`** must be set in `docker/airgap/.env` to the real mount
  before anything starts. It defaults to `./recordings`, which is fine for a laptop and
  wrong for prod.
- The collector talks to the backend **directly**, not through this host's nginx: it is
  a server-side client, so there is no single-origin requirement and no reason to add a
  proxy hop to several hundred MB per meeting.

### Known-failing checks that predate this work

Neither was introduced here; both are the owner's call.

- DNA `--cov-fail-under=90` fails. It was 87.41% before phase 5 and is 89% after. The
  gap is `email_service.py` at 0% (116 statements), unrelated to recordings.
- DNA `black --check` fails on `email_service.py`, `models/transcription.py` and
  `prodtrack_providers/shotgrid.py` — formatting drift from earlier commits.
  Reformatting them was deliberately reverted to keep the phase 5 diff focused.

### What phase 5 actually measured

- **The A/V offset is not a constant.** Two runs of identical code measured 1428 ms and
  123 ms. Any hardcoded or once-measured offset would have been wrong on one of them —
  which is why the bot now stamps both streams' start clocks and the collector pads by
  the difference.
- **The frame pacer holds.** 275.65 s of video against 275.4 s of wall clock, +0.09%
  over 4m35s including a long static stretch — the condition where screencast starves
  and video time could silently decouple.
- **Resume is exact.** A collection interrupted at 7 of 9 parts, with stray bytes
  appended to simulate a torn write, archived a file byte-for-byte identical to an
  uninterrupted run.

### A bug found along the way

The bot was leaving any meeting with exactly one other person in it, after ~2 minutes
(`fcf6457e` in the Vexa fork). It is unrelated to recording, but it truncated the first
live phase 5 test to 2m16s, and a dailies review with one supervisor would have hit it
every time. The count is of *other* participants and was read as counting everyone, so
1 meant "only me". Confirmed against the live Meet DOM, not inferred: the bot's own
tile carries no `data-participant-id` at all.

Worth carrying forward as a habit, not just a fix — **every test of that monitor
injected the count as a number**, so the timer's arithmetic was thoroughly covered
while what the number *meant* was never asserted. The monitor was well tested and still
wrong. Five of the bugs this work has found were invisible to unit tests.

---

## Running the stack on a development machine

Operational knowledge that is NOT recoverable from the code or the commits. The plan
(`meeting_recording_playback.plan.md`) says what to build and why; this says how to run it on this
laptop. Phases 1–5 are done and committed; Phase 6 (the cut list) is next.

### The VPN breaks TLS in four different places

Each needed a different fix. This is the single biggest time sink in the setup.

| Where | Symptom | Fix |
|---|---|---|
| host npm / pnpm | `SELF_SIGNED_CERT_IN_CHAIN` | `NODE_EXTRA_CA_CERTS=<roots.pem>` |
| Node inside a Docker build | corepack cannot fetch pnpm | CA baked into the base image |
| Chromium in the bot container | "Your connection is not private" | CA in the **NSS db** (`~/.pki/nssdb`), not the system store |
| pip / uv in a Docker build | cannot reach PyPI | `PIP_CERT` + `SSL_CERT_FILE` + `UV_NATIVE_TLS` |

Export the CA bundle once per session:

```sh
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > /tmp/roots.pem
security find-certificate -a -p /Library/Keychains/System.keychain >> /tmp/roots.pem
export NODE_EXTRA_CA_CERTS=/tmp/roots.pem
```

**Chromium is the non-obvious one.** `NODE_EXTRA_CA_CERTS` fixes the build and leaves the browser
broken, and `login-status` then reports `logged_in` anyway because Chrome keeps the original URL
behind a cert interstitial — so the probe sees `myaccount.google.com` and calls it success. If the
session browser looks logged in but nothing works, check TLS inside the container first:

```sh
docker exec vexa-browser-session-1 curl -s -o /dev/null -w '%{http_code}\n' https://accounts.google.com
```

### Images: build order matters

`python:3.12-slim` is retagged locally with the CA. BuildKit resolves `FROM` from the registry, so
it must be overridden explicitly per build:

```sh
# meeting-api  (context = repo root)
docker build --build-context python:3.12-slim=docker-image://vexa-python-ca:latest \
  -f core/meetings/services/meeting-api/Dockerfile -t vexaai/v012-meeting-api:v012 .

# gateway  (context = the SERVICE dir, not the repo root — a root context fails with "/src not found")
docker build --build-context python:3.12-slim=docker-image://vexa-python-ca:latest \
  -f core/gateway/services/gateway/Dockerfile -t vexaai/v012-gateway:v012 core/gateway/services/gateway
```

**The bot needs two steps, always.** `make bot` rebuilds the join-env base and wipes the CA patch,
so build from the Dockerfile directly and re-apply the CA layer afterwards — skipping the second
step leaves the session browser unable to reach Google:

```sh
docker build -t vexa/vexa-bot:dev -f core/meetings/services/bot/Dockerfile .
docker build -t vexa/vexa-bot:dev -f <scratch>/Dockerfile.ca2 <scratch>    # re-apply CA + NSS db
```

### Running tests (no local uv/pytest/tsx)

```sh
# python — meeting-api / gateway
docker run --rm -v "$PWD":/w -w /w/core/<...> -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  vexa-python-ca:latest bash -c 'pip install -q uv==0.9.22 && uv run --project . pytest -q'

# node — pnpm is via corepack; deps need one install with the CA exported
corepack pnpm install --filter @vexa/bot... --frozen-lockfile=false
corepack pnpm --filter @vexa/recording test

# DNA backend
cd backend && docker compose -f docker-compose.yml -f docker-compose.local.yml \
  run --rm --no-deps api python -m pytest -q --no-cov
```

### Stack bring-up

`deploy/compose/.env` is seeded from `.env.example` with three overrides: `BROWSER_IMAGE=vexa/vexa-bot:dev`,
`RECORDING_ENABLED=true`, `TRANSCRIBE_ENABLED=false` (no Whisper — turn on for Phase 6 alignment).

```sh
cd deploy/compose && docker compose -p vexa-v012 -f docker-compose.yml up -d --no-build \
  postgres redis minio minio-init admin-api gateway meeting-api runtime
make -s provision-token ADMIN_TOKEN=dev-admin-token     # mints the API key
```

Skip `agent-api`, `mcp`, `terminal` — `agent-api` has no published image and none are on the
recording path. Registry pulls time out through the VPN proxy; **retry, layers resume**.

Session browser (the human-authenticated one meeting bots attach to):

```sh
VNC_HOST_PORT=6080 EMAIL=self-host@vexa.ai ADMIN_TOKEN=dev-admin-token \
  deploy/compose/bin/browser-session.sh up          # noVNC at localhost:6080
```

Inspect object storage:

```sh
docker run --rm --network vexa-v012_vexa --entrypoint sh minio/mc:latest -c \
  'mc alias set v http://minio:9000 vexa-access-key vexa-secret-key >/dev/null && mc ls -r v/vexa/recordings'
```

### DNA → Vexa wiring

`backend/docker-compose.local.yml` (gitignored) carries `VEXA_API_URL=http://gateway:8000` and joins
the external `vexa-v012_vexa` network. The network join is **required**: the gateway publishes on
`127.0.0.1:18056`, which is loopback-bound and invisible to containers, so `host.docker.internal`
does not work either.

`VEXA_API_KEY` used to be passed as a shell variable, so it was baked into the running container and
**not persisted** — recreate `dna-backend` without it and every bot dispatch 400s (the provider
silently falls back to `https://api.cloud.vexa.ai` with an empty key). It is now written inline in
that same `backend/docker-compose.local.yml`, so a recreate keeps it.

Inline is not merely convenient, it is what `dev-up.sh` requires: `:47` greps `VEXA_API_KEY=` out of
that file to decide whether the current token still validates, and `:70` seds a freshly minted one
back in. Point the key at a `${VEXA_API_KEY}` interpolation instead and both halves break — the grep
returns the literal `${VEXA_API_KEY:-}`, validation always fails, and the sed then overwrites the
interpolation with a hardcoded token anyway.

### Live test loop

1. Dispatch: `POST /bots` with `authenticated: true, recording_enabled: true`.
2. **Verify the topology actually under test** — `docker inspect <container>` and check `cdpUrl` is
   set. Published upstream images ignore `authenticated`, so a stack running them silently tests the
   guest path instead of CDP attach. This cost a whole round of false confidence.
3. Watch parts land: poll the chunk index, or `mc ls` the session prefix.
4. The bot self-terminates ~2 min after the last human leaves, and its container is reaped.

Do not read `/master` mid-recording expecting a complete file — it is a snapshot of what existed
then. That used to freeze permanently; it now rebuilds, but the snapshot is still partial.

### Verification habits worth keeping

Three bugs this work found were invisible to unit tests and only appeared on a live run. Two more
were found by *distrusting a green test*:

- **A test that cannot fail is worse than no test.** The concurrent-chunk race test passed WITH the
  bug, because the in-memory fakes never suspend and `asyncio.gather` ran one upload to completion
  before starting the other. Verify red-before by reverting the fix.
- **Don't measure a file that is still being written.** Three drift measurements disagreed
  (−0.6%, +1.9%, +7.7%) purely because ffmpeg's on-disk lag varies. Compare a persisted anchor
  against a finished file instead.
- **`make ... | tail` hides failures** — the pipeline's exit status is `tail`'s. Two builds looked
  green when they had failed.

### Running the collector against the live stack

`dna-backend` bind-mounts `./src`, so backend changes need only `docker restart dna-backend`. A
recreate is fine as well — `VEXA_API_KEY` lives inline in `backend/docker-compose.local.yml`.

```sh
docker run -d --name dna-collector --network backend_default \
  -e DNA_API_URL=http://dna-backend:8000 -e COLLECTOR_STAGING_DIR=/staging \
  -e RECORDING_NETWORK_PATH=/net/media/dna-recordings -e COLLECTOR_POLL_SECONDS=10 \
  -v dna-collector-staging:/staging -v <host-archive-dir>:/net/media/dna-recordings \
  dna-collector:airgap
```

Build it with the CA base and public PyPI (`.env` points `PIP_INDEX_URL` at Artifactory, which is
unreachable from here). `docker compose build` cannot pass `--build-context`, so use `docker build`:

```sh
docker build -t dna-collector:airgap -f collector/Dockerfile \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  --build-context dna=backend/src/dna \
  --build-context python:3.11-slim=docker-image://dna-python311-ca:latest \
  collector
```

`dna-python311-ca` is `python:3.11-slim` with `/tmp/roots.pem` appended to its CA bundle plus
`PIP_CERT`/`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` — the same trick as `vexa-python-ca`, for 3.11.

**Re-running a collection.** Once a playlist is archived it drops out of `/recordings/pending`
(that is the point). To re-test, clear the archive fields and wipe the staging volume:

```sh
docker exec dna-mongo mongosh --quiet dna --eval '
  db.playlist_metadata.updateOne({playlist_id:460115},{$unset:{recording_network_path:"",
    recording_sha256:"",vexa_recording_id:"",recording_media_file_id:"",
    recording_start_time_utc:"",recording_duration_seconds:""}})'
docker volume rm dna-collector-staging
```

**Inspecting the live Meet DOM** — how the alone-monitor bug was confirmed rather than guessed.
Only `playwright-core` is in the bot image, and pnpm's layout means it must be imported by path:

```js
import pw from '/app/node_modules/.pnpm/playwright-core@1.56.0/node_modules/playwright-core/index.js';
const b = await pw.chromium.connectOverCDP('http://<session-browser-ip>:9223');
```

Run it with `-w /app` on the `vexa-v012_vexa` network. The bot's `cdpUrl` env gives the address.
Attaching a second CDP client alongside the bot's own did not disturb the recording.

### Outstanding (see also the known-failing checks above)

- `gate:config-contract` is RED, pre-existing from `cb09e142`: `BROWSER_SESSION_NAME_PREFIX` and
  `BROWSER_SESSION_CDP_PORT` are read in `bot_spawn/service.py` but not declared in
  `config.v1.json`. Two lines; owner's call.
- Vexa `5160dd55` carries a sealed-contract change (`api.v1` resealed). Per AGENTS.md the seal diff
  is the review artifact and wants a human on the PR — it should not ride in on green gates.
- The CA patches live only in local images. If this becomes the regular test bed, that injection
  belongs in the Dockerfiles behind a build arg, or every contributor on the VPN rediscovers it.
- Playback is served from `RECORDING_NETWORK_PATH`, which on this laptop is a scratch directory.
  A real mount has to exist on prod before Phase 7 means anything.

---

## Narrowing the Publish path to what our ShotGrid actually does (2026-09-01)

Audited what clicking **Publish** sends to ShotGrid, then turned off the parts that were being
offered without working. All of it is reversible; nothing about the note body, subject, status or
attachment path changed.

**What Publish does reach SG with:** a `Note` created under the author's own login (script key +
`sudo_as_login`), linked to the Version plus the Playlist plus the version's parent Shot/Asset;
`Version.sg_status_list`; and file attachments. A duplicate guard on
`project + version link + subject + content` means an identical re-publish returns the existing
note rather than making a second one.

**Publish sends no mail from DNA.** `email_service.py` is reached only by the separate **Email**
button (`POST /email-notes`). ShotGrid may still notify off its own rules — DNA sets no
addressings, so what goes out is down to our site's subscriptions on the linked entities.

### Turned off, and why

| Thing | Where | Why |
|---|---|---|
| To / CC on a note | `ADDRESSING_FIELDS_ENABLED` in `NoteOptionsInline.tsx` | `publish_notes` passes `to_users=[], cc_users=[]` (`main.py`, `# TODO: Parse to/cc`). The fields promised a notification that never went out, and To's *(required)* marker gated nothing. A constant, not a flag: no deployment makes them work. |
| Links on a note | `VITE_FEATURE_NOTE_LINKS` | Links reach SG only on a note's **first** publish; `update_note` writes content and subject only, so links added afterwards silently go nowhere. Publish already attaches Version + Playlist + parent Shot/Asset by itself, so the field only ever added reach beyond those. |
| Subject on a note | `VITE_FEATURE_NOTE_SUBJECT` | ShotGrid writes subjects; reviewers do not. Measured below. |
| Note QC | `VITE_FEATURE_NOTE_QC` | An ASWF feature we are not using. It was on: `get_qc_checks` **auto-seeded** an "Action Item Check" per user on first read, so everyone who had opened the Publish dialog had one, costing an LLM call per draft each time it opened. Seeding removed; the four already-seeded rows were deleted from Mongo (all the default, no custom ones). |
| Transcript checkboxes in Publish | `VITE_FEATURE_TRANSCRIPT_PUBLISH` | The backend flag was already `false` everywhere, but the dialog still showed per-version checkboxes, **default-checked**, firing calls that 404'd into `Promise.allSettled` and vanished. |

QC got its own flag rather than riding on `aiEnabled`, so **AI note generation still works** with QC
off. All four default off; unset behaves as off.

`NoteOptionsInline` now renders nothing when all four are off, a plain labelled Subject input when
Subject is the only one on, and the original chip + pencil panel as soon as a second field returns.
No separate cleanup is needed when any of these get implemented.

With the fields gone the publish dialog was mostly whitespace, so it was reworked:

- the embedded editor has no padding or header of its own — the row already provides both;
- its **height auto-sizes to the note** (116–320px) instead of reserving a fixed 140px box, and the
  drag handle still pins it to whatever a reader drags it to, as on the playlist page
  (`autoHeight = isEmbedded && defaultHeight == null && !isResized`). The floor is tied to the
  240px 16:9 thumbnail beside it, so a one-line note sits level with its frame rather than at half
  its height;
- **the drag used to jump on first press.** Taking a row off auto-height pins `editorHeight`, and
  that state was still sitting at the untouched 140px default — the measured height had gone only
  into the ref used for delta maths. `handleResizeMouseDown` now seeds the state from the
  measurement before flipping `isResized`, so the switch is invisible and the drag starts where the
  reader sees the box. Verified by pressing every handle in the page and asserting the height does
  not change;
- the note row is a checkbox beside the editor — the owner's name is dropped, since one note-taker
  is the norm here, and reappears only when a version carries more than one note;
- an **unticked row is dimmed and desaturated** (everything but the checkbox) and its editor goes
  read-only with the toolbar and resize handle hidden, so a row excluded from the publish reads as
  excluded rather than differing by one faint tick. The grid row does the same, and its note cell is
  disabled and struck through;
- the header is one line — version name, state badge, then the artist in muted weight after a
  divider — instead of spending a second line on the artist alone;
- the version's state badge sits on that line, on the same rule the grid uses: shown only when it
  is not a draft;
- the thumbnail moved out of the header and **into the note row** at 240px wide, after the
  checkbox, instead of a 48px square in the header. It sits inside the row rather than spanning the
  card so that the tick stays the leftmost control, matching the grid; a version carrying more than
  one note therefore repeats the frame, which is the price of that alignment;
- the dialog widened to 1120px, which both views now use.

The standalone editor is untouched — it keeps the fixed default height, since `autoHeight` requires
`isEmbedded`.

### Grid view (experiment)

A **Cards / Grid** toggle in the dialog header, remembered per browser in `localStorage` under
`dna-publish-view`. Grid is one row per note — checkbox, JTS number + thumbnail, artist, and the
note body in a plain editable text box — for scanning what is about to reach
ShotGrid, fixing a line, ticking rows off and publishing. Cards remains the view for composing:
the grid's cell is a bare textarea, with no markdown toolbar, mentions or image paste. Both views
share the same draft state and flush-before-publish path, so edits made in either are saved by the
same code.

Watch the grid's column minimums (`GRID_COLUMNS`): they have to sum to less than the dialog's inner
width or the note cell overflows its row. That is what happened at the first attempt.

The State column is gone, and so is Note by. The badge now sits beside the JTS number and renders
**only when the row is not a draft** — measured, not guessed: across eight real playlists all 44
dialog-eligible notes were `D`, so a State column was constant, while `E`/`P` is the case worth
catching because publish then takes `update_note` and **overwrites** an existing ShotGrid note
rather than creating one. The card view's header badge follows the same rule. The letter and label
mappings live in `noteStatus.ts`, beside the rule that produces the status. `VersionCard` imports them rather than keeping its own copy, so the
sidebar, the cards and the grid cannot drift.

The first column is the **JTS number**, not the version name — `Version.external_ref`, which is our
`sg_jts` field reaching DNA through `PRODTRACK_VERSION_EXTERNAL_REF_FIELD=sg_jts` (already set here;
see the env note above). It happens to match the bracketed prefix in a version's `code`
(`[188467] kpop-den020-animref-1`), but the field is the right source, and sites without it
configured fall back to the name. Full version name on hover. The width that freed went to an 80×50
thumbnail and to the note column.

Verified live in the browser rather than by reading: a four-line note grows its editor while its
neighbours stay one line tall, and a grid-cell edit was confirmed to reach Mongo and then reverted.
The test playlist's four notes are back to `first`/`second`/`third`/`fourth`, unchanged flags.

### Why Subject is hidden — what ShotGrid actually holds

Worth writing down, because it looked at first like DNA was pre-filling the field. It is not. What
you see is a real ShotGrid note mirrored down by `_sync_published_notes`.

ShotGrid seeds **one empty Note per version** when a playlist is created, subject set to the
playlist name, authored by the playlist creator, already linked to Version + Shot + Playlist. DNA's
sync copies that subject into the draft row, so the editor shows it.

Surveyed the newest 400 notes in each of `nite` and `kpop`:

- **800/800 have a subject.** Not one is empty.
- Of the playlist-linked ones, the subject is the playlist name **326/326 (100%) in kpop** and
  **237/246 (96%) in nite**.
- Every one of the 9 nite exceptions is a **playlist renamed after its notes were seeded** — the
  event log shows e.g. playlist 462992 created as "Lookdev AM Dailies" at 19:17:43, note 5832316
  seeded at 19:18:33, playlist renamed to "PM Dailies" at 19:21:08. The subject kept "AM".
- **154/400 nite and 74/400 kpop notes have no playlist link at all**, and use entirely different
  conventions: `Artist Note: /nite/seq/sf/sf0160 Animation`,
  `KD 12 /nite/char/goblin/modeling - Modeling (Medium)`.

So a subject at SPI is a **tool-generated identifying label**, on at least three conventions, and a
playlist note's is the playlist name *frozen at seeding time* — a record of which session the note
came from, which deliberately does not follow renames. A reviewer retyping one in DNA would produce
the only hand-written subject on the site and erase that record. Hence hidden rather than editable.

Publish still echoes the mirrored subject back unchanged, and that is correct: `update_note` sends
whatever came down, so the frozen value survives. Do **not** "improve" this by regenerating the
subject from the current playlist name — that would overwrite the provenance those 9 notes carry.

### What publish does to these seeded notes

They arrive with `published_note_id` set, so publish never takes the create path:

- untouched (`published: true, edited: false`) → skipped, nothing written;
- **the moment a body is typed**, `edited` flips and publish calls `update_note`, writing content
  and subject onto **that same SG note**.

So DNA fills in ShotGrid's blank placeholder rather than making a second note — which is why the
duplicate guard almost never fires in practice. Two consequences: clearing a subject does not clear
it upstream (`if subject:` skips empties), and an edited draft with an empty body writes
`content: ""` — harmless on a seeded blank, but it would wipe a note that had content.

### Two documentation bugs found while doing it

- `DEPLOYMENT.md` told you to create `sg_versions` (multi-entity) on the transcript custom entity.
  The code writes **`sg_version_in_review`** (`shotgrid.py`). Provisioning to the doc would have
  failed on the first transcript publish. Corrected.
- The same section documented `VITE_ENABLE_TRANSCRIPT_PUBLISH`, which **existed nowhere in the
  code** — it was only ever a doc. The flag above is that promise actually implemented, under the
  repo's `VITE_FEATURE_*` naming.

### A note-wiping trap in the editor, worth not re-treading

Making an excluded row's editor read-only wiped four draft note bodies in Mongo before it was
caught. TipTap's `setEditable(editable)` **emits an update by default**, and an update means
`onChange(getHTML())`. The effect that syncs the flag ran on mount, when the editor still held the
empty string it was created with — the draft arrives from the query a moment later — so the empty
document was saved straight over the note, with `edited: true` for good measure.

`MarkdownEditor` now guards it twice: skip when `editor.isEditable` already matches (so mount does
nothing at all, since `useEditor` set it from the same prop), and pass `emitUpdate: false`. Neither
guard is decorative. Anything else that pokes the editor imperatively deserves the same suspicion —
the save path is a debounced autosave, so a stray transaction becomes a write.

ShotGrid was never touched: only the Mongo draft rows were affected, and three were restored from
the upstream notes. The fourth had never been published, so it came back off a screenshot.

### Email sits after Publish, and says so

**Email** moved from the far side of the footer to sit **after Publish selected**, in the order the
work happens: review and publish here, then send the artist what ShotGrid now holds. It takes the
rightmost slot without becoming the primary action, because the two already differ in weight —
Publish is solid, Email is soft — so reading order and visual hierarchy do not have to fight. Opening it
with notes still unpublished shows an amber warning naming the count — the mail is built from the
draft rows, not from ShotGrid, so anything unpublished goes out in it while ShotGrid still has the
old text.

The post-publish summary offers **Email** too, as the primary action there rather than the aside it
is beforehand — telling the artist is the step after publishing, and the summary is where you are
standing when it becomes true. That meant lifting `EmailNotesDialog` out of the pre-publish branch
so both screens can open it; `PublishNotesDialog.test.tsx` publishes, reaches the summary and opens
the dialog from it, which fails if it ever slips back inside the branch.

It warns and does not block. Sending before publishing is unusual, not wrong, and the person doing
it can see exactly what is outstanding. That is the same stance the readiness gate takes with its
"Send anyway", except this one does not even need the escape hatch. `EmailNotesDialog.test.tsx`
pins the behaviour, including that Send stays enabled.

### The notes email shows the clip rather than describing it

The email listed shots as text, and nothing in it said that a clip of the discussion was one click
away. Every version name already linked to its own anchor on the review page — but a link that
looks like a link gets read as "more admin", and the recording is the part of this system nobody
knew existed. So each shot now carries a **160×90 still of the moment it came up**, with a play
badge over it, sitting under the File Spec cell to the left of its notes and linking to the same
anchor the name does. The header gained a **Playlist** row pointing at ShotGrid, next to the
existing Review Page row: the two answer different questions — "show me the versions" versus "what
was said about mine" — and neither replaces the other.

**The collector makes them, after it has finished.** Once the archive is recorded and the upstream
copy released, it asks DNA for the cut list, takes one frame per shot two seconds into that shot's
opening span, composites the badge and writes the JPEG beside the archive. Nothing about this sits
inside the ordering rule, and every failure is logged and dropped — `test_recording_collector.py`
drives a cut list that raises, an ffmpeg that refuses one shot, and a cut list that is not ready,
and asserts the archive survives all three. A missing thumbnail costs a cue; a thumbnailer wedged
into the custody chain would cost the meeting.

**Two seconds in, not the first frame.** The span opens the instant the operator marked the shot,
which is routinely a beat before the shared screen catches up — so the literal first frame
frequently shows the *previous* shot, which is worse than no thumbnail. Clamped to the middle of
short spans, because ffmpeg answers a seek past the end with no file at all and that would lose
the poster for exactly the shots that got the briefest mention.
`RECORDING_POSTER_LEAD_SECONDS` moves it; how slow a screen share is belongs to the room.

**The images are embedded in the mail, not linked.** They are written to the share and served at
`/recordings/` like the recording, and the email does not use that copy: it carries the bytes as
`cid:` parts. A hosted thumbnail is fetched by the reader's mail client, and Gmail's web client
does not fetch it itself — it asks a Google proxy, which cannot see an internal host. The link on
the thumbnail still works from anywhere inside the network, because that one is followed by the
reader's own browser. So the collector pushes ~30 kB per shot to DNA, which is the one place DNA
deliberately keeps media it otherwise only relays. A twenty-shot email is about half a megabyte.

**The badge is drawn by hand**, in `recording_posters.py` — a white triangle on a translucent disc,
supersampled 4×4 for a clean rim, emitted as a PNG built from zlib and `struct`. The alternatives
were an image library (a new dependency in an image that has one job) or ffmpeg's `geq`, which is
a GPL-only filter and therefore a property of whichever build `imageio-ffmpeg` happens to bundle
rather than of this code. It is stdlib-only for the same reason `recording_collector` is: the
collector image copies both modules out of the backend package.

Also: `ShotgridProvider.get_entity` now writes `prodtrack_detail_url` from the same field mapping
the query was built from, instead of a branch that only handled versions. The playlist's link had
been missing the whole time because nothing had asked for it.

### Still open, not addressed here

- `publish_notes` takes `_: CurrentUserDep` and never uses `request.user_email` to filter, so any
  authenticated user can publish anyone else's note — and it lands in SG under *that* person's
  login via sudo.
- Publish is not gated by `useRecordingReadiness`; only the Email dialog is, though
  `RecordingReadiness.tsx` says it was factored so Publish could adopt it.
- Note failures are `print`ed and counted, never surfaced with a reason — watch the backend log on
  the first live run.
