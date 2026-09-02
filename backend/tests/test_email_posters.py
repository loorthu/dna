"""The notes email's thumbnails: the picture that says a clip is one click away.

Two failure modes are worth holding still, and both look like nothing rather than like an error.

  • The Content-ID in the body and the one on the attached part must be the same string. A
    mismatch shows the reader a broken image and reports nothing anywhere, which is why one
    function writes it and both sides ask that function.
  • The images are carried IN the message, not linked. They live on the air-gapped host, and a
    linked thumbnail is broken for exactly the readers most likely to open the email on a phone:
    Gmail's web client fetches every image through a Google proxy that cannot reach it.

The third thing here is the layout rule — a playlist with no recording must send the email it
always sent, rather than a table with an empty column down the side of it.
"""

import re
from email import message_from_bytes

from dna.email_service import (
    InlineImage,
    _build_message,
    build_notes_html,
    poster_cid,
)
from dna.models.entity import Version

VERSIONS = [
    Version(id=900, name="abc_0100_comp_v012"),
    Version(id=901, name="abc_0110_comp_v004"),
]
REVIEW = "https://dna.example.com/review/abc/dailies-comp-2026-08-30"


def _html(poster_cids=None, review_url=REVIEW) -> str:
    return build_notes_html(
        playlist_name="Dailies Comp 2026-08-30",
        project_name="ABC Show",
        sent_by="sup@example.com",
        versions=VERSIONS,
        drafts_by_version={},
        review_url=review_url,
        poster_cids=poster_cids,
    )


# ── the body ────────────────────────────────────────────────────────────────────────────────────


def test_a_shot_with_a_poster_shows_it_linked_to_its_own_place_in_the_recording():
    """The picture itself is the click target, and it lands on the shot, not the top of the page."""
    html = _html({900: poster_cid(12, 900)})
    linked = re.search(
        r'<a href="([^"]+)"[^>]*>\s*<img src="cid:dna-poster-12-900"', html
    )
    assert linked, "the thumbnail is wrapped in the link, not merely near one"
    assert linked.group(1) == f"{REVIEW}#abc_0100_comp_v012"


def test_the_thumbnail_is_sized_in_the_tag_as_well_as_the_style():
    """A client that strips CSS still has to reserve the space, or the table reflows as it loads."""
    html = _html({900: poster_cid(12, 900)})
    assert 'width="160" height="90"' in html


def test_the_alt_text_is_the_invitation_not_a_description():
    """Images are blocked by default in more clients than not; the alt text is what is read."""
    html = _html({900: poster_cid(12, 900)})
    assert "Play this shot in the meeting recording" in html


def test_a_playlist_with_no_recording_sends_the_email_it_always_sent():
    html = _html(None)
    assert "cid:" not in html
    assert 'colspan="4"' in html, "the notes still span the whole row"


def test_only_the_shots_that_have_a_poster_get_a_cell():
    """Mixed is the normal case: a shot nobody discussed has no span to take a frame from."""
    html = _html({900: poster_cid(12, 900)})
    assert html.count("cid:dna-poster-12-900") == 1
    assert "dna-poster-12-901" not in html
    assert 'colspan="3"' in html and 'colspan="4"' in html


def test_a_poster_still_shows_when_the_deployment_has_no_address():
    """The picture is worth showing even when there is nowhere to send the click."""
    html = _html({900: poster_cid(12, 900)}, review_url=None)
    assert 'src="cid:dna-poster-12-900"' in html
    assert "/review/" not in html


# ── the message ─────────────────────────────────────────────────────────────────────────────────


def test_the_body_and_the_attached_part_agree_on_the_content_id():
    cid = poster_cid(12, 900)
    message = message_from_bytes(
        _build_message(
            "artist@example.com",
            "Dailies",
            _html({900: cid}),
            inline_images=[
                InlineImage(cid=cid, data=b"\xff\xd8JPEG", filename="a.jpg")
            ],
        ).as_bytes()
    )
    image = [p for p in message.walk() if p.get_content_maintype() == "image"]
    assert len(image) == 1
    # Angle brackets on the header, none in the URL: `src="cid:x"` refers to `<x>`, and clients
    # that do not match the two simply show nothing.
    assert image[0]["Content-ID"] == f"<{cid}>"
    assert image[0].get_payload(decode=True) == b"\xff\xd8JPEG"


def test_a_message_carrying_images_is_related_not_mixed():
    """ "related" is what says the parts are pieces of the HTML rather than attachments."""
    message = _build_message(
        "artist@example.com",
        "Dailies",
        "<p>hi</p>",
        inline_images=[InlineImage(cid="c", data=b"x", filename="a.jpg")],
    )
    assert message.get_content_subtype() == "related"


def test_a_message_with_no_images_keeps_the_structure_it_always_had():
    message = _build_message("artist@example.com", "Dailies", "<p>hi</p>")
    assert message.get_content_subtype() == "mixed"
    assert not [p for p in message.walk() if p.get_content_maintype() == "image"]


def test_the_images_are_carried_rather_than_linked():
    """The share they were written to is not reachable from every client that opens the email."""
    html = _html({900: poster_cid(12, 900)})
    assert (
        "/recordings/" not in html
    ), "the copy on the share is never the email's source"
    assert all(
        src.startswith("cid:") for src in re.findall(r'<img[^>]+src="([^"]+)"', html)
    )
