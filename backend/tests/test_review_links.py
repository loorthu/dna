"""Tests for review page addresses.

These strings are the contract between two things that never call each other: the mailer writes
them and the resolver reads them. Testing them here is what keeps a change on one side from
quietly breaking the other.
"""

import pytest

from dna.review_links import (
    playlist_path,
    project_segment,
    review_url,
    slugify,
    version_anchors,
)


class Version:
    """The two fields anchors are built from."""

    def __init__(self, id, name):
        self.id = id
        self.name = name


class TestSlugify:
    def test_lowercases_and_joins_with_hyphens(self):
        assert slugify("Dailies Comp 2026-08-30") == "dailies-comp-2026-08-30"

    def test_folds_accents_to_their_base_letter(self):
        # Dropping them instead would slug "Prévis" to "prvis", which nobody would recognise.
        assert slugify("Prévis") == "previs"

    def test_collapses_runs_of_punctuation(self):
        assert slugify("Comp // Lighting -- Round 2") == "comp-lighting-round-2"

    def test_strips_leading_and_trailing_separators(self):
        assert slugify("  --Dailies--  ") == "dailies"

    def test_empty_and_none_produce_empty(self):
        assert slugify(None) == ""
        assert slugify("") == ""
        assert slugify("!!!") == ""

    def test_keep_passes_named_characters_through(self):
        assert slugify("abc_0100_comp_v012", keep="_.") == "abc_0100_comp_v012"
        assert slugify("abc_0100 comp", keep="_") == "abc_0100-comp"


class TestProjectSegment:
    def test_prefers_the_code(self):
        assert project_segment("ABC", "A Big Coproduction") == "abc"

    def test_falls_back_to_the_name_when_there_is_no_code(self):
        # The site this was built against has no tank_name on any project, so every code comes
        # back empty and the name is the short handle — "ap1", "bogz". Without this fallback
        # every review link there would collapse to the id form.
        assert project_segment(None, "ap1") == "ap1"
        assert project_segment("", "ap1") == "ap1"

    def test_empty_when_there_is_neither(self):
        assert project_segment(None, None) == ""


class TestPlaylistPath:
    def test_name_form_when_both_halves_are_usable(self):
        assert (
            playlist_path(4471, "Dailies Comp 2026-08-30", "ABC")
            == "/review/abc/dailies-comp-2026-08-30"
        )

    def test_id_form_when_the_playlist_has_no_name(self):
        assert playlist_path(4471, "", "ABC") == "/review/id/4471"
        assert playlist_path(4471, None, "ABC") == "/review/id/4471"

    def test_id_form_when_the_project_segment_is_missing(self):
        # A slug with no project is ambiguous across shows, which is the whole reason the show is
        # in the path — without one the readable form would be a worse address, not a nicer one.
        assert playlist_path(4471, "Dailies", "") == "/review/id/4471"
        assert playlist_path(4471, "Dailies", None) == "/review/id/4471"

    def test_a_project_code_of_id_cannot_shadow_the_id_form(self):
        assert playlist_path(4471, "Dailies", "ID") == "/review/id/4471"


class TestVersionAnchors:
    def test_version_names_survive_intact(self):
        anchors = version_anchors([Version(1, "abc_0100_comp_v012")])
        assert anchors == {1: "abc_0100_comp_v012"}

    def test_repeated_names_are_disambiguated_by_id(self):
        # An anchor that appears twice sends every link to the first one. The first occurrence
        # keeps the readable form so only the collision pays for itself.
        anchors = version_anchors(
            [Version(1, "abc_0100_comp_v012"), Version(2, "abc_0100_comp_v012")]
        )
        assert anchors == {1: "abc_0100_comp_v012", 2: "abc_0100_comp_v012-2"}

    def test_a_version_with_no_name_falls_back_to_its_id(self):
        assert version_anchors([Version(7, None)]) == {7: "version-7"}

    def test_versions_may_be_dicts(self):
        assert version_anchors([{"id": 3, "name": "xyz_v001"}]) == {3: "xyz_v001"}

    def test_versions_without_an_id_are_skipped(self):
        assert version_anchors([Version(None, "nameless")]) == {}


class TestReviewUrl:
    def test_none_when_the_deployment_has_no_configured_address(self, monkeypatch):
        # A mail client has no origin to resolve a bare path against, so no base means no link
        # rather than a link that goes nowhere.
        monkeypatch.delenv("DNA_APP_BASE_URL", raising=False)
        assert review_url(4471, "Dailies", "ABC") is None

    def test_joins_the_base_to_the_path(self, monkeypatch):
        monkeypatch.setenv("DNA_APP_BASE_URL", "https://dna.example.com")
        assert (
            review_url(4471, "Dailies", "ABC")
            == "https://dna.example.com/review/abc/dailies"
        )

    def test_uses_the_project_name_when_the_site_has_no_codes(self, monkeypatch):
        monkeypatch.setenv("DNA_APP_BASE_URL", "https://dna.example.com")
        assert (
            review_url(4471, "Dailies", "", "ap1")
            == "https://dna.example.com/review/ap1/dailies"
        )

    def test_tolerates_a_trailing_slash_on_the_base(self, monkeypatch):
        monkeypatch.setenv("DNA_APP_BASE_URL", "https://dna.example.com/")
        assert (
            review_url(4471, "Dailies", "ABC")
            == "https://dna.example.com/review/abc/dailies"
        )
