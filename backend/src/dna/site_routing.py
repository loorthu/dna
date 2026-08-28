"""Which side of the deployment a request came from, and therefore which collector owns the job.

A single DNA backend serves more than one front end — the air-gapped host's nginx and a
development machine both dispatch bots to it. Recordings are collected by a service running
*beside* each front end, and the work queue used to answer "what needs collecting" rather than
"what needs collecting BY YOU". Every collector took every job: two of them mirrored the same
meeting in parallel, pulled every chunk twice, and the loser was left holding a partial mirror it
could never finish because the winner had already archived and released the upstream copy.

The rule is simple: the collector on the side that ASKED for the recording is the one that should
collect it. Anything else risks archiving a file onto a host that is not the one serving playback
— a recording that exists, cannot be played, and whose upstream copy is already gone.

The side is inferred from the immediate peer of the dispatch. `Host` and `X-Forwarded-For`
describe the browser, and change with how someone happened to type the address; the peer is the
front end's own proxy, which is also the host its collector runs on.

Routing is OPT-IN, via DNA_COLLECTOR_SITES. Until that map is configured nothing is sited at all,
and the single collector — which declares no site either — is offered every job. That is the
common deployment, and it must need no configuration.

Deriving a site from the peer whenever one merely EXISTS is what makes it need configuration: a
real HTTP request always has a peer, so every job would be stamped with some address, while an
unconfigured collector asks for the unrouted ones and matches none of them. Recordings then queue
up addressed to a site no collector claims, and the only repair is pasting a literal IP into the
collector's COLLECTOR_SITE — the deployment reaching for a hardcoded address is the symptom.
"""

import os
from typing import Optional

SITE_MAP_ENV = "DNA_COLLECTOR_SITES"


def _site_map() -> dict[str, str]:
    """`DNA_COLLECTOR_SITES="10.0.0.7=prod,172.19.0.1=dev"` → {address: name}.

    Configuring this is what turns routing ON; an empty result means every job is unrouted.
    Malformed entries are skipped rather than raising: a typo here should not stop bots being
    dispatched — though note that a map which parses to nothing switches routing off entirely,
    which is the safe direction (one collector taking everything, rather than none taking it).
    """
    raw = os.getenv(SITE_MAP_ENV, "")
    mapping: dict[str, str] = {}
    for entry in raw.split(","):
        address, _, name = entry.partition("=")
        address, name = address.strip(), name.strip()
        if address and name:
            mapping[address] = name
    return mapping


def site_for_client(client_host: Optional[str]) -> Optional[str]:
    """The site that owns work dispatched by this peer, or None if nothing is routed.

    None means unrouted, and an unrouted job is offered only to a collector that also declares no
    site — so the two queues never overlap and a single-collector deployment keeps working with no
    configuration at all.

    An address absent from a CONFIGURED map is still its own site: once routing is on, a front end
    nobody named must not quietly fall into the unrouted queue that another collector is draining.
    """
    if not client_host:
        return None

    mapping = _site_map()
    if not mapping:
        return None

    return mapping.get(client_host, client_host)
