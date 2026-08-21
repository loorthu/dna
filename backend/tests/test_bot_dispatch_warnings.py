"""Dispatching a bot when nothing will be kept.

Segments are stored against the version in review. With none set the bot joins, Vexa transcribes,
and DNA discards every segment on arrival — a run that is indistinguishable, from outside, from a
meeting where nobody spoke. That cost a whole meeting's transcript on 2026-08-21.

These are endpoint-level on purpose. The condition is evaluated in the request handler, inside a
`try` that converts any exception into a 400, so a mistake there does not surface as an error in
the service layer — it surfaces as a dispatch that simply stops working.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient
from main import (
    app,
    get_storage_provider_cached,
    get_transcription_provider_cached,
    get_transcription_service_cached,
)

from dna.models.playlist_metadata import PlaylistMetadata
from dna.models.transcription import BotSession, BotStatus, BotStatusEnum, Platform

DISPATCH = {
    "platform": "google_meet",
    "meeting_id": "abc-defg-hij",
    "playlist_id": 42,
}


def _metadata(in_review=None) -> PlaylistMetadata:
    return PlaylistMetadata(
        _id="meta-id",
        playlist_id=42,
        meeting_id="abc-defg-hij",
        platform="google_meet",
        vexa_meeting_id=7,
        in_review=in_review,
    )


def _session() -> BotSession:
    return BotSession(
        platform=Platform.GOOGLE_MEET,
        meeting_id="abc-defg-hij",
        playlist_id=42,
        status=BotStatusEnum.JOINING,
        vexa_meeting_id=7,
    )


class TestDispatchWarnsWhenNothingIsKept:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        return mock.AsyncMock()

    @pytest.fixture
    def mock_provider(self):
        p = mock.AsyncMock()
        p.dispatch_bot.return_value = _session()
        p.get_bot_status.return_value = BotStatus(
            platform=Platform.GOOGLE_MEET,
            meeting_id="abc-defg-hij",
            status=BotStatusEnum.IN_CALL,
        )
        return p

    @pytest.fixture
    def override_deps(self, mock_storage, mock_provider):
        app.dependency_overrides[get_storage_provider_cached] = lambda: mock_storage
        app.dependency_overrides[get_transcription_provider_cached] = (
            lambda: mock_provider
        )
        app.dependency_overrides[get_transcription_service_cached] = (
            lambda: mock.AsyncMock()
        )
        yield
        app.dependency_overrides.clear()

    def test_dispatch_without_a_version_in_review_still_succeeds_but_warns(
        self, client, mock_storage, override_deps
    ):
        """The bot is dispatched — refusing would block picking a version mid-meeting — but the
        response says plainly that nothing is being stored."""
        mock_storage.get_playlist_metadata.return_value = _metadata(in_review=None)

        response = client.post("/transcription/bot", json=DISPATCH)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["saving_segments"] is False
        assert "no_version_in_review" in body["warnings"]

    def test_dispatch_with_a_version_in_review_reports_healthy(
        self, client, mock_storage, override_deps
    ):
        mock_storage.get_playlist_metadata.return_value = _metadata(in_review=101)

        response = client.post("/transcription/bot", json=DISPATCH)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["saving_segments"] is True
        assert body["warnings"] == []

    def test_bot_status_reports_that_nothing_is_being_stored(
        self, client, mock_storage, override_deps
    ):
        """A caller polling status must not read `in_call` as 'working' when it is discarding."""
        mock_storage.get_playlist_metadata.return_value = _metadata(in_review=None)

        response = client.get(
            "/transcription/bot/google_meet/abc-defg-hij/status?playlist_id=42"
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "in_call"
        assert body["saving_segments"] is False
        assert "no_version_in_review" in body["warnings"]

    def test_bot_status_is_clean_when_segments_are_being_stored(
        self, client, mock_storage, override_deps
    ):
        mock_storage.get_playlist_metadata.return_value = _metadata(in_review=101)

        response = client.get(
            "/transcription/bot/google_meet/abc-defg-hij/status?playlist_id=42"
        )

        assert response.status_code == 200, response.text
        assert response.json()["saving_segments"] is True
        assert response.json()["warnings"] == []

    def test_bot_status_does_not_guess_without_a_playlist(
        self, client, mock_storage, override_deps
    ):
        """A meeting id does not identify a playlist — the same room is reused across them.

        Guessing produced a confident `no_version_in_review` about a playlist the caller was not
        asking about, which is worse than saying nothing: a warning nobody can act on teaches
        people to ignore the warning.
        """
        response = client.get("/transcription/bot/google_meet/abc-defg-hij/status")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["saving_segments"] is None, "unknown, not assumed"
        assert body["warnings"] == []
        mock_storage.get_playlist_metadata.assert_not_awaited()
