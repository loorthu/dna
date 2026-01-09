#!/usr/bin/env python3
"""
Sync Google Meet Recordings to Database

Discovers finished Google Meet meetings with video recordings and ShotGrid
playlist links, then stores them in a SQLite database for pipeline processing.

Usage:
    python sync_meetings_to_db.py                    # Sync today's meetings
    python sync_meetings_to_db.py --days 1           # Include yesterday
    python sync_meetings_to_db.py --verbose          # Verbose output
    python sync_meetings_to_db.py --list-pending     # List pending meetings
    python sync_meetings_to_db.py --update-status EVENT_ID STATUS
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

# Import calendar functions from get_gcalendar_entries.py
from get_gcalendar_entries import (
    get_calendar_service,
    get_drive_service,
    get_meetings,
)

# Default database path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'meetings.db')


# =============================================================================
# Database Functions
# =============================================================================

def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize database and create tables if not exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute('''
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_minutes INTEGER,
            organizer_email TEXT,
            organizer_name TEXT,
            meet_link TEXT,
            attendees TEXT,
            recording_link TEXT,
            recording_file_id TEXT,
            recording_filename TEXT,
            recording_mime_type TEXT,
            sg_playlist_link TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )
    ''')

    conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON meetings(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_start_time ON meetings(start_time)')
    conn.commit()

    return conn


def meeting_exists(conn: sqlite3.Connection, event_id: str) -> bool:
    """Check if meeting already exists in database."""
    cursor = conn.execute('SELECT 1 FROM meetings WHERE event_id = ?', (event_id,))
    return cursor.fetchone() is not None


def insert_meeting(conn: sqlite3.Connection, meeting: dict, sg_playlist_link: str) -> bool:
    """Insert a new meeting into the database. Returns True if inserted."""
    if meeting_exists(conn, meeting['event_id']):
        return False

    conn.execute('''
        INSERT INTO meetings (
            event_id, title, description, start_time, end_time, duration_minutes,
            organizer_email, organizer_name, meet_link, attendees,
            recording_link, recording_file_id, recording_filename, recording_mime_type,
            sg_playlist_link, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        meeting['event_id'],
        meeting['title'],
        meeting.get('description'),
        meeting['start_time'],
        meeting['end_time'],
        meeting.get('duration_minutes'),
        meeting.get('organizer_email'),
        meeting.get('organizer_name'),
        meeting.get('meet_link'),
        json.dumps(meeting.get('attendees', [])),
        meeting.get('recording_link'),
        meeting.get('recording_file_id'),
        meeting.get('recording_filename'),
        meeting.get('recording_mime_type'),
        sg_playlist_link,
        'pending'
    ))
    conn.commit()
    return True


def get_pending_meetings(conn: sqlite3.Connection) -> list:
    """Get all meetings with pending status."""
    cursor = conn.execute('''
        SELECT * FROM meetings WHERE status = 'pending' ORDER BY start_time
    ''')
    return [dict(row) for row in cursor.fetchall()]


def update_meeting_status(conn: sqlite3.Connection, event_id: str, status: str,
                          error_message: str = None) -> bool:
    """Update meeting processing status."""
    now = datetime.now(timezone.utc).isoformat()

    if status == 'completed':
        conn.execute('''
            UPDATE meetings
            SET status = ?, error_message = ?, updated_at = ?, processed_at = ?
            WHERE event_id = ?
        ''', (status, error_message, now, now, event_id))
    else:
        conn.execute('''
            UPDATE meetings
            SET status = ?, error_message = ?, updated_at = ?
            WHERE event_id = ?
        ''', (status, error_message, now, event_id))

    conn.commit()
    return conn.total_changes > 0


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

def sync_meetings_to_db(conn: sqlite3.Connection, calendar_service, drive_service,
                        days: int = 0, verbose: bool = False) -> dict:
    """
    Sync finished meetings with recordings and SG links to database.
    Returns dict with counts: {synced, skipped, no_sg_link, no_recording, errors}
    """
    stats = {'synced': 0, 'skipped': 0, 'no_sg_link': 0, 'no_recording': 0, 'errors': 0}

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

    for meeting in meetings:
        title = meeting['title']

        # Skip if already in database
        if meeting_exists(conn, meeting['event_id']):
            stats['skipped'] += 1
            if verbose:
                print(f"  Skipping (already exists): {title}")
            continue

        # Extract ShotGrid playlist link - REQUIRED
        sg_playlist_link = extract_sg_playlist_link(meeting.get('description', ''))
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
                if verbose:
                    print(f"  Synced: {title}")
                    print(f"    Recording: {meeting['recording_filename']}")
                    print(f"    SG Playlist: {sg_playlist_link}")
        except Exception as e:
            stats['errors'] += 1
            print(f"  Error inserting {title}: {e}")

    return stats


# =============================================================================
# CLI
# =============================================================================

def list_pending(conn: sqlite3.Connection):
    """Print pending meetings."""
    meetings = get_pending_meetings(conn)

    if not meetings:
        print("No pending meetings.")
        return

    print(f"\nPending meetings ({len(meetings)}):")
    print("=" * 80)

    for m in meetings:
        print(f"\n{m['title']}")
        print(f"  Event ID:    {m['event_id']}")
        print(f"  Start:       {m['start_time']}")
        print(f"  Recording:   {m['recording_filename']}")
        print(f"  SG Playlist: {m['sg_playlist_link']}")
        print(f"  Status:      {m['status']}")

    print("=" * 80)


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
    parser.add_argument('--list-pending', action='store_true',
                        help='List pending meetings')
    parser.add_argument('--update-status', nargs=2, metavar=('EVENT_ID', 'STATUS'),
                        help='Update meeting status (pending/processing/completed/failed/skipped)')

    args = parser.parse_args()

    # Resolve database path
    db_path = os.path.abspath(args.db)

    # Initialize database
    conn = init_db(db_path)

    if args.verbose:
        print(f"Database: {db_path}")

    # Handle --list-pending
    if args.list_pending:
        list_pending(conn)
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

    # Default: sync meetings
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(script_dir, '../client_secret.json')
    token_path = os.path.join(script_dir, '../token.json')

    try:
        calendar_service = get_calendar_service(credentials_path, token_path)
        drive_service = get_drive_service(credentials_path, token_path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Syncing finished meetings (past {args.days} days + today)...")
    stats = sync_meetings_to_db(conn, calendar_service, drive_service,
                                 days=args.days, verbose=args.verbose)

    print(f"\nSync complete:")
    print(f"  Synced:       {stats['synced']}")
    print(f"  Skipped:      {stats['skipped']} (already in DB)")
    print(f"  No SG link:   {stats['no_sg_link']}")
    print(f"  No recording: {stats['no_recording']}")
    print(f"  Errors:       {stats['errors']}")

    conn.close()


if __name__ == '__main__':
    main()
