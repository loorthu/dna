"""Which side owns a recording job.

One DNA backend serves several front ends, and each has a collector beside it. The work queue used
to answer "what needs collecting" rather than "what needs collecting BY YOU", so every collector
took every job: two of them mirrored one meeting in parallel and the loser was left holding a
partial it could never finish, because the winner had already archived and released the upstream
copy. Worse was available — had the other one won, DNA would hold an archive on a host that is not
the one serving playback.
"""

from unittest import mock

import pytest

from dna.site_routing import SITE_MAP_ENV, site_for_client


class TestSiteForClient:
    def test_an_unmapped_peer_is_its_own_site(self):
        """A name is a convenience; the address routes perfectly well without one."""
        with mock.patch.dict("os.environ", {}, clear=True):
            assert site_for_client("10.5.81.74") == "10.5.81.74"

    def test_a_mapped_peer_gets_its_name(self):
        with mock.patch.dict(
            "os.environ", {SITE_MAP_ENV: "10.5.81.74=prod,172.19.0.1=dev"}
        ):
            assert site_for_client("10.5.81.74") == "prod"
            assert site_for_client("172.19.0.1") == "dev"

    def test_no_peer_is_unrouted(self):
        assert site_for_client(None) is None
        assert site_for_client("") is None

    def test_a_malformed_map_does_not_stop_a_dispatch(self):
        """A typo in configuration must not take bot dispatch down with it."""
        with mock.patch.dict(
            "os.environ", {SITE_MAP_ENV: "garbage,,=x,y=,10.0.0.1=ok"}
        ):
            assert site_for_client("10.0.0.1") == "ok"
            assert site_for_client("10.0.0.2") == "10.0.0.2"


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
