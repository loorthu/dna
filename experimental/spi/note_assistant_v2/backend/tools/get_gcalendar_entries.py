#!/usr/bin/env python3
"""
List Google Meet Meetings

Simple script to list Google Meet meetings from Google Calendar.

Usage:
    python list_meetings.py              # List meetings for next 7 days
    python list_meetings.py --days 30    # List meetings for next 30 days
    python list_meetings.py --days -7    # List meetings for past 7 days

Prerequisites:
    1. Enable Google Calendar API in Google Cloud Console:
       https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
    2. Delete token.json to re-authenticate with new Calendar scope
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_drive_utils import SCOPES, is_video_file

# Response status display mapping
RESPONSE_STATUS = {
    'accepted': 'Yes',
    'declined': 'No',
    'tentative': 'Maybe',
    'needsAction': 'Pending'
}


def _get_credentials(credentials_path: str, token_path: str):
    """Get OAuth2 credentials, refreshing or prompting for login as needed."""
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"OAuth2 credentials not found at: {credentials_path}\n"
            f"Please ensure client_secret.json exists."
        )

    creds = None

    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"Warning: Could not load token from {token_path}: {e}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def get_calendar_service(credentials_path: str, token_path: str):
    """Create Google Calendar API service using OAuth2."""
    creds = _get_credentials(credentials_path, token_path)
    return build('calendar', 'v3', credentials=creds)


def get_drive_service(credentials_path: str, token_path: str):
    """Create Google Drive API service using OAuth2."""
    creds = _get_credentials(credentials_path, token_path)
    return build('drive', 'v3', credentials=creds)


def extract_meet_link(event: dict) -> str:
    """Extract Google Meet link from calendar event."""
    conference_data = event.get('conferenceData', {})
    for entry in conference_data.get('entryPoints', []):
        if entry.get('entryPointType') == 'video':
            return entry.get('uri', '')

    return event.get('hangoutLink', '')


def extract_drive_links(event: dict) -> list:
    """Extract Google Drive links from event description and attachments."""
    links = []

    # Check description for Drive links
    description = event.get('description', '')
    if description:
        # Match various Drive URL patterns
        patterns = [
            r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
            r'https://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
            r'https://docs\.google\.com/[^/]+/d/([a-zA-Z0-9_-]+)',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, description):
                links.append(match.group(0))

    # Check attachments
    for attachment in event.get('attachments', []):
        file_url = attachment.get('fileUrl', '')
        if 'drive.google.com' in file_url or 'docs.google.com' in file_url:
            links.append(file_url)

    return list(set(links))  # Remove duplicates


def get_meeting_status(event: dict) -> str:
    """Determine if meeting is finished, in progress, or upcoming."""
    now = datetime.now().astimezone()

    start = event.get('start', {})
    end = event.get('end', {})
    start_str = start.get('dateTime', start.get('date', ''))
    end_str = end.get('dateTime', end.get('date', ''))

    if 'T' in start_str:
        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))

        if now > end_dt:
            return 'Finished'
        elif now >= start_dt:
            return 'In Progress'
        else:
            return 'Upcoming'
    else:
        # All-day event
        start_date = datetime.strptime(start_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if now.date() > end_date.date():
            return 'Finished'
        elif now.date() >= start_date.date():
            return 'In Progress'
        else:
            return 'Upcoming'


def format_duration(start_str: str, end_str: str) -> str:
    """Calculate and format meeting duration."""
    if 'T' not in start_str:
        return "All day"

    start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
    end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    minutes = int((end - start).total_seconds() / 60)

    if minutes >= 60:
        hours, mins = divmod(minutes, 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{minutes}m"


def calculate_duration_minutes(start_str: str, end_str: str) -> int:
    """Calculate meeting duration in minutes."""
    if 'T' not in start_str:
        return 0

    start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
    end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    return int((end - start).total_seconds() / 60)


def extract_video_from_attachments(attachments: list) -> tuple:
    """
    Extract video recording from calendar event attachments.
    Returns (file_url, file_id, filename, mime_type) or (None, None, None, None)
    """
    if not attachments:
        return None, None, None, None

    for attachment in attachments:
        mime_type = attachment.get('mimeType', '')
        if mime_type.startswith('video/'):
            return (
                attachment.get('fileUrl'),
                attachment.get('fileId'),
                attachment.get('title'),
                mime_type
            )

    return None, None, None, None


def extract_drive_file_ids(text: str) -> list:
    """Extract Google Drive file IDs from text. Returns list of (url, file_id) tuples."""
    if not text:
        return []

    patterns = [
        r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'https://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
    ]

    results = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            results.append((match.group(0), match.group(1)))

    return results


def get_meetings(calendar_service, drive_service=None, days: int = 0,
                 only_with_meet: bool = True, only_finished: bool = False) -> list:
    """
    Get calendar meetings as structured data.

    Args:
        calendar_service: Google Calendar API service
        drive_service: Google Drive API service (optional, for video detection)
        days: Number of past days to include (0 = today only)
        only_with_meet: Only return events with Google Meet links
        only_finished: Only return finished meetings

    Returns:
        List of meeting dictionaries with all metadata
    """
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today_start - timedelta(days=days)
    time_max = today_start + timedelta(days=1)

    try:
        events = calendar_service.events().list(
            calendarId='primary',
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=250
        ).execute().get('items', [])
    except HttpError as e:
        print(f"Error querying calendar: {e}")
        return []

    meetings = []
    for event in events:
        meet_link = extract_meet_link(event)

        # Filter by meet link if requested
        if only_with_meet and not meet_link:
            continue

        # Get meeting status
        status = get_meeting_status(event)

        # Filter by finished status if requested
        if only_finished and status != 'Finished':
            continue

        # Extract basic metadata
        start = event.get('start', {})
        end = event.get('end', {})
        start_str = start.get('dateTime', start.get('date', ''))
        end_str = end.get('dateTime', end.get('date', ''))
        organizer = event.get('organizer', {})
        attendees = event.get('attendees', [])
        description = event.get('description', '')
        attachments = event.get('attachments', [])

        # Extract video recording from attachments first
        recording_link, recording_file_id, recording_filename, recording_mime_type = \
            extract_video_from_attachments(attachments)

        # Fallback: check description for video links (requires drive_service)
        if not recording_link and drive_service:
            drive_links = extract_drive_file_ids(description)
            for full_url, file_id in drive_links:
                is_video, metadata = is_video_file(file_id, service=drive_service)
                if is_video and metadata:
                    recording_link = full_url
                    recording_file_id = file_id
                    recording_filename = metadata.get('name')
                    recording_mime_type = metadata.get('mimeType')
                    break

        meeting = {
            'event_id': event.get('id'),
            'title': event.get('summary', '(No title)'),
            'description': description,
            'start_time': start_str,
            'end_time': end_str,
            'duration_minutes': calculate_duration_minutes(start_str, end_str),
            'status': status,
            'organizer_email': organizer.get('email'),
            'organizer_name': organizer.get('displayName'),
            'meet_link': meet_link,
            'attendees': [
                {
                    'email': a.get('email'),
                    'name': a.get('displayName'),
                    'response': a.get('responseStatus')
                }
                for a in attendees
            ],
            'recording_link': recording_link,
            'recording_file_id': recording_file_id,
            'recording_filename': recording_filename,
            'recording_mime_type': recording_mime_type,
            'drive_links': extract_drive_links(event),
            'attachments': attachments,
        }

        meetings.append(meeting)

    return meetings


def format_time(dt_str: str) -> str:
    """Format datetime string for display."""
    if 'T' in dt_str:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%a %b %d, %Y %I:%M %p')
    return datetime.strptime(dt_str, '%Y-%m-%d').strftime('%a %b %d, %Y (All day)')


def list_meetings(service, days: int):
    """List calendar events with Google Meet links."""
    # Use local time for date boundaries
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if days >= 0:
        # Include all of today plus future days
        time_min, time_max = today_start, today_start + timedelta(days=days + 1)
    else:
        time_min, time_max = now + timedelta(days=days), now

    print(f"\nMeetings from {time_min.strftime('%Y-%m-%d')} to {time_max.strftime('%Y-%m-%d')}")
    print("=" * 80)

    try:
        events = service.events().list(
            calendarId='primary',
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=250
        ).execute().get('items', [])

        meeting_count = 0
        for event in events:
            meet_link = extract_meet_link(event)
            if not meet_link:
                continue

            meeting_count += 1
            summary = event.get('summary', '(No title)')
            start = event.get('start', {})
            end = event.get('end', {})
            start_str = start.get('dateTime', start.get('date', ''))
            end_str = end.get('dateTime', end.get('date', ''))

            # Get organizer
            organizer = event.get('organizer', {})
            organizer_name = organizer.get('displayName', organizer.get('email', 'Unknown'))

            # Get meeting status
            status = get_meeting_status(event)

            # Get attendees with response status
            attendees = event.get('attendees', [])

            # Get drive links (recordings, docs, etc.)
            drive_links = extract_drive_links(event)

            # Get description
            description = event.get('description', '').strip()

            # Print meeting details
            print(f"\n{summary}")
            print(f"  Status:     {status}")
            print(f"  When:       {format_time(start_str)}")
            print(f"  Duration:   {format_duration(start_str, end_str)}")
            print(f"  Organizer:  {organizer_name}")
            print(f"  Meet:       {meet_link}")
            if description:
                lines = description.split('\n')
                print(f"  Description: {lines[0]}")
                for line in lines[1:]:
                    print(f"              {line}")

            # Print attendees
            if attendees:
                print(f"  Attendees:  ({len(attendees)})")
                for attendee in attendees:
                    name = attendee.get('displayName', attendee.get('email', 'Unknown'))
                    response = RESPONSE_STATUS.get(attendee.get('responseStatus', ''), '?')
                    is_organizer = ' (organizer)' if attendee.get('organizer') else ''
                    is_optional = ' [optional]' if attendee.get('optional') else ''
                    print(f"              - {name}: {response}{is_organizer}{is_optional}")

            # Print drive links (recordings, etc.)
            if drive_links:
                print(f"  Drive Links:")
                for link in drive_links:
                    print(f"              {link}")

            print("-" * 80)

        print(f"\nTotal: {meeting_count} Google Meet meeting(s)")

    except HttpError as e:
        if e.resp.status == 403:
            print("Error: Permission denied.")
            print("Enable Calendar API: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com")
            print("Then delete token.json and re-authenticate.")
        else:
            print(f"API error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='List Google Meet meetings from Calendar')
    parser.add_argument('--days', '-d', type=int, default=7,
                        help='Number of days (positive=future, negative=past). Default: 7')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(script_dir, '../client_secret.json')
    token_path = os.path.join(script_dir, '../token.json')

    service = get_calendar_service(credentials_path, token_path)
    list_meetings(service, args.days)


if __name__ == '__main__':
    main()
