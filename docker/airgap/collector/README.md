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
complete it pulls the audio master, muxes the two streams, writes the finished MP4 to the share,
re-reads it to confirm what landed, records the path and hash in DNA, and only then asks DNA to
delete the upstream copy.

That order is the design. Until the archive is recorded, Vexa holds the only copy — so the
delete is refused by DNA until a path and a hash exist, and refused again here before the request
is even formed.

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
in the backend suite. Only the runnable shell (the DNA HTTP client and the poll loop) is in this
directory, and the Dockerfile copies the module in from the backend rather than vendoring a
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
| `RECORDING_NETWORK_PATH` | `/net/media/dna-recordings` | the share nginx serves |
| `COLLECTOR_POLL_SECONDS` | `10` | |
| `COLLECTOR_MAX_PLAYLISTS` | `25` | work-queue depth per pass |
| `COLLECTOR_UID` / `COLLECTOR_GID` | `1000` / `1000` | who the archives end up owned by |

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

Both directories are probed for writability at **startup**, and the collector refuses to run if
either fails. Nothing is written until parts actually arrive, so without that check a misconfigured
container looks perfectly healthy right up until the first meeting it was supposed to save.

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
