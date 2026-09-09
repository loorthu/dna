"""Which side owns a recording job.

One DNA backend serves several front ends, and each has a collector beside it. The work queue used
to answer "what needs collecting" rather than "what needs collecting BY YOU", so every collector
took every job: two of them mirrored one meeting in parallel and the loser was left holding a
partial it could never finish, because the winner had already archived and released the upstream
copy. Worse was available — had the other one won, DNA would hold an archive on a host that is not
the one serving playback.
"""

import os
import re
from unittest import mock

import pytest

from dna.site_routing import SITE_HEADER, site_for_dispatch


class TestSiteForDispatch:
    def test_naming_no_site_is_unrouted(self):
        """The single-collector deployment must need no configuration.

        The unrouted queue is drained by a collector that declares no site either, so a deployment
        that has never heard of any of this keeps working.
        """
        assert site_for_dispatch(None) is None

    def test_an_empty_declaration_is_the_same_as_none(self):
        """`proxy_set_header X-DNA-Site "";` sends no header at all, and that is exactly what an
        unset COLLECTOR_SITE renders to — so the two cannot be allowed to mean different things.
        """
        assert site_for_dispatch("") is None
        assert site_for_dispatch("   ") is None

    def test_a_declared_site_is_taken_at_its_word(self):
        """No map, no lookup, no inference. The deployment knows its own name."""
        assert site_for_dispatch("prod") == "prod"
        assert site_for_dispatch("laptop") == "laptop"

    def test_stray_whitespace_does_not_invent_a_second_site(self):
        """Matching is by equality against the collector's own label, so ` prod` would address the
        job to a site nobody runs — and the job would wait for a collector that cannot exist."""
        assert site_for_dispatch("  prod\n") == "prod"


class TestTheTwoHalvesAgree:
    """The header this package reads is the header the front end sends.

    The name is written down twice, in two languages, on hosts that deploy separately — which is
    precisely the drift that put a prod recording on a dev host. Skipped when the frontend tree is
    absent: the backend's test image mounts only `src` and `tests`.
    """

    TEMPLATE = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "default.conf.template"
    )

    @pytest.mark.skipif(
        not os.path.exists(TEMPLATE), reason="frontend tree not mounted in this test image"
    )
    def test_the_nginx_template_sets_the_header_the_backend_reads(self):
        with open(self.TEMPLATE) as handle:
            template = handle.read()

        assert re.search(rf"proxy_set_header\s+{SITE_HEADER}\s", template), (
            f"{SITE_HEADER} is what dispatch reads, and the API location in "
            "frontend/default.conf.template is the only thing that sets it — renaming one "
            "without the other silently unroutes every recording that front end dispatches"
        )


class TestTheQueuesNeverOverlap:
    """The property that makes the race impossible, rather than merely unlikely."""

    @pytest.fixture
    def provider(self):
        from dna.storage_providers.mongodb import MongoDBStorageProvider

        with mock.patch.dict(
            "os.environ", {"MONGODB_URL": "mongodb://localhost:27017"}
        ):
            yield MongoDBStorageProvider()

    @staticmethod
    def _capture(provider):
        class Cursor:
            def sort(self, *a, **k):
                return self

            def limit(self, n):
                return self

            async def __aiter__(self):
                return
                yield

        collection = mock.MagicMock()
        collection.find = mock.MagicMock(return_value=Cursor())
        client = mock.MagicMock()
        client.dna.playlist_metadata = collection
        provider._client = client
        return collection

    async def test_a_named_site_asks_for_exactly_its_own(self, provider):
        collection = self._capture(provider)

        await provider.list_playlists_pending_archive(site="prod")

        assert collection.find.call_args[0][0]["collector_site"] == "prod"

    async def test_no_site_asks_for_exactly_the_unrouted(self, provider):
        collection = self._capture(provider)

        await provider.list_playlists_pending_archive()

        assert collection.find.call_args[0][0]["collector_site"] is None, (
            "None matches absent and explicitly-null, which is the pre-routing backlog — and "
            "never matches a named site, so it cannot overlap another collector's queue"
        )

    async def test_two_named_sites_cannot_be_handed_the_same_job(self, provider):
        """The queues are disjoint by construction, not by timing."""
        collection = self._capture(provider)
        await provider.list_playlists_pending_archive(site="prod")
        prod = collection.find.call_args[0][0]["collector_site"]

        collection = self._capture(provider)
        await provider.list_playlists_pending_archive(site="dev")
        dev = collection.find.call_args[0][0]["collector_site"]

        assert prod != dev
