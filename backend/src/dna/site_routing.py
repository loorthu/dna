"""Which side of the deployment asked for a recording, and therefore which collector owns it.

A single DNA backend serves more than one front end — the air-gapped host's nginx and a
development machine both dispatch bots to it. Recordings are collected by a service running
*beside* each front end, and the work queue used to answer "what needs collecting" rather than
"what needs collecting BY YOU". Every collector took every job: two of them mirrored the same
meeting in parallel, pulled every chunk twice, and the loser was left holding a partial mirror it
could never finish because the winner had already archived and released the upstream copy.

The rule is simple: the collector on the side that ASKED for the recording is the one that should
collect it. Anything else risks archiving a file onto a host that is not the one serving playback
— a recording that exists, cannot be played, and whose upstream copy is already gone.

THE SIDE IS DECLARED, NOT INFERRED. Each front end sends its own name in `X-DNA-Site`, set by that
deployment's nginx from the same `COLLECTOR_SITE` its collector reads. One variable, one host: the
two halves that have to agree are the same string in the same file, so they cannot drift apart.

This was previously inferred from the dispatch's peer address against a configured map, and the
inference is what broke. On a host whose backend sits behind an edge proxy and a loopback-published
port, every request arrives from the docker bridge gateway — the real client address never reaches
`request.client.host` at all. So every front end looked like one site, a prod recording was stamped
`dev` and archived onto a host that does not serve it, and the map's entry for the prod address
could never match anything. Addresses also move: a migrated server or a renumbered network silently
re-sites every dispatch. Nothing about a peer address says which deployment it is; a name does, and
the deployment already knows its own.

WHAT THE HEADER IS AND IS NOT. That nginx SETS it — `proxy_set_header` overwrites whatever the
browser sent — so a client on the far side of it cannot claim a site. Anything that reaches this
API directly can, and no peer-address map provided that boundary either. What this does provide is
that the value is compared for equality with a collector's own label and used for nothing else, so
an unrecognised one addresses the job to a collector that does not exist: it waits, visibly,
instead of being archived onto the wrong host.

Naming no site leaves the job unrouted, and an unrouted job is offered only to a collector that
also declares no site — so the two queues never overlap, and a single-collector deployment needs no
configuration at all.
"""

from typing import Optional

# Written down twice — here, and in the front end's nginx template. `test_site_routing` holds the
# two together whenever the frontend tree is present.
SITE_HEADER = "X-DNA-Site"


def site_for_dispatch(declared: Optional[str]) -> Optional[str]:
    """The site the dispatching front end named, or None when it named none.

    Empty is the same as absent, deliberately: `proxy_set_header X-DNA-Site "";` sends no header at
    all, which is what an unset COLLECTOR_SITE renders to, and a deployment that sets the variable
    to nothing means the same as one that never set it. Surrounding whitespace is trimmed for the
    same reason — matching is by equality, so a stray space in a `.env` would otherwise address the
    job to a site no collector claims.
    """
    return (declared or "").strip() or None
