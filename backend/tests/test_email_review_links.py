"""The notes email's links back into the artist review page.

The email is the only place these links are written, and it is sent to people who cannot ask
anyone what went wrong when one does not work. Two things are worth holding still: a deployment
that has not been told its own address sends the email it always sent, and the anchors it writes
are the ones the page will actually have.
"""

from dna.email_service import build_notes_html
from dna.models.entity import Version
from dna.review_links import version_anchors

VERSIONS = [
    Version(id=900, name="abc_0100_comp_v012"),
    Version(id=901, name="abc_0110_comp_v004"),
]


def _html(review_url=None) -> str:
    return build_notes_html(
        playlist_name="Dailies Comp 2026-08-30",
        project_name="ABC Show",
        sent_by="sup@example.com",
        versions=VERSIONS,
        drafts_by_version={},
        review_url=review_url,
    )


def test_without_a_base_url_the_email_carries_no_links():
    """A mail client has no origin to resolve a bare path against."""
    html = _html()
    assert "/review/" not in html
    assert "Review Page" not in html
    # The version names are still there — just as text, the way they always were.
    assert "abc_0100_comp_v012" in html


def test_the_header_offers_the_playlist():
    html = _html("https://dna.example.com/review/abc/dailies-comp-2026-08-30")
    assert "Review Page" in html
    assert 'href="https://dna.example.com/review/abc/dailies-comp-2026-08-30"' in html


def test_a_version_name_opens_that_version_in_the_production_tracker():
    """The name is the version, so it opens the version. The thumbnail carries the recording.

    Before the thumbnail existed the name had to be both, and it could only be one — a reader
    who wanted the version itself had to go and find it. Now each link goes where its own shape
    already suggests.
    """
    base = "https://dna.example.com/review/abc/dailies-comp-2026-08-30"
    html = build_notes_html(
        playlist_name="Dailies Comp 2026-08-30",
        project_name="ABC Show",
        sent_by="sup@example.com",
        versions=[
            Version(
                id=900,
                name="abc_0100_comp_v012",
                prodtrack_detail_url="https://sg.example.com/detail/Version/900",
            )
        ],
        drafts_by_version={},
        review_url=base,
    )
    assert 'href="https://sg.example.com/detail/Version/900"' in html
    assert f"{base}#abc_0100_comp_v012" not in html, (
        "the name must not also carry the review anchor — that is the thumbnail's job, and two "
        "links to different places under one piece of text is how a reader learns not to trust "
        "either"
    )


def test_the_review_anchor_is_the_fallback_when_there_is_no_tracker_page():
    """A provider with no web UI must not leave the shot with no link at all.

    The mock provider is one, and so is ShotGrid with no SHOTGRID_URL set. A shot nobody
    discussed has no thumbnail either, so without this it would carry nothing.
    """
    base = "https://dna.example.com/review/abc/dailies-comp-2026-08-30"
    html = _html(base)
    assert f'href="{base}#abc_0100_comp_v012"' in html
    assert f'href="{base}#abc_0110_comp_v004"' in html


def test_the_anchors_are_the_ones_the_page_will_build():
    """Written by one function so the two sides cannot drift into disagreeing."""
    base = "https://dna.example.com/review/abc/dailies"
    html = _html(base)
    for anchor in version_anchors(VERSIONS).values():
        assert f'href="{base}#{anchor}"' in html


def test_a_version_with_no_name_still_gets_a_link():
    html = build_notes_html(
        playlist_name="Dailies",
        project_name="ABC Show",
        sent_by="sup@example.com",
        versions=[Version(id=42, name=None)],
        drafts_by_version={},
        review_url="https://dna.example.com/review/abc/dailies",
    )
    assert "#version-42" in html


def test_the_header_offers_the_playlist_in_the_production_tracker():
    """A different question from the review page, so it gets its own row rather than replacing it.

    The review page answers "what was said about my shot"; the playlist answers "show me the
    versions". A supervisor reading the email wants the second one often enough that having to
    go and find it is the difference between the email being the whole handoff and not.
    """
    html = build_notes_html(
        playlist_name="Dailies Comp 2026-08-30",
        project_name="ABC Show",
        sent_by="sup@example.com",
        versions=VERSIONS,
        drafts_by_version={},
        review_url="https://dna.example.com/review/abc/dailies-comp-2026-08-30",
        playlist_url="https://sg.example.com/detail/Playlist/4471",
    )
    assert 'href="https://sg.example.com/detail/Playlist/4471"' in html
    assert "Review Page" in html, "the two links are offered together, not instead"


def test_a_provider_with_no_web_ui_simply_omits_the_playlist_row():
    assert "detail/Playlist" not in _html()
    assert "Playlist:" not in _html()
