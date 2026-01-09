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
from datetime import datetime, timezone

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), 'meetings.db')
VALID_STATUSES = {'pending', 'processing', 'completed', 'failed', 'skipped'}

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
