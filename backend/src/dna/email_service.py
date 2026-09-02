"""Email service: HTML generation and Gmail/SMTP dispatch for daily notes.

Mirrors experimental/spi/note_assistant_v2/backend/email_service.py:
  EMAIL_PROVIDER=gmail (default) uses Gmail API via token.json + client_secret.json
  EMAIL_PROVIDER=smtp uses SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_TLS)
  EMAIL_SENDER must always be set to the From address.

Gmail credential files are resolved from the GMAIL_CREDENTIALS_DIR env var,
defaulting to /app/gmail-credentials/ (mount a volume there in docker-compose).
"""

import base64
import html
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dna.auth.email import display_name as _display_name
from dna.models.draft_note import DraftNote
from dna.models.entity import Version
from dna.review_links import version_anchors

EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "gmail")
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
_smtp_port = os.getenv("SMTP_PORT")
SMTP_PORT = int(_smtp_port) if _smtp_port else None
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_TLS = os.getenv("SMTP_TLS", "false").lower() == "true"

_CREDENTIALS_DIR = os.getenv("GMAIL_CREDENTIALS_DIR", "/app/gmail-credentials")
CREDENTIALS_FILE = os.path.join(_CREDENTIALS_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(_CREDENTIALS_DIR, "token.json")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


# ---------------------------------------------------------------------------
# Send helpers (Gmail + SMTP)
# ---------------------------------------------------------------------------


def _get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
        except Exception as e:
            raise RuntimeError(f"Failed to load Gmail token: {e}")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            try:
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except OSError:
                pass  # read-only mount; refreshed creds are valid in memory
        else:
            raise RuntimeError(
                f"Gmail token missing or invalid. Run the OAuth flow once: "
                f"token.json must exist at {TOKEN_FILE}"
            )
    return build("gmail", "v1", credentials=creds)


@dataclass(frozen=True)
class InlineImage:
    """An image carried IN the message and referenced by `cid:`, not fetched from a URL.

    Embedded rather than linked because the images are poster frames served by the air-gapped
    host: a mail client only reaches it from inside the network, and Gmail's web client never
    does — it asks a Google proxy to fetch every image, and that proxy cannot see an internal
    address. A linked thumbnail is therefore broken for exactly the readers most likely to open
    the email on their phone.
    """

    cid: str
    data: bytes
    filename: str
    subtype: str = "jpeg"


def _build_message(
    to: str,
    subject: str,
    html_content: str,
    cc: Optional[str] = None,
    inline_images: Optional[list[InlineImage]] = None,
) -> MIMEMultipart:
    """The message both transports send.

    `multipart/related` when there are inline images and `multipart/mixed` when there are not:
    "related" is what tells a client the parts are pieces of the HTML rather than attachments,
    and a message with no images gets exactly the structure it always had.
    """
    msg = MIMEMultipart("related" if inline_images else "mixed")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    for image in inline_images or []:
        part = MIMEImage(image.data, _subtype=image.subtype)
        # Angle brackets: the header is a message-id, and `src="cid:x"` refers to `<x>`. Without
        # them some clients simply do not match the two, and the thumbnail silently vanishes.
        part.add_header("Content-ID", f"<{image.cid}>")
        part.add_header("Content-Disposition", "inline", filename=image.filename)
        msg.attach(part)
    return msg


def _send_gmail(
    to: str,
    subject: str,
    html_content: str,
    cc: Optional[str] = None,
    inline_images: Optional[list[InlineImage]] = None,
) -> None:
    msg = _build_message(to, subject, html_content, cc=cc, inline_images=inline_images)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = _get_gmail_service()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _send_smtp(
    to: str,
    subject: str,
    html_content: str,
    cc: Optional[str] = None,
    inline_images: Optional[list[InlineImage]] = None,
) -> None:
    recipients = [to]
    if cc:
        recipients += [a.strip() for a in cc.split(",") if a.strip()]
    msg = _build_message(to, subject, html_content, cc=cc, inline_images=inline_images)
    smtp = smtplib.SMTP()
    if SMTP_PORT is not None:
        smtp.connect(SMTP_HOST, SMTP_PORT)
    else:
        smtp.connect(SMTP_HOST)
    if SMTP_TLS:
        smtp.starttls()
    if SMTP_USER and SMTP_PASSWORD:
        smtp.login(SMTP_USER, SMTP_PASSWORD)
    smtp.sendmail(EMAIL_SENDER, recipients, msg.as_string())
    smtp.close()


def send_notes_email(
    to: str,
    subject: str,
    html_content: str,
    cc: Optional[str] = None,
    inline_images: Optional[list[InlineImage]] = None,
) -> None:
    if not EMAIL_SENDER:
        raise ValueError("EMAIL_SENDER is not set — add it to docker-compose.local.yml")
    if EMAIL_PROVIDER == "smtp":
        _send_smtp(to, subject, html_content, cc=cc, inline_images=inline_images)
    else:
        _send_gmail(to, subject, html_content, cc=cc, inline_images=inline_images)


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


def _h(s: Optional[str]) -> str:
    return html.escape(s or "")


def _attr(obj, *keys: str) -> Optional[str]:
    """Get a string attribute from an object or dict, trying each key in order."""
    for key in keys:
        val = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        if val is not None:
            return str(val)
    return None


def poster_cid(playlist_id: int, version_id: int) -> str:
    """The Content-ID one shot's poster is carried under.

    Written by one function because two things have to agree on it exactly: the `<img src="cid:…">`
    in the body, and the Content-ID header on the attached part. A mismatch is silent — the client
    shows a broken image and nothing anywhere reports why — so neither side spells it itself.
    """
    return f"dna-poster-{playlist_id}-{version_id}"


def build_notes_html(
    playlist_name: str,
    project_name: str,
    sent_by: str,
    versions: list[Version],
    drafts_by_version: dict[int, list[DraftNote]],
    review_url: Optional[str] = None,
    playlist_url: Optional[str] = None,
    poster_cids: Optional[dict[int, str]] = None,
) -> str:
    """The notes email, and — when the deployment knows its own address — the way back into it.

    `review_url` turns every version name into a link to that shot on the artist review page,
    where the same notes sit next to the transcript and the part of the meeting recording that
    discussed them. The anchors come from `review_links.version_anchors` rather than being
    written here, because the page derives its own from the same function: a link is only worth
    sending if the thing it lands on agrees about what it is called.

    `playlist_url` is the same review, in the production tracker — the place a supervisor goes to
    see the versions themselves rather than what was said about them. The two are offered side by
    side in the header because they answer different questions and neither replaces the other.

    `poster_cids` maps a version to the Content-ID of a still taken from the moment that shot came
    up in the meeting. It is what makes the clip look like a clip: the row already links to the
    recording, but nothing in a page of text says a video is one click away, and a frame with a
    play button on it says so before anything is read. Versions with no poster keep the layout
    they always had, so a playlist with no recording is unchanged.

    Everything optional here degrades to the email as it was before. A mail client has no origin
    to resolve a bare path against, so a deployment that has not been told where it is served
    from (DNA_APP_BASE_URL unset) sends plain text rather than links that go nowhere.
    """
    date_str = datetime.now().strftime("%B %d, %Y, %I:%M %p")
    anchors = version_anchors(versions) if review_url else {}
    poster_cids = poster_cids or {}

    review_row = ""
    if review_url:
        review_row = f"""
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Review Page:</td>
          <td style="padding:3px 0;"><a href="{_h(review_url)}"
             style="color:#1a5fb4;">Open notes, transcript and recording</a></td></tr>"""

    playlist_row = ""
    if playlist_url:
        playlist_row = f"""
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Playlist:</td>
          <td style="padding:3px 0;"><a href="{_h(playlist_url)}"
             style="color:#1a5fb4;">{_h(playlist_name)} in ShotGrid</a></td></tr>"""

    header = f"""
    <table style="border-collapse:collapse;width:100%;margin-bottom:20px;font-size:13px;">
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;width:130px;">Show:</td>
          <td style="padding:3px 0;">{_h(project_name)}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Title:</td>
          <td style="padding:3px 0;">{_h(playlist_name)}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Screening Date:</td>
          <td style="padding:3px 0;">{date_str}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Notes By:</td>
          <td style="padding:3px 0;">{_h(sent_by)}</td></tr>{playlist_row}{review_row}
    </table>"""

    rows = []
    for idx, version in enumerate(versions, 1):
        artist = _h(_attr(version.user, "name") if version.user else "")
        entity_name = _h(_attr(version.entity, "name") if version.entity else "")
        task_name = ""
        if version.task:
            step = (
                version.task.get("pipeline_step")
                if isinstance(version.task, dict)
                else getattr(version.task, "pipeline_step", None)
            )
            task_name = _h(
                _attr(step, "name") if step else (_attr(version.task, "name") or "")
            )
        frame_path = _h(version.frame_path or version.movie_path or "")
        version_name = _h(version.name or f"Version {version.id}")
        anchor = anchors.get(version.id)
        if review_url and anchor:
            version_name = (
                f'<a href="{_h(review_url)}#{_h(anchor)}" '
                f'style="color:#1a5fb4;text-decoration:none;">{version_name}</a>'
            )

        notes_parts = []
        for draft in drafts_by_version.get(version.id, []):
            if draft.content and draft.content.strip():
                author = _h(_display_name(draft.user_email))
                content = _h(draft.content.strip()).replace("\n", "<br>")
                notes_parts.append(
                    f'<p style="margin:4px 0;"><strong>{author}:</strong> {content}</p>'
                )

        notes_html = "".join(notes_parts) or '<span style="color:#aaa;">—</span>'
        row_bg = "#ffffff" if idx % 2 == 1 else "#f9f9f9"
        td = f"border:1px solid #ddd;background:{row_bg};"

        # The thumbnail and the notes share a row, the picture on the left under the file spec.
        # Sized in the tag as well as the style because a mail client that strips CSS still has
        # to reserve the space, and one that blocks images shows the alt text in it — which is
        # why the alt text is the invitation rather than a description of the picture.
        thumbnail_cell = ""
        cid = poster_cids.get(version.id)
        if cid:
            image = (
                f'<img src="cid:{_h(cid)}" width="160" height="90" '
                f'alt="&#9654; Play this shot in the meeting recording" '
                f'style="display:block;width:160px;height:90px;border:1px solid #ccc;'
                f'border-radius:3px;" />'
            )
            if review_url and anchor:
                image = (
                    f'<a href="{_h(review_url)}#{_h(anchor)}" '
                    f'style="text-decoration:none;">{image}</a>'
                )
            thumbnail_cell = f'<td style="padding:8px;vertical-align:top;{td}width:176px;">{image}</td>'

        notes_row = (
            f'{thumbnail_cell}<td colspan="{3 if thumbnail_cell else 4}" '
            f'style="padding:10px 8px;vertical-align:top;{td}">{notes_html}</td>'
        )

        rows.append(
            f"""
        <tr>
          <td style="padding:10px 8px;text-align:center;vertical-align:middle;{td}
                     font-weight:bold;width:28px;" rowspan="3">{idx}</td>
          <td style="padding:10px 8px;vertical-align:top;{td}white-space:nowrap;">
            <strong>{version_name}</strong></td>
          <td style="padding:10px 8px;vertical-align:top;{td}">{artist}</td>
          <td style="padding:10px 8px;vertical-align:top;{td}">{entity_name}</td>
          <td style="padding:10px 8px;vertical-align:top;{td}white-space:nowrap;">{task_name}</td>
        </tr>
        <tr>
          <td style="padding:4px 8px;font-size:11px;font-weight:bold;color:#555;{td}white-space:nowrap;">File Spec</td>
          <td colspan="3" style="padding:4px 8px;font-size:11px;color:#555;{td}word-break:break-all;">
            {frame_path or '<span style="color:#aaa;">—</span>'}</td>
        </tr>
        <tr>
          {notes_row}
        </tr>"""
        )

    versions_table = f"""
    <table style="border-collapse:collapse;width:100%;font-size:13px;">
      <thead>
        <tr style="background:#2c2c2c;color:#fff;">
          <th style="padding:8px;text-align:center;border:1px solid #444;">#</th>
          <th style="padding:8px;text-align:left;border:1px solid #444;">Version</th>
          <th style="padding:8px;text-align:left;border:1px solid #444;">Artist</th>
          <th style="padding:8px;text-align:left;border:1px solid #444;">Entity</th>
          <th style="padding:8px;text-align:left;border:1px solid #444;">Task</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""

    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222;
                   max-width:1200px;margin:0 auto;padding:20px;">
  {header}
  {versions_table}
</body></html>"""
