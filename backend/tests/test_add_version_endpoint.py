"""Tests for POST /playlists/{id}/versions -- adding versions from the sidebar.

The field takes the id the review tool announces (the JTS at SPI) and nothing else, a list of
them at a time. What is asserted here is that a pasted list is answered for id by id: a review is
assembled from ids off a turnover sheet, some of which are stale, already in the playlist, or on
another show, and a person needs to be told which were which.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from main import app, get_prodtrack_provider_cached

from dna.models.entity import Playlist, Version

PROJECT = {"type": "Project", "id": 7}
OTHER_PROJECT = {"type": "Project", "id": 8}


def _version(version_id: int, name: str, jts: int, project: dict = PROJECT) -> Version:
    return Version(id=version_id, name=name, project=project, external_ref=str(jts))


class FakeProdtrack:
    """A show with three versions, one of them already in the playlist, plus one on another show."""

    def __init__(self) -> None:
        self.versions = [
            _version(300, "[1786] nite-seq.pvs-camera-120", 1786),
            _version(301, "[1787] nite-seq.pvs-camera-121", 1787),
            _version(302, "[1789] nite-seq.pvs-camera-122", 1789),
            _version(999, "[1786] other-show-thing", 1786, OTHER_PROJECT),
        ]
        self.playlist_versions: dict[int, list[int]] = {400: [300]}
        self.appends: list[tuple[int, list[int]]] = []

    def get_entity(
        self, entity_type: str, entity_id: int, resolve_links: bool = True
    ) -> Any:
        if entity_type == "playlist":
            if entity_id not in self.playlist_versions:
                raise ValueError(f"Entity not found: playlist {entity_id}")
            return Playlist(id=entity_id, code="dailies", project=PROJECT)
        raise ValueError(f"Unknown entity type: {entity_type}")

    def find(
        self, entity_type: str, filters: list[dict[str, Any]], limit: int = 0
    ) -> list[Any]:
        assert entity_type == "version"
        by_field = {f["field"]: f["value"] for f in filters}
        wanted = {str(ref) for ref in by_field["external_ref"]}
        project_id = by_field["project"]["id"]
        return [
            v
            for v in self.versions
            if v.external_ref in wanted and (v.project or {}).get("id") == project_id
        ]

    def add_versions_to_playlist(
        self, playlist_id: int, version_ids: list[int]
    ) -> list[int]:
        self.appends.append((playlist_id, version_ids))
        existing = self.playlist_versions[playlist_id]
        appended = [vid for vid in version_ids if vid not in existing]
        existing.extend(appended)
        return appended


class NoReviewIdField(FakeProdtrack):
    """A deployment with no external-ref field configured."""

    def find(self, entity_type: str, filters: list[dict[str, Any]], limit: int = 0):
        raise ValueError("Unknown field 'external_ref' for entity type 'version'")


@pytest.fixture
def prodtrack():
    fake = FakeProdtrack()
    app.dependency_overrides[get_prodtrack_provider_cached] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _add(client: TestClient, jts: list[int], playlist_id: int = 400):
    return client.post(f"/playlists/{playlist_id}/versions", json={"jts": jts})


def _statuses(response) -> list[tuple[int, str]]:
    return [(o["jts"], o["status"]) for o in response.json()["outcomes"]]


def test_a_pasted_list_goes_in_in_one_go(prodtrack, client):
    response = _add(client, [1787, 1789])

    assert response.status_code == 201
    assert response.json()["added_count"] == 2
    assert _statuses(response) == [(1787, "added"), (1789, "added")]
    assert prodtrack.playlist_versions[400] == [300, 301, 302]


def test_the_list_lands_in_the_order_it_was_pasted(prodtrack, client):
    _add(client, [1789, 1787])

    assert prodtrack.appends == [(400, [302, 301])]


def test_the_whole_list_costs_one_query(prodtrack, client):
    """Forty ids off a turnover sheet must not be forty round trips to ShotGrid."""
    calls = []
    original = prodtrack.find
    prodtrack.find = lambda *a, **k: (calls.append(a), original(*a, **k))[1]

    _add(client, [1786, 1787, 1789])

    assert len(calls) == 1


def test_each_id_is_answered_for_separately(prodtrack, client):
    """The mixed paste: one already there, one good, one stale. All three get an answer."""
    response = _add(client, [1786, 1787, 4242])

    assert response.status_code == 201
    assert _statuses(response) == [
        (1786, "already_in_playlist"),
        (1787, "added"),
        (4242, "not_found"),
    ]
    assert response.json()["added_count"] == 1


def test_an_outcome_names_the_version_it_resolved_to(prodtrack, client):
    """A number alone is unreadable; the name is how someone checks it added what they meant."""
    outcome = _add(client, [1787]).json()["outcomes"][0]

    assert outcome["version_id"] == 301
    assert outcome["version_name"] == "[1787] nite-seq.pvs-camera-121"


def test_an_id_repeated_in_a_paste_is_one_version(prodtrack, client):
    response = _add(client, [1787, 1787])

    assert _statuses(response) == [(1787, "added")]
    assert prodtrack.playlist_versions[400] == [300, 301]


def test_a_review_id_from_another_show_is_not_found_here(prodtrack, client):
    """Ids are only unique within a show, and the playlist decides which show that is."""
    prodtrack.versions = [v for v in prodtrack.versions if v.id == 999]

    response = _add(client, [1786])

    assert _statuses(response) == [(1786, "not_found")]
    assert prodtrack.appends == [(400, [])]


def test_nothing_found_is_still_an_answer_not_an_error(prodtrack, client):
    """A paste of stale ids is a normal thing to do; the reply says so id by id."""
    response = _add(client, [4242, 4243])

    assert response.status_code == 201
    assert response.json()["added_count"] == 0
    assert _statuses(response) == [(4242, "not_found"), (4243, "not_found")]


def test_unknown_playlist_is_not_found(prodtrack, client):
    assert _add(client, [1787], playlist_id=401).status_code == 404


def test_an_empty_list_is_rejected(prodtrack, client):
    assert _add(client, []).status_code == 422
    assert prodtrack.appends == []


def test_a_deployment_without_a_review_id_field_says_which_setting_is_missing(client):
    app.dependency_overrides[get_prodtrack_provider_cached] = lambda: NoReviewIdField()
    try:
        response = _add(client, [1787])
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 501
    assert "PRODTRACK_VERSION_EXTERNAL_REF_FIELD" in response.json()["detail"]
