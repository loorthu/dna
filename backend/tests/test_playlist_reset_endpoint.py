"""Tests for DELETE /playlists/{id}/data, the air-gapped reset path."""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from main import app, get_storage_provider_cached

ENABLE_FLAG = {"DNA_ENABLE_PLAYLIST_RESET": "true"}


class FakeStore:
    """Records what it was asked to delete, so the route's contract is what is asserted."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    async def delete_playlist_data(
        self, playlist_id: int, include_notes: bool = True
    ) -> dict[str, int]:
        self.calls.append((playlist_id, include_notes))
        return {
            "segments": 18,
            "playlist_metadata": 1,
            "draft_notes": 3 if include_notes else 0,
        }


@pytest.fixture
def store():
    fake = FakeStore()
    app.dependency_overrides[get_storage_provider_cached] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_disabled_by_default_looks_absent(store, client):
    """Without the flag the route must not merely refuse -- it must not appear to exist."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DNA_ENABLE_PLAYLIST_RESET", None)
        response = client.delete("/playlists/462858/data")
    assert response.status_code == 404
    assert store.calls == [], "nothing may be deleted while the feature is off"


def test_enabled_clears_the_playlist(store, client):
    with mock.patch.dict(os.environ, ENABLE_FLAG):
        response = client.delete("/playlists/462858/data")

    assert response.status_code == 200
    body = response.json()
    assert body["playlist_id"] == 462858
    assert body["deleted"] == {
        "segments": 18,
        "playlist_metadata": 1,
        "draft_notes": 3,
    }
    assert body["kept_notes"] is False
    assert store.calls == [(462858, True)]


def test_keep_notes_spares_the_only_human_authored_rows(store, client):
    with mock.patch.dict(os.environ, ENABLE_FLAG):
        response = client.delete("/playlists/462858/data?keep_notes=true")

    assert response.status_code == 200
    assert response.json()["deleted"]["draft_notes"] == 0
    assert response.json()["kept_notes"] is True
    assert store.calls == [(462858, False)], "include_notes must be the inverse of keep_notes"


def test_reset_of_an_untouched_playlist_is_not_an_error(store, client):
    """A collector retrying after a partial run must not see a failure for already-clean data."""

    async def nothing(playlist_id: int, include_notes: bool = True) -> dict[str, int]:
        store.calls.append((playlist_id, include_notes))
        return {"segments": 0, "playlist_metadata": 0, "draft_notes": 0}

    store.delete_playlist_data = nothing  # type: ignore[assignment]
    with mock.patch.dict(os.environ, ENABLE_FLAG):
        response = client.delete("/playlists/999999/data")

    assert response.status_code == 200
    assert response.json()["deleted"]["segments"] == 0
