---
name: Follow Along (itview sync)
overview: Let a DNA user follow a live itview review session, so that when the review player changes clip, the user's selected version follows automatically. Ports the "Itview Sync" feature from notebox. Browser-direct STOMP over WebSocket to ActiveMQ; personal follow only (does not touch playlist in_review).
todos:
  - id: env-setup
    content: Set dna_dev onto a follow-along branch based on bot-authentication-v2, copy gitignored config from the dna checkout
    status: pending
  - id: backend-external-ref
    content: Add optional Version.external_ref + Project.code, populated from configurable ShotGrid fields (sg_jts / tank_name)
    status: pending
  - id: core-parse
    content: Add followAlong/ to @dna/core - types, parseCurrentClip (DOMParser), reviewSyncClient (STOMP), edbotSessions
    status: pending
  - id: app-context
    content: Add FollowAlongContext + useFollowAlong hook, mount beside EventProvider in ThemedApp
    status: pending
  - id: app-wire
    content: Drive selectedVersion from App.tsx when follow is on
    status: pending
  - id: app-ui
    content: FollowAlongMenu (session picker + connection LED) in VersionHeader; off-playlist toast
    status: pending
  - id: feature-flag
    content: Add followAlongEnabled to FeatureFlagsContext (VITE_FEATURE_FOLLOW_ALONG) and document env vars
    status: pending
  - id: tests
    content: Unit tests for parseCurrentClip, session/show filtering, version resolution, toast de-dup
    status: pending
---

# Follow Along — mirror the itview review session's current clip in DNA

## Context

During dailies, the review player (**itview**) decides what everyone is actually
looking at, but DNA has no idea. The note-taker has to keep their selected
version in step with the room by hand, which is error-prone and steals attention
from writing notes.

The sibling app **notebox** already solves this — the feature is called
**"Itview Sync"** (added 2013, hardened Aug 2026). Its screening-report grid
subscribes over STOMP to an ActiveMQ topic that itview publishes to, and draws a
red dashed border around the row for the clip currently on screen.

This plan ports that idea to DNA.

### Decisions already taken

| Decision | Choice |
|---|---|
| Signal source | itview topic **+** edbot REST session list (session picker, as notebox does) |
| Topology | **Browser-direct STOMP** — each DNA tab connects to the broker itself |
| Effect | **Personal follow only** — moves the local `selectedVersion`; `in_review` untouched |
| ID mapping | Expose ShotGrid `sg_jts` as an opaque `external_ref` on Version; match in-browser |

Because the effect is personal-only and the connection is browser-direct, this is
**almost entirely a frontend feature**. The one backend change exists solely so
the browser can map itview's JTS onto a DNA version.

> **DNA is an ASWF open-source project.** SPI specifics (itview, edbot, JTS,
> `mq1.spimageworks.com`) must not be hardcoded into shared code — they belong
> behind configuration and a narrow, swappable parsing/transport seam.

---

## Reference: how notebox does it

All in `notebox/site_media/js/note_detail.js`; the Django server is not involved
at all (there is no STOMP library in its `requirements.txt`).

- **Connect** (`:2076`): `Stomp.client('ws://mq1.spimageworks.com:61614/stomp')`,
  anonymous auth (empty user/password).
- **Subscribe** (`:2082`): `/topic/itview/current_clip.xml`. The payload is XML
  and is broadcast to *every* listener.
- **Filter** client-side by substring match on `<session>NAME</session>` **and**
  `<show>SHOW</show>`.
- **Extract** `<jts>(\d+)</jts>` — **JTS is the version identity** — plus
  `<shot>(\w+)</shot>`.
- **Session list** (`:1962`):
  `GET http://edbot-vm.spimageworks.com:8080/edbotproxy/rest/show/{show}/sessions`
  over JSONP, returning `[{id, name, connections:[{<id>:{username}}]}]`.
- **Persistence**: chosen session saved per report in the ExtJS state manager;
  auto-reconnect every 5 s, guarded by `requested_session` so a user disconnect
  cancels the retry loop.
- **Off-report clip** (`:1930-1945`): toast offering "Add JTS to Screening
  Report", de-duplicated via `_warned_jts` because itview republishes constantly.

### Deliberately *not* copied

- The shot regex `(\w+)` silently drops shot names containing `-` or `.`.
  We use `DOMParser` instead, which fixes this for free.
- `disconnect_session` never clears the `current` flag, so a later grid refresh
  re-applies the highlight after disconnect.
- The heartbeat subscription computes two booleans and discards them — dead code.

---

## Backend change (small, additive, opt-in)

Expose an opaque external reference on Version so the browser can match on it.
This **must be opt-in**: `sg_jts` is an SPI custom field that does not exist on a
stock ShotGrid site, and requesting it unconditionally would break `find()` for
every other studio running DNA.

1. **`backend/src/dna/models/entity.py`** — add to `Version`:

   ```python
   external_ref: Optional[str] = Field(
       default=None,
       description="Opaque id for this version in an external review tool",
   )
   ```

2. **`backend/src/dna/prodtrack_providers/shotgrid.py`** —
   `FIELD_MAPPING["version"]["fields"]` (~line 85) is the declarative field list
   that `get_versions_for_playlist` (`:688-696`) derives its ShotGrid query from,
   so adding one entry flows through automatically.

   Insert `{<field>: "external_ref"}` **only when configured**, via a new env var
   `PRODTRACK_VERSION_EXTERNAL_REF_FIELD` (SPI sets it to `sg_jts`; unset means
   the feature is simply off). Do not hardcode `sg_jts`.

3. **Show code for the edbot URL.** `FIELD_MAPPING["project"]` maps only
   `id`/`name`, and `get_projects` (`:614-623`) additionally hardcodes
   `fields=["id", "name"]` — **both** need updating. Add an optional `code`
   (SPI: ShotGrid `tank_name`) to the mapping, that hardcoded list, the `Project`
   model, and the `Project` TS interface. Fall back to `Project.name` when absent.

4. **`mock_provider.py` + `mock_data`** — populate `external_ref` so the feature
   is demoable without ShotGrid or a broker.

No broker library, no new backend dependency, and no changes to `events/`,
`transcription_service.py`, or the `/ws` endpoint.

> ⚠️ **This change cannot be tested without restarting `dna-backend`**, which is
> shared with other users (see "Local environment" below). Build and test the
> entire frontend first against a stubbed `external_ref`, then apply this change
> and restart deliberately in a quiet window. It is additive and a no-op when the
> env var is unset, so the restart is low risk.

---

## Frontend

Respect `.cursor/rules/keep-app-and-core-seperate.mdc` — framework-free logic in
`@dna/core`, React in `@dna/app`.

### New dependency

**`@stomp/stompjs`** (npm, via the Artifactory registry). Bundled, *not* loaded
from a remote `<script>` the way notebox does — the DNA frontend is built for
air-gapped deployment, so a runtime fetch from `spimageworks.com` is not viable.
It provides `Client({brokerURL, connectHeaders, reconnectDelay, heartbeat*})`,
`subscribe()`, and built-in reconnect, replacing notebox's hand-rolled retry loop.

### `@dna/core` — `frontend/packages/core/src/followAlong/`

| File | Responsibility |
|---|---|
| `types.ts` | `ReviewFocus { session, show, shot, externalRef }`, `ReviewSession { id, name, users }` |
| `parseCurrentClip.ts` | Parse the topic payload → `ReviewFocus \| null`. Use `DOMParser` (`text/xml`) and read element text; return `null` on parse failure or missing `jts`. |
| `reviewSyncClient.ts` | `ReviewSyncClient` wrapping `@stomp/stompjs`. Applies the session+show filter before notifying subscribers. |
| `edbotSessions.ts` | `fetchReviewSessions(baseUrl, show)`; flattens edbot's `connections` into a `users` list so active sessions can sort above idle ones. |

`ReviewSyncClient` should deliberately mirror the ergonomics of the existing
`DNAEventClient` (`frontend/packages/core/src/eventClient.ts`) so it reads as the
same codebase: `connect()`, `disconnect()`, `subscribe(cb)`,
`onConnectionStateChange(cb)`, `setSession(name)`.

### `@dna/app`

- **`contexts/FollowAlongContext.tsx`** — modelled on `contexts/EventContext.tsx`.
  Owns one `ReviewSyncClient`, the chosen session (persisted in `localStorage`,
  keyed by playlist — notebox keys by report), connection state, available
  sessions, and the latest `ReviewFocus`. Mount in `ThemedApp.tsx` beside
  `EventProvider`.

- **`hooks/useFollowAlong.ts`** — resolves `focus.externalRef` against the
  already-loaded `versions` array
  (`versions.find(v => v.external_ref === focus.externalRef)`); **no network call
  per clip change**. Returns
  `{ enabled, connected, sessions, session, setSession, focus, followedVersion, isOffPlaylist }`.

- **`App.tsx`** — `selectedVersion` already lives here (`:21`), so nothing needs
  lifting. Add one effect beside the existing auto-select effect (`:31-44`):

  ```ts
  useEffect(() => {
    if (!followEnabled || !followedVersion) return;
    setSelectedVersion(followedVersion);
  }, [followEnabled, followedVersion]);
  ```

- **UI** — a `FollowAlongMenu` component (session dropdown + connection LED) in
  `components/VersionHeader.tsx`, next to the existing "In Review" / "Set In
  Review" controls (`:420`, `:467`), so the two "what's being reviewed"
  affordances sit together. Reuse the live/reconnecting dot idiom from
  `components/TranscriptPanel.tsx:171-174`.

- **Off-playlist notice** — when the followed session shows a version not in the
  playlist, raise a toast via `useToast().showToast`
  (`contexts/ToastContext.tsx:22`), de-duplicated on `externalRef` exactly as
  notebox's `_warned_jts` guard does. Do **not** port notebox's "add it to the
  report" action — DNA playlists come from ShotGrid.

- **Feature flag** — `followAlongEnabled` in `contexts/FeatureFlagsContext.tsx`
  with `VITE_FEATURE_FOLLOW_ALONG`, following the existing `readEnvOverride` +
  `localStorage` pattern (`:20-22`). Keep it **independent** of the
  transcription/AI/in-review "russian doll" chain.

- **Config** (build-time Vite env, matching the `VITE_PRODTRACK_TAB_SYNC_*`
  precedent), documented in `.env.example`:

  ```
  VITE_FOLLOW_ALONG_BROKER_URL=ws://mq1.spimageworks.com:61614/stomp
  VITE_FOLLOW_ALONG_TOPIC=/topic/itview/current_clip.xml
  VITE_FOLLOW_ALONG_SESSIONS_URL=http://edbot-vm.spimageworks.com:8080
  ```

  The feature stays off when the broker URL is unset.

---

## Local environment — how to work without disturbing the running app

**A live DNA instance other people are using runs on this machine.** Read this
section before starting anything.

### What is running

| Container | Compose project | Source tree | Ports |
|---|---|---|---|
| `dna-backend` | `backend` | `/home/loorthu/Documents/git/dna/backend` | `8000:8000` |
| `dna-mongo` | `backend` | same | `27017:27017` |
| `vexa-v012-*` (10 containers) | `vexa-v012` | `/home/loorthu/Documents/git/vexa/deploy/compose` | various |
| `transcription-*` | `transcription` | `/home/loorthu/Documents/git/vexa/deploy/transcription` | `8083` |

`dna-backend` also bind-mounts Gmail credentials out of
`/home/loorthu/Documents/git/loorthu_dna/experimental/...`, so that clone is
load-bearing for the running app too.

### Decision: reuse the running containers

We are **not** starting a second DNA stack. The frontend dev server runs from
`dna_dev` and talks to the existing `dna-backend:8000` (and through it the
existing vexa stack).

**Run vite on the default port 5173.** This is not arbitrary:
`CORS_ALLOWED_ORIGINS` is unset on the live container, so
`backend/src/dna/cors_settings.py` falls back to allowing only
`http://localhost:5173` and `http://localhost:3000`. Port 5173 is currently free.
Using it means **zero backend changes and zero restarts**.

### Hard rules

1. **Never run `docker compose`, `make start-local`, `make stop-local`, or
   `make test` from `dna_dev/backend`.** Compose derives its project name from the
   directory basename — `backend` in *both* trees — so `down` there would tear
   down the live stack, and `make test` (`run --rm api`, `MONGODB_URL=mongodb://mongo:27017`)
   would execute against the **live Mongo**. Deliberately do **not** copy
   `docker-compose.local.yml` into `dna_dev`, so there is nothing there to start
   by accident.
2. **Never `git checkout` in `/home/loorthu/Documents/git/dna`.** Its
   `backend/src` is bind-mounted **read-write** into the running container; a
   branch switch swaps the live app's source out from under it. (Uvicorn runs
   without `--reload`, so nothing takes effect until a restart — but the next
   restart would pick up whatever is on disk.)
3. **We share the live Mongo.** Follow-along itself writes nothing, but testing
   by typing draft notes or toggling In Review lands in real data. Agree on a
   scratch playlist for testing.

### Setup steps for this clone

`dna_dev` was created as a fresh clone of ASWF `origin/main`. Two things are
missing:

**1. It is on `main` and does not contain the bot-authentication work.** The
`bot-authentication-v2` branch lives on the personal fork, which this clone has
no remote for:

```sh
cd /home/loorthu/Documents/git/dna_dev
git remote add fork git@github.com:loorthu/dna.git
git fetch fork
git checkout -b follow-along fork/bot-authentication-v2
```

(Alternatively fetch straight from the local checkout:
`git remote add local /home/loorthu/Documents/git/dna && git fetch local && git checkout -b follow-along local/bot-authentication-v2`.)

**2. Gitignored config did not come with the clone.** Copy the frontend env,
which already points at `localhost:8000`:

```sh
cp /home/loorthu/Documents/git/dna/frontend/packages/app/.env \
   /home/loorthu/Documents/git/dna_dev/frontend/packages/app/.env
```

Then `npm install` at `frontend/` and `npm run dev` (vite, port 5173).

---

## Risks to settle during implementation

1. **edbot CORS.** notebox reaches edbot over JSONP, which strongly implies edbot
   sends no CORS headers — in which case a React `fetch()` will be blocked.
   **Verify this in a browser before building the session picker.** If blocked,
   the fallback is a thin backend proxy (`GET /follow-along/sessions?show=`)
   rather than reintroducing JSONP. This is the one item that could pull backend
   work back into scope.
2. **Mixed content.** notebox is served over `http://` and uses `ws://`. If DNA is
   served over `https://`, the browser blocks a `ws://` connection outright and
   follow-along fails silently. Confirm how DNA is served in the target
   deployment; a `wss://` listener on the broker may be required.
3. **Broker reachability.** Browser-direct means every DNA user's workstation must
   reach `mq1:61614`. True for notebox users today, so low risk — but it will not
   work from a DMZ dev machine, so expect to develop against a stub.
4. **JTS type.** Keep `external_ref` a string end to end and compare as strings;
   itview sends digits, but ShotGrid custom fields are inconsistently typed.

---

## Verification

1. **Frontend unit (vitest, colocated `*.test.ts` — see
   `prodtrackTabSync/sendProdtrackTabSync.test.ts` for the existing style):**
   - `parseCurrentClip` — well-formed XML; shot names containing `-` and `.`
     (the notebox regex bug); missing `<jts>`; malformed XML → `null`.
   - Session/show filtering — a message for a different session produces no
     focus change.
   - `useFollowAlong` — resolves to the right version; reports `isOffPlaylist`
     when nothing matches; toast fires once per `externalRef`, not per message.
2. **Backend (pytest, `backend/tests/`):** `external_ref` and project `code`
   survive the ShotGrid→DNA conversion; with
   `PRODTRACK_VERSION_EXTERNAL_REF_FIELD` unset, the SG query field list is
   **unchanged** (this is the guard for other studios).
3. **End-to-end without a broker:** feed synthetic frames straight into
   `ReviewSyncClient`'s message handler from the devtools console — same spirit as
   the existing `POST /test/broadcast-transcript` dev hook. Confirm the sidebar
   selection jumps and the note editor swaps to the followed version's draft.
4. **Against the real broker (on-site):** point `VITE_FOLLOW_ALONG_BROKER_URL` at
   `ws://mq1.spimageworks.com:61614/stomp`, pick a live itview session, change
   clip in itview, confirm DNA follows within a second and the LED reflects
   disconnect/reconnect.
5. **Gates:** `make format-python`, prettier on TS, `make test` (per
   `.cursor/rules/run-formatting.mdc`, `always-update-tests.mdc`). Commits need
   `Signed-off-by` (`.cursor/rules/dco-signoff.mdc`).

---

## Out of scope (deliberately)

- **Driving `in_review`**, and therefore transcript attribution
  (`transcription_service.py:241-256` stores segments against
  `metadata.in_review`). Personal-follow-only was an explicit choice. If that
  changes later, the natural follow-on is broadcasting a `review.version_changed`
  event from `upsert_playlist_metadata` (`main.py:1442`), which today publishes
  nothing — so even a manual "Set In Review" click fails to propagate to other
  browsers.
- Any backend STOMP consumer.
- Publishing DNA's selection *back* to itview.
