#!/usr/bin/env python3
"""
Sync Google Meet Recordings to Database

Discovers finished Google Meet meetings with video recordings and ShotGrid
playlist links, then stores them in a SQLite database for pipeline processing.

Usage:
    python sync_meetings_to_db.py                    # Sync today's meetings
    python sync_meetings_to_db.py --days 1           # Include yesterday
    python sync_meetings_to_db.py --verbose          # Verbose output
    python sync_meetings_to_db.py --list              # List all meetings
    python sync_meetings_to_db.py --list --status pending  # Filter by status
    python sync_meetings_to_db.py --update-status EVENT_ID STATUS
    python sync_meetings_to_db.py --cron             # Cron mode: silent unless new meetings found
"""

import argparse
import contextlib
import io
import os
import re
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.text import MIMEText

# Add parent directory to path for importing meeting_service and shotgrid_service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import calendar functions from get_gcalendar_entries.py
from get_gcalendar_entries import (
    get_calendar_service,
    get_drive_service,
    get_meetings,
)

# Import database functions from meeting_service
from meeting_service import (
    init_db,
    meeting_exists,
    insert_meeting,
    update_meeting_status,
    get_meetings as db_get_meetings,
    DEFAULT_DB_PATH
)

from shotgrid_service import find_playlist_for_meeting, load_show_mapping, _strip_calendar_suffix


# =============================================================================
# ShotGrid Link Extraction
# =============================================================================

def extract_sg_playlist_link(text: str) -> str:
    """Extract ShotGrid playlist link from text."""
    if not text:
        return None

    # Match ShotGrid/ShotGun playlist URLs
    # Examples:
    #   https://spi.shotgrid.autodesk.com/page/43590#Playlist_412983
    #   https://studio.shotgunstudio.com/page/123#Playlist_456
    patterns = [
        r'https?://[^\s"<>]*shotgrid[^\s"<>]*#Playlist_\d+',
        r'https?://[^\s"<>]*shotgun[^\s"<>]*#Playlist_\d+',
        r'https?://[^\s"<>]*shotgrid[^\s"<>]*/playlist/\d+',
        r'https?://[^\s"<>]*shotgun[^\s"<>]*/playlist/\d+',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


# =============================================================================
# Main Sync Logic
# =============================================================================

def _resolve_meeting_date(start_time: str) -> datetime:
    """Parse meeting start_time ISO string to a datetime object."""
    return datetime.fromisoformat(start_time.replace('Z', '+00:00'))


def _pipeline_command(meeting: dict, sg_playlist_link: str, show_mapping: dict = None) -> str:
    """Build the run_pipeline.sh command for a synced meeting."""
    title = meeting['title']
    project = (title.split(':')[0] if ':' in title else title.split()[0]).strip().lower()

    stripped = _strip_calendar_suffix(title, show_mapping or {})
    if ':' in stripped:
        meeting_type = stripped.split(':', 1)[1].strip()
    else:
        meeting_type = ' '.join(stripped.split()[1:])

    start_time = meeting.get('start_time', '')
    if start_time:
        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        date_str = dt.strftime('%m-%d-%y')
    else:
        date_str = datetime.now().strftime('%m-%d-%y')

    subject = f"{project.upper()} {meeting_type} {date_str}"

    return (
        f"./run_pipeline.sh"
        f" \"{meeting['recording_link']}\""
        f" \"{sg_playlist_link}\""
        f" --project {project}"
        f" --subject \"{subject}\""
    )


def sync_meetings_to_db(conn, calendar_service, drive_service,
                        days: int = 0, verbose: bool = False) -> dict:
    """
    Sync finished meetings with recordings and SG links to database.
    Returns dict with counts: {synced, skipped, no_sg_link, no_recording, errors}
    Also includes 'pipeline_commands': list of run_pipeline.sh commands for newly synced meetings.
    """
    stats = {'synced': 0, 'skipped': 0, 'no_sg_link': 0, 'no_recording': 0, 'errors': 0,
             'pipeline_commands': []}

    # Get finished meetings with Google Meet links
    meetings = get_meetings(
        calendar_service,
        drive_service=drive_service,
        days=days,
        only_with_meet=True,
        only_finished=True
    )

    if verbose:
        print(f"Found {len(meetings)} finished Google Meet meeting(s)")

    show_mapping = load_show_mapping()

    for meeting in meetings:
        title = meeting['title']

        # Skip if already in database
        if meeting_exists(conn, meeting['event_id']):
            stats['skipped'] += 1
            if verbose:
                print(f"  Skipping (already exists): {title}")
            continue

        # Resolve SG playlist link:
        #   1. Name-convention match (calendar title + meeting date → SG playlist)
        #   2. Fallback: ShotGrid URL pasted in the calendar event description
        sg_playlist_link = None
        source = None
        start_time = meeting.get('start_time', '')
        if start_time:
            try:
                meeting_date = _resolve_meeting_date(start_time)
                sg_playlist_link = find_playlist_for_meeting(title, meeting_date, show_mapping)
                if sg_playlist_link:
                    source = 'name-convention'
            except Exception as e:
                if verbose:
                    print(f"  Warning: name-convention lookup failed for '{title}': {e}")

        if not sg_playlist_link:
            sg_playlist_link = extract_sg_playlist_link(meeting.get('description', ''))
            if sg_playlist_link:
                source = 'description'

        if not sg_playlist_link:
            stats['no_sg_link'] += 1
            if verbose:
                print(f"  Skipping (no ShotGrid link): {title}")
            continue

        # Check for video recording - REQUIRED
        if not meeting.get('recording_link'):
            stats['no_recording'] += 1
            if verbose:
                print(f"  Skipping (no video recording): {title}")
            continue

        # Insert into database
        try:
            if insert_meeting(conn, meeting, sg_playlist_link):
                stats['synced'] += 1
                stats['pipeline_commands'].append({
                    'event_id': meeting['event_id'],
                    'title': title,
                    'command': _pipeline_command(meeting, sg_playlist_link, show_mapping),
                })
                if verbose:
                    print(f"  Synced: {title}")
                    print(f"    Recording:   {meeting['recording_filename']}")
                    print(f"    SG Playlist: {sg_playlist_link}  [{source}]")
        except Exception as e:
            stats['errors'] += 1
            print(f"  Error inserting {title}: {e}")

    return stats


# =============================================================================
# Cron helpers
# =============================================================================

def _load_dotenv_values(env_path: str) -> dict:
    """Parse key=value pairs from a .env file without sourcing the shell."""
    values = {}
    if not os.path.exists(env_path):
        return values
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                values[key.strip()] = val.strip()
    return values


def _send_cron_email(subject: str, body: str, recipient: str, sender: str,
                     smtp_host: str = 'localhost', smtp_port: int = None):
    """Send a plain-text email via SMTP for cron notifications."""
    msg = MIMEText(body, 'plain')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    port = smtp_port or smtplib.SMTP_PORT
    with smtplib.SMTP(smtp_host, port) as smtp:
        smtp.sendmail(sender, [recipient], msg.as_string())


def run_cron_mode(conn, calendar_service, drive_service,
                  days: int, recipient: str, env_cfg: dict):
    """
    Sync meetings and auto-launch run_pipeline.sh for each new one.
    Emails the combined output only when at least one meeting was synced.
    Completely silent otherwise (suitable for cron).

    Duplicate-processing safety: each job is stamped 'processing' in the DB
    before its subprocess starts, and 'completed'/'failed' when it exits.
    Combined with the UNIQUE event_id constraint (new meetings are only ever
    inserted once), subsequent cron ticks will always skip in-progress or
    finished jobs.  Use `flock -n` in your crontab to prevent two instances
    from running simultaneously.
    """
    # Capture sync output without printing to stdout
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stats = sync_meetings_to_db(conn, calendar_service, drive_service,
                                    days=days, verbose=True)

    if stats['synced'] == 0:
        return  # Nothing new — stay silent

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_parts = [buf.getvalue()]

    for job in stats['pipeline_commands']:
        event_id = job['event_id']
        cmd = job['command']
        sep = '=' * 72
        output_parts.append(f"\n{sep}\nRunning: {cmd}\n{sep}\n")

        # Claim the job — any subsequent cron tick that somehow sees this
        # meeting will find status='processing' and won't re-insert it
        # (meeting_exists returns True), so no duplicate launch is possible.
        update_meeting_status(conn, event_id, 'processing')

        result = subprocess.run(
            cmd, shell=True, cwd=script_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True
        )
        output_parts.append(result.stdout or '')

        if result.returncode == 0:
            update_meeting_status(conn, event_id, 'completed')
        else:
            update_meeting_status(conn, event_id, 'failed',
                                  f'Pipeline exited with code {result.returncode}')

    full_output = ''.join(output_parts)

    sender = env_cfg.get('EMAIL_SENDER', recipient)
    smtp_host = env_cfg.get('SMTP_HOST', 'localhost')
    smtp_port_str = env_cfg.get('SMTP_PORT')
    smtp_port = int(smtp_port_str) if smtp_port_str else None

    subject = (
        f"[GMeet] {stats['synced']} new meeting(s) processed"
        f" — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    try:
        _send_cron_email(subject, full_output, recipient, sender, smtp_host, smtp_port)
    except Exception as e:
        # Fall back to stderr so the cron daemon captures it
        print(f"[cron] Failed to send email: {e}\n\n{full_output}", file=sys.stderr)


# =============================================================================
# CLI
# =============================================================================

def list_meetings(conn, status: str = None, days: int = None):
    """Print meetings from the database, optionally filtered by status and date range."""
    from datetime import timedelta

    start_date = end_date = None
    if days is not None:
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = (today_start - timedelta(days=days)).isoformat()
        end_date = (today_start + timedelta(days=1)).isoformat()

    meetings, _ = db_get_meetings(conn, status=status,
                                      start_date=start_date, end_date=end_date,
                                      limit=200)

    label = f"{status} " if status else ""
    label += "meetings"
    if not meetings:
        print(f"No {label} found.")
        return

    for m in meetings:
        print(f"{m['status']} | {m['recording_filename']} | {m['sg_playlist_link']}")


def main():
    parser = argparse.ArgumentParser(
        description='Sync Google Meet recordings to database'
    )
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--days', '-d', type=int, default=0,
                        help='Number of past days to include (0=today, 1=today+yesterday, etc.)')
    parser.add_argument('--db', default=DEFAULT_DB_PATH,
                        help=f'Database path (default: {DEFAULT_DB_PATH})')
    parser.add_argument('--list', action='store_true',
                        help='List meetings in the database')
    parser.add_argument('--status', metavar='STATUS',
                        help='Filter --list by status (pending/processing/completed/failed/skipped)')
    parser.add_argument('--update-status', nargs=2, metavar=('EVENT_ID', 'STATUS'),
                        help='Update meeting status (pending/processing/completed/failed/skipped)')
    parser.add_argument('--cron', action='store_true',
                        help='Cron mode: silent unless new meetings are found; '
                             'auto-launches run_pipeline.sh and emails combined output')
    parser.add_argument('--recipient', metavar='EMAIL',
                        help='Email recipient for --cron notifications '
                             '(default: EMAIL_SENDER from .env)')

    args = parser.parse_args()

    # Resolve database path
    db_path = os.path.abspath(args.db)

    # Initialize database
    conn = init_db(db_path)

    if args.verbose:
        print(f"Database: {db_path}")

    # Handle --list
    if args.list:
        list_meetings(conn, status=args.status, days=args.days)
        conn.close()
        return

    # Handle --update-status
    if args.update_status:
        event_id, status = args.update_status
        valid_statuses = ['pending', 'processing', 'completed', 'failed', 'skipped']
        if status not in valid_statuses:
            print(f"Error: Invalid status. Must be one of: {valid_statuses}")
            sys.exit(1)

        if update_meeting_status(conn, event_id, status):
            print(f"Updated {event_id} to {status}")
        else:
            print(f"No meeting found with event_id: {event_id}")
        conn.close()
        return

    # Resolve calendar/drive credentials
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(script_dir, '../client_secret.json')
    token_path = os.path.join(script_dir, '../token.json')

    try:
        calendar_service = get_calendar_service(credentials_path, token_path)
        drive_service = get_drive_service(credentials_path, token_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # --cron: silent sync + auto-launch + email
    if args.cron:
        env_cfg = _load_dotenv_values(os.path.join(script_dir, '../.env'))
        recipient = args.recipient or env_cfg.get('EMAIL_SENDER', '')
        if not recipient:
            print("Error: --cron requires a recipient email. "
                  "Set EMAIL_SENDER in .env or pass --recipient.", file=sys.stderr)
            sys.exit(1)
        run_cron_mode(conn, calendar_service, drive_service,
                      days=args.days, recipient=recipient, env_cfg=env_cfg)
        conn.close()
        return

    # Default: interactive sync
    print(f"Syncing finished meetings (past {args.days} days + today)...")
    stats = sync_meetings_to_db(conn, calendar_service, drive_service,
                                 days=args.days, verbose=args.verbose)

    print(f"\nSync complete:")
    print(f"  Synced:       {stats['synced']}")
    print(f"  Skipped:      {stats['skipped']} (already in DB)")
    print(f"  No SG link:   {stats['no_sg_link']}")
    print(f"  No recording: {stats['no_recording']}")
    print(f"  Errors:       {stats['errors']}")

    if stats['pipeline_commands']:
        print(f"\nRun pipeline for synced meetings:")
        print("=" * 80)
        for job in stats['pipeline_commands']:
            print(job['command'])
        print("=" * 80)

    conn.close()


if __name__ == '__main__':
    main()
