"""
Meeting Service API

Provides FastAPI endpoints for accessing and managing meetings in meetings.db.
Also exports database functions for use by sync_meetings_to_db.py.

API Endpoints:
    GET  /meetings - List meetings with filtering and pagination
    GET  /meetings/{event_id} - Get specific meeting details
    PUT  /meetings/{event_id}/status - Update meeting processing status
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timezone

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), 'meetings.db')
VALID_STATUSES = {'pending', 'processing', 'completed', 'failed', 'skipped', 'downloaded'}

# =============================================================================
# Pydantic Models
# =============================================================================

class UpdateStatusRequest(BaseModel):
    """Request model for updating meeting status."""
    status: str
    error_message: Optional[str] = None


class MeetingsListResponse(BaseModel):
    """Response model for listing meetings."""
    meetings: list[dict]
    total: int
    limit: int
    offset: int


# =============================================================================
# Database Functions
# =============================================================================

def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
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


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Get database connection with Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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


def get_meetings(conn: sqlite3.Connection, status: str = None, start_date: str = None,
                 end_date: str = None, limit: int = 50, offset: int = 0) -> tuple:
    """
    Query meetings with filters.

    Returns: (meetings_list, total_count)
    """
    # Build WHERE clauses
    where_clauses = []
    params = []

    if status:
        where_clauses.append('status = ?')
        params.append(status)

    if start_date:
        where_clauses.append('start_time >= ?')
        params.append(start_date)

    if end_date:
        where_clauses.append('start_time <= ?')
        params.append(end_date)

    where_sql = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''

    # Get total count
    count_query = f'SELECT COUNT(*) FROM meetings {where_sql}'
    cursor = conn.execute(count_query, params)
    total = cursor.fetchone()[0]

    # Get paginated results
    query = f'''
        SELECT * FROM meetings
        {where_sql}
        ORDER BY start_time DESC
        LIMIT ? OFFSET ?
    '''
    params.extend([limit, offset])
    cursor = conn.execute(query, params)
    meetings = [dict(row) for row in cursor.fetchall()]

    return meetings, total


def get_meeting_by_event_id(conn: sqlite3.Connection, event_id: str) -> Optional[dict]:
    """Get single meeting by event_id."""
    cursor = conn.execute('SELECT * FROM meetings WHERE event_id = ?', (event_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


# =============================================================================
# FastAPI Router
# =============================================================================

router = APIRouter()


@router.get("/meetings")
async def list_meetings(
    status: str = Query(None, description="Filter by status (pending/processing/completed/failed/skipped)"),
    start_date: str = Query(None, description="Start date filter (ISO format)"),
    end_date: str = Query(None, description="End date filter (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    List meetings with filtering and pagination.

    Returns meetings in reverse chronological order (newest first).
    """
    # Validate status if provided
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    try:
        conn = get_connection()
        meetings, total = get_meetings(conn, status, start_date, end_date, limit, offset)
        conn.close()

        return {
            "meetings": meetings,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/meetings/{event_id}")
async def get_meeting_details(event_id: str):
    """
    Get full details of a specific meeting.

    Returns 404 if meeting not found.
    """
    try:
        conn = get_connection()
        meeting = get_meeting_by_event_id(conn, event_id)
        conn.close()

        if not meeting:
            raise HTTPException(status_code=404, detail=f"Meeting not found: {event_id}")

        # Parse attendees JSON if present
        if meeting.get('attendees'):
            try:
                meeting['attendees'] = json.loads(meeting['attendees'])
            except json.JSONDecodeError:
                meeting['attendees'] = []

        return meeting

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.put("/meetings/{event_id}/status")
async def update_status(event_id: str, request: UpdateStatusRequest):
    """
    Update meeting processing status.

    Valid statuses: pending, processing, completed, failed, skipped
    """
    # Validate status
    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    try:
        conn = get_connection()

        # Check if meeting exists
        if not meeting_exists(conn, event_id):
            conn.close()
            raise HTTPException(status_code=404, detail=f"Meeting not found: {event_id}")

        # Update status
        success = update_meeting_status(conn, event_id, request.status, request.error_message)
        conn.close()

        return {
            "success": success,
            "event_id": event_id,
            "status": request.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# =============================================================================
# Command Line Interface
# =============================================================================

def cmd_list(args):
    """List meetings with optional filtering."""
    conn = get_connection(args.db)

    meetings, total = get_meetings(
        conn,
        status=args.status,
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        offset=args.offset
    )

    if not meetings:
        print("No meetings found.")
        conn.close()
        return

    print(f"\nFound {total} meeting(s) (showing {len(meetings)})\n")
    print("=" * 120)

    for m in meetings:
        # Parse attendees JSON
        attendees = []
        if m.get('attendees'):
            try:
                attendees = json.loads(m['attendees'])
            except json.JSONDecodeError:
                pass

        print(f"\n{m['title']}")
        print(f"  Event ID:     {m['event_id']}")
        print(f"  Start:        {m['start_time']}")
        print(f"  Duration:     {m.get('duration_minutes', 0)} minutes")
        print(f"  Status:       {m['status']}")
        if m.get('error_message'):
            print(f"  Error:        {m['error_message']}")
        print(f"  Recording:    {m.get('recording_filename', 'N/A')}")
        print(f"  SG Playlist:  {m.get('sg_playlist_link', 'N/A')}")
        print(f"  Attendees:    {len(attendees)}")
        print(f"  Created:      {m.get('created_at', 'N/A')}")
        if m.get('processed_at'):
            print(f"  Processed:    {m['processed_at']}")

    print("=" * 120)
    print(f"\nTotal: {total} meeting(s)")

    conn.close()


def cmd_show(args):
    """Show details for a specific meeting."""
    conn = get_connection(args.db)
    meeting = get_meeting_by_event_id(conn, args.event_id)

    if not meeting:
        print(f"Meeting not found: {args.event_id}")
        conn.close()
        sys.exit(1)

    # Parse attendees JSON
    attendees = []
    if meeting.get('attendees'):
        try:
            attendees = json.loads(meeting['attendees'])
        except json.JSONDecodeError:
            pass

    print("\n" + "=" * 120)
    print(f"Meeting: {meeting['title']}")
    print("=" * 120)
    print(f"Event ID:          {meeting['event_id']}")
    print(f"Status:            {meeting['status']}")
    print(f"Start Time:        {meeting['start_time']}")
    print(f"End Time:          {meeting['end_time']}")
    print(f"Duration:          {meeting.get('duration_minutes', 0)} minutes")
    print(f"Organizer:         {meeting.get('organizer_name', 'N/A')} ({meeting.get('organizer_email', 'N/A')})")
    print(f"Meet Link:         {meeting.get('meet_link', 'N/A')}")
    print(f"\nRecording:")
    print(f"  Filename:        {meeting.get('recording_filename', 'N/A')}")
    print(f"  File ID:         {meeting.get('recording_file_id', 'N/A')}")
    print(f"  MIME Type:       {meeting.get('recording_mime_type', 'N/A')}")
    print(f"  Link:            {meeting.get('recording_link', 'N/A')}")
    print(f"\nShotGrid:")
    print(f"  Playlist Link:   {meeting.get('sg_playlist_link', 'N/A')}")

    if attendees:
        print(f"\nAttendees ({len(attendees)}):")
        for a in attendees:
            response = a.get('response', 'unknown')
            print(f"  - {a.get('name', 'N/A')} ({a.get('email', 'N/A')}) - {response}")

    if meeting.get('description'):
        print(f"\nDescription:")
        print(f"  {meeting['description'][:200]}{'...' if len(meeting['description']) > 200 else ''}")

    print(f"\nTimestamps:")
    print(f"  Created:         {meeting.get('created_at', 'N/A')}")
    print(f"  Updated:         {meeting.get('updated_at', 'N/A')}")
    print(f"  Processed:       {meeting.get('processed_at', 'N/A')}")

    if meeting.get('error_message'):
        print(f"\nError Message:")
        print(f"  {meeting['error_message']}")

    print("=" * 120 + "\n")

    conn.close()


def cmd_stats(args):
    """Show database statistics."""
    conn = get_connection(args.db)

    # Count by status
    print("\nMeeting Statistics")
    print("=" * 60)

    total = 0
    for status in VALID_STATUSES:
        cursor = conn.execute('SELECT COUNT(*) FROM meetings WHERE status = ?', (status,))
        count = cursor.fetchone()[0]
        print(f"  {status:12s}: {count:5d}")
        total += count

    print("-" * 60)
    print(f"  {'Total':12s}: {total:5d}")

    # Recent activity
    print("\n" + "=" * 60)
    print("Recent Activity (last 10)")
    print("=" * 60)

    cursor = conn.execute('''
        SELECT title, status, start_time, updated_at
        FROM meetings
        ORDER BY updated_at DESC
        LIMIT 10
    ''')

    for row in cursor.fetchall():
        title = row[0][:40] + "..." if len(row[0]) > 40 else row[0]
        print(f"  {row[1]:12s} | {row[2][:10]} | {title}")

    print("=" * 60 + "\n")

    conn.close()


def cmd_update_status(args):
    """Update meeting status."""
    if args.status not in VALID_STATUSES:
        print(f"Error: Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
        sys.exit(1)

    conn = get_connection(args.db)

    if not meeting_exists(conn, args.event_id):
        print(f"Meeting not found: {args.event_id}")
        conn.close()
        sys.exit(1)

    success = update_meeting_status(conn, args.event_id, args.status, args.error_message)

    if success:
        print(f"✓ Updated {args.event_id} to status: {args.status}")
    else:
        print(f"✗ Failed to update {args.event_id}")

    conn.close()


def main():
    """Command-line interface for querying meetings database."""
    parser = argparse.ArgumentParser(
        description='Query and manage meetings database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # List all pending meetings
  python meeting_service.py list --status pending

  # Show details for a specific meeting
  python meeting_service.py show EVENT_ID

  # Show database statistics
  python meeting_service.py stats

  # Update meeting status
  python meeting_service.py update-status EVENT_ID completed
        '''
    )

    parser.add_argument('--db', default=DEFAULT_DB_PATH,
                        help=f'Database path (default: {DEFAULT_DB_PATH})')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    subparsers.required = True

    # List command
    list_parser = subparsers.add_parser('list', help='List meetings')
    list_parser.add_argument('--status', choices=list(VALID_STATUSES),
                             help='Filter by status')
    list_parser.add_argument('--start-date', help='Filter by start date (ISO format)')
    list_parser.add_argument('--end-date', help='Filter by end date (ISO format)')
    list_parser.add_argument('--limit', type=int, default=50,
                             help='Maximum number of results (default: 50)')
    list_parser.add_argument('--offset', type=int, default=0,
                             help='Pagination offset (default: 0)')
    list_parser.set_defaults(func=cmd_list)

    # Show command
    show_parser = subparsers.add_parser('show', help='Show meeting details')
    show_parser.add_argument('event_id', help='Event ID of the meeting')
    show_parser.set_defaults(func=cmd_show)

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show database statistics')
    stats_parser.set_defaults(func=cmd_stats)

    # Update status command
    update_parser = subparsers.add_parser('update-status', help='Update meeting status')
    update_parser.add_argument('event_id', help='Event ID of the meeting')
    update_parser.add_argument('status', choices=list(VALID_STATUSES),
                                help='New status')
    update_parser.add_argument('--error-message', help='Optional error message')
    update_parser.set_defaults(func=cmd_update_status)

    args = parser.parse_args()

    # Initialize database if it doesn't exist
    if not os.path.exists(args.db):
        print(f"Database not found. Initializing: {args.db}")
        init_db(args.db)

    # Execute the command
    args.func(args)


if __name__ == '__main__':
    main()
