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
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dna.models.draft_note import DraftNote
from dna.models.entity import Version
from dna.models.stored_segment import StoredSegment

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


def _send_gmail(to: str, subject: str, html_content: str, cc: Optional[str] = None) -> None:
    msg = MIMEMultipart("mixed")
    msg["to"] = to
    msg["from"] = EMAIL_SENDER
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = _get_gmail_service()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _send_smtp(to: str, subject: str, html_content: str, cc: Optional[str] = None) -> None:
    recipients = [to]
    if cc:
        recipients += [a.strip() for a in cc.split(",") if a.strip()]
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(html_content, "html", "utf-8"))
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


def send_notes_email(to: str, subject: str, html_content: str, cc: Optional[str] = None) -> None:
    if not EMAIL_SENDER:
        raise ValueError("EMAIL_SENDER is not set — add it to docker-compose.local.yml")
    if EMAIL_PROVIDER == "smtp":
        _send_smtp(to, subject, html_content, cc=cc)
    else:
        _send_gmail(to, subject, html_content, cc=cc)


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


def _display_name(email: str) -> str:
    local = email.split("@")[0]
    return local.replace(".", " ").replace("_", " ").title()


def build_notes_html(
    playlist_name: str,
    project_name: str,
    sent_by: str,
    versions: list[Version],
    drafts_by_version: dict[int, list[DraftNote]],
    segments_by_version: dict[int, list[StoredSegment]],
) -> str:
    date_str = datetime.now().strftime("%B %d, %Y, %I:%M %p")

    header = f"""
    <table style="border-collapse:collapse;width:100%;margin-bottom:20px;font-size:13px;">
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;width:130px;">Show:</td>
          <td style="padding:3px 0;">{_h(project_name)}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Title:</td>
          <td style="padding:3px 0;">{_h(playlist_name)}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Screening Date:</td>
          <td style="padding:3px 0;">{date_str}</td></tr>
      <tr><td style="padding:3px 8px 3px 0;font-weight:bold;">Notes By:</td>
          <td style="padding:3px 0;">{_h(sent_by)}</td></tr>
    </table>"""

    rows = []
    for idx, version in enumerate(versions, 1):
        artist = _h(_attr(version.user, "name") if version.user else "")
        entity_name = _h(_attr(version.entity, "name") if version.entity else "")
        task_name = ""
        if version.task:
            step = (version.task.get("pipeline_step") if isinstance(version.task, dict)
                    else getattr(version.task, "pipeline_step", None))
            task_name = _h(_attr(step, "name") if step else (_attr(version.task, "name") or ""))
        frame_path = _h(version.frame_path or version.movie_path or "")
        version_name = _h(version.name or f"Version {version.id}")

        notes_parts = []
        for draft in drafts_by_version.get(version.id, []):
            if draft.content and draft.content.strip():
                author = _h(_display_name(draft.user_email))
                content = _h(draft.content.strip()).replace("\n", "<br>")
                notes_parts.append(
                    f'<p style="margin:4px 0;"><strong>{author}:</strong> {content}</p>'
                )

        segs = segments_by_version.get(version.id, [])
        if segs:
            lines = []
            prev_speaker = None
            for seg in segs:
                speaker = seg.speaker or "Unknown"
                if speaker != prev_speaker:
                    lines.append(f'<strong>{_h(speaker)}:</strong> {_h(seg.text)}')
                    prev_speaker = speaker
                else:
                    lines.append(_h(seg.text))
            notes_parts.append(
                '<p style="margin:8px 0 2px;font-size:11px;color:#888;font-style:italic;">Transcript:</p>'
                + "<br>".join(f'<span style="font-size:12px;">{l}</span>' for l in lines)
            )

        notes_html = "".join(notes_parts) or '<span style="color:#aaa;">—</span>'
        row_bg = "#ffffff" if idx % 2 == 1 else "#f9f9f9"
        td = f'border:1px solid #ddd;background:{row_bg};'

        rows.append(f"""
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
          <td colspan="4" style="padding:10px 8px;{td}">{notes_html}</td>
        </tr>""")

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
