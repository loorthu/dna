# The airgap collector

Takes custody of a meeting recording. It runs beside nginx on the air-gapped prod host and is
the only thing on that side that asks DNA for media — DNA in turn is the only thing that reaches
Vexa, so the Vexa credential never crosses over and the browser never crosses at all.

```
   Vexa  ◄────  DNA backend  ◄────  collector  ────►  /net/media/dna-recordings
 (the bot        (relay, keeps      (this)                      │
  uploads         no copy)                                      │  nginx serves it
  parts)                                                        ▼
                                                            the browser
```

## What it does

While a meeting runs it polls DNA's per-part index, fetches each new part, checks the part
against the sha256 the index advertises, and appends it to a staging file. When the recording is
complete it pulls the audio master, muxes the two streams, asks DNA where the file belongs, writes
the finished MP4 there, re-reads it to confirm what landed, records the path and hash in DNA, and
only then asks DNA to delete the upstream copy.

**DNA names the file; this deployment places it.** Neither side can supply the other's half.

```
RECORDING_ARCHIVE_DIR / <YYYYMMDD> / <playlist>_<start>_Recording.mp4
└─ this deployment ──┘ └───────── DNA ──────────────────────────────┘
```

`RECORDING_ARCHIVE_DIR` substitutes `{show}` and is the ONLY place a directory layout is written
down. Which folders a studio keeps recordings in is a fact about that studio, and a naming rule
with one site's tree baked into it is one nobody else can adopt — so it is configuration, not
code. SPI sets `/shots/{show}/lib.recording/pix/ref/dna`; unset, it defaults to
`<RECORDING_NETWORK_PATH>/{show}`.

The other half comes from `GET /recordings/{playlist_id}/archive-name`, which answers with the
show, the dated directory and the filename — the playlist's name and its show live in the
tracking system, which this side has no route to. If DNA cannot answer, the recording is **not**
archived under some fallback name: the pass fails, both copies stay where they are, and the next
pass tries again. A name that nothing can reconcile later is worse than a wait.

The path recorded in DNA is derived here, as the archive's location relative to
`RECORDING_NETWORK_PATH` — so the configured directory stays the single source of the layout. It
must therefore resolve **under** that root, which is what nginx serves; a directory outside it
would archive perfectly and produce a URL that resolves nowhere, so the collector refuses instead.

The date directory and the timestamp are the **meeting's**, in studio-local time — so a restarted
collection recomputes the same destination it was already writing to.

### A show's first recording

The directory `RECORDING_ARCHIVE_DIR` resolves to must already exist; the collector creates only
the `YYYYMMDD` directory inside it. Everything above that belongs to a tree the studio owns, made
with the ownership it means it to have — and a share that failed to mount looks exactly like a
show nobody has set up, so creating one silently would turn either into a recording filed where
no one will look for it.

So the first recording for a new show waits for someone to run the equivalent of:

```sh
mkdir -p /shots/<show>/lib.recording/pix/ref/dna     # whatever RECORDING_ARCHIVE_DIR resolves to
```

The collector names the full directory in the message it reports, so nobody has to reassemble it
from a root they were not told.

**If the share is symlinked** — each show's storage on its own volume, so the archive directory
points somewhere else entirely — then mounting the share is not enough. The link resolves inside
the container and its target does not exist there, so the directory reads as unreachable and
nothing is archived. Mount the targets as well, at the same path inside as outside, in both this
container and the one serving playback; `docker/airgap/docker-compose.frontend.yml` shows the
shape. The collector says so explicitly when it happens, naming the target rather than claiming
the directory is missing.

The wait is **visible**: the collector posts the reason to DNA, the player shows it, and both keep
polling — so the video appears on its own once the directory exists. Nothing is lost meanwhile,
because no archive is recorded and no upstream copy is released. The reason is reported once per
playlist rather than every pass, and cleared when the recording is finally archived.

That order is the design. Until the archive is recorded, Vexa holds the only copy — so the
delete is refused by DNA until a path and a hash exist, and refused again here before the request
is even formed.

## Poster frames

Once the handover is finished — archive recorded, upstream copy released — the collector asks DNA
for the playlist's cut list and grabs one still per shot, a couple of seconds into the span where
that shot came up. Each frame gets a play badge composited over its middle and is written beside
the archive, in the same dated directory, so nginx serves it at `/recordings/` like the recording; the bytes are also pushed to
DNA, because the notes email is composed on the other side of the airgap and **embeds** the
thumbnail rather than linking it. A linked one would be broken for the readers most likely to open
the mail on a phone: Gmail's web client fetches every image through a Google proxy, and that proxy
cannot reach this host.

The badge is drawn in Python, not by an image library or by ffmpeg's `geq` — `geq` is a GPL-only
filter, so its presence would be a property of whichever build the wheel happens to bundle, and a
PNG is a handful of CRC'd chunks around a zlib stream. It is the same on every host and is covered
by an offline test.

**None of this can cost a recording.** It runs strictly after the ordering rule has completed, one
shot at a time, and every failure — no cut list, no ffmpeg, DNA unreachable — is logged and
dropped. A missing thumbnail costs a visual cue; a thumbnailer wedged into the middle of the
custody chain would cost the meeting. Frames are only taken from a `ready` cut list, so a
recording that is still being made is never guessed at.

## Why it mirrors during the meeting rather than downloading at the end

The assembled master only exists once the meeting is over, and pulling several hundred MB in one
request across a link whose characteristics are undocumented is the transfer most likely to fail.
Parts are readable while the recording is still in progress, so the copy is built as the meeting
happens and finishes moments after it does — and a failure costs one part, not the recording.

## Why a service and not the browser

A page cannot write to a network filesystem; the prod origin is plain HTTP so `crypto.subtle` is
undefined there; a reload would drop the accumulated state; and nothing would resume.

## Resuming

A meeting lasts an hour and this process can restart at any point inside it. Progress is a fact
about the staging file, reconciled against the state file on every start: the parts on disk are
re-derived from the bytes that actually survived, so a crash between the append and the state
write is trimmed rather than trusted in either direction. Interrupting a collection and resuming
it produces a byte-identical file to one that ran straight through.

## Where the code lives

The logic — resuming, verification, the mux command, the ordering rule — is
`backend/src/dna/recording_collector.py`, covered by `backend/tests/test_recording_collector.py`
in the backend suite; the thumbnailer is `recording_posters.py` beside it, covered by
`test_recording_posters.py`. Only the runnable shell (the DNA HTTP client and the poll loop) is in
this directory, and the Dockerfile copies both modules in from the backend rather than vendoring a
second copy that could drift.

## ffmpeg

Installed as `imageio-ffmpeg`, a wheel bundling a full static build, rather than
`apt-get install ffmpeg`. The prod host mirrors PyPI and npm through Artifactory but not Debian,
so an apt dependency would make this image buildable only on an internet-connected machine and
carried over; the wheel keeps building on prod working too. The image build asserts the bundled
binary has an AAC encoder, so a bad pin fails the build rather than the first real meeting.

The pinned version determines the ffmpeg version — 0.6.0 carries 7.0.2, while 0.5.1 carries
4.2.2. Re-check the mux if that pin moves.

## Configuration

| Variable | Default | |
|---|---|---|
| `DNA_API_URL` | `http://localhost:8000` | where DNA's API answers |
| `DNA_API_TOKEN` | *(empty)* | only if the backend runs with auth |
| `COLLECTOR_STAGING_DIR` | `/staging` | must be durable across restarts |
| `RECORDING_NETWORK_PATH` | `/net/media/dna-recordings` | the share ROOT nginx serves (`/shots` in prod) |
| `RECORDING_ARCHIVE_DIR` | `<root>/{show}` | which directory a show's recordings go in; must resolve under the root |
| `COLLECTOR_POLL_SECONDS` | `10` | |
| `COLLECTOR_MAX_PLAYLISTS` | `25` | work-queue depth per pass |
| `COLLECTOR_UID` / `COLLECTOR_GID` | `1000` / `1000` | who the archives end up owned by |
| `RECORDING_POSTER_LEAD_SECONDS` | `2` | how far into a shot's span its thumbnail is taken from |

Staging is a named volume rather than a bind or a tmpfs precisely because a half-mirrored meeting
has to survive a container restart.

## Who the files belong to

The collector runs unprivileged, and every archive is owned by the uid it runs as. That uid is a
deployment choice, not an image one: it has to be able to **write** `RECORDING_NETWORK_PATH`, and
nginx has to be able to **read** what it writes (files are `0644`). On the host,
`stat -c '%u:%g' <mount>` usually names the right pair.

```sh
COLLECTOR_UID=1234
COLLECTOR_GID=100
```

It is deliberately not root. An archive is the only copy of its meeting once the upstream copy is
released, and a root-owned file cannot be rotated, moved or deleted by whoever owns the share.

Staging is probed for **writability** at startup and the share root for **reachability**, and the
collector refuses to run if either fails. Nothing is written until parts actually arrive, so
without that check a misconfigured container looks perfectly healthy right up until the first
meeting it was supposed to save.

The share is only checked for reachability because nothing writes to its root: archives land
several directories down, in a show's own library, and which show that is depends on the meeting.
So write permission is discovered on the first archive of each **show** rather than at startup —
safely, since a failed write leaves the upstream copy alone and the next pass retries, but later.
A show being recorded for the first time is the moment to watch the logs.

**Changing the uid on an existing deployment needs the staging volume recreated.** A named volume
keeps the ownership it was created with, so it stays root-owned from before and the new uid cannot
write to it — the startup probe says so plainly. Any half-mirrored meeting in there is abandoned,
so do it between meetings:

```sh
docker compose ... down
docker volume rm <project>_collector-staging
docker compose ... up -d
```

## Running it

It comes up with the frontend:

```sh
docker compose --env-file docker/airgap/.env -f docker/airgap/docker-compose.frontend.yml up -d
docker logs -f dna-collector
```

A playlist whose meeting was never recorded stays in the work queue and 404s; that is logged once
and then quietened, so a real failure stays visible in the log.
