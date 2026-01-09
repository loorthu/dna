#!/usr/bin/env python3
"""
Automated Meeting Processing Launcher

Fetches pending meetings from the API and either:
1. Downloads Google Meet recordings (--download-only mode)
2. Launches process_gmeet_recording.py for each meeting (default mode)

Usage:
    # Download recordings only
    python process_pending_meetings.py --download-only
    python process_pending_meetings.py --download-only --output-dir /path/to/downloads

    # Process all pending meetings
    python process_pending_meetings.py
    python process_pending_meetings.py --verbose
    python process_pending_meetings.py --dry-run
"""

import argparse
import os
import sys
import subprocess
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

# =============================================================================
# Configuration
# =============================================================================

def load_config():
    """Load configuration from environment variables."""
    # Use existing GMEET_* variables from .env
    config = {
        'backend_url': os.getenv('LLM_BACKEND_BASE_URL', 'http://localhost:8000'),
        'model': os.getenv('GMEET_MODEL', 'gemini-2.5-pro'),
        'version_pattern': os.getenv('GMEET_VERSION_PATTERN', r'(\d{6})'),
        'version_column': os.getenv('SG_CSV_VERSION_FIELD', 'jts'),  # ShotGrid version field
        'parallel': os.getenv('GMEET_PARALLEL', 'true').lower() == 'true',
        'prompt_type': os.getenv('GMEET_PROMPT_TYPE', 'short'),
        'reference_threshold': int(os.getenv('GMEET_REFERENCE_THRESHOLD', '6')),
        'audio_model': os.getenv('GMEET_AUDIO_MODEL', 'medium'),
        'frame_interval': float(os.getenv('GMEET_FRAME_INTERVAL', '2.0')),
        'batch_size': int(os.getenv('GMEET_BATCH_SIZE', '120')),
        'keep_intermediate': os.getenv('GMEET_KEEP_INTERMEDIATE', 'false').lower() == 'true',
        'thumbnail_url': os.getenv('GMEET_THUMBNAIL_URL'),  # Optional
        'email_subject': os.getenv('GMEET_EMAIL_SUBJECT', 'Dailies Review Data'),
        'cache_dir': os.getenv('GMEET_CACHE_DIR', './media'),
        'duration': os.getenv('GMEET_DURATION'),  # Optional duration limit
    }
    return config


# =============================================================================
# API Client
# =============================================================================

def get_pending_meetings(backend_url: str) -> list:
    """Fetch pending meetings from API."""
    url = f"{backend_url}/api/meetings"
    params = {'status': 'pending'}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data['meetings']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching pending meetings: {e}")
        sys.exit(1)


def update_meeting_status(backend_url: str, event_id: str, status: str, error_message: str = None):
    """Update meeting status via API."""
    url = f"{backend_url}/api/meetings/{event_id}/status"
    payload = {'status': status}
    if error_message:
        payload['error_message'] = error_message

    try:
        response = requests.put(url, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error updating meeting status: {e}")
        return False


# =============================================================================
# Download Handler
# =============================================================================

def extract_meet_id(meet_link: str) -> str:
    """Extract Google Meet ID from meet link.

    Examples:
        https://meet.google.com/abc-defg-hij -> abc-defg-hij
        https://meet.google.com/lookup/abc123 -> lookup_abc123
    """
    if not meet_link:
        return None

    # Extract the last part of the URL path
    parts = meet_link.rstrip('/').split('/')
    if len(parts) >= 2:
        meet_id = '-'.join(parts[-2:]) if 'lookup' in parts[-2] else parts[-1]
        # Sanitize for directory name
        return meet_id.replace('/', '_')

    return None


def get_extension_from_mime_type(mime_type: str) -> str:
    """Get file extension from MIME type."""
    mime_to_ext = {
        'video/mp4': '.mp4',
        'video/webm': '.webm',
        'video/quicktime': '.mov',
        'video/x-msvideo': '.avi',
        'video/mpeg': '.mpeg',
        'video/3gpp': '.3gp',
        'video/x-matroska': '.mkv',
    }
    return mime_to_ext.get(mime_type, '.mp4')


def ensure_filename_extension(filename: str, mime_type: str = None) -> str:
    """Ensure filename has proper extension based on MIME type."""
    if not filename:
        return 'recording.mp4'

    # Check if filename already has an extension
    name, ext = os.path.splitext(filename)
    if ext:
        return filename

    # No extension - add one based on MIME type
    if mime_type:
        ext = get_extension_from_mime_type(mime_type)
    else:
        ext = '.mp4'

    return filename + ext


def download_meeting_recording(meeting: dict, output_dir: str,
                                script_dir: str, verbose: bool = False) -> bool:
    """Download Google Drive recording for a meeting."""
    # Import here to avoid circular dependency issues
    sys.path.insert(0, script_dir)
    from google_drive_utils import download_drive_file, parse_drive_url

    # Extract file ID from recording link
    file_id = meeting.get('recording_file_id')
    if not file_id:
        # Fallback: parse from recording_link
        file_id = parse_drive_url(meeting.get('recording_link', ''))

    if not file_id:
        print(f"  ✗ No recording file ID found")
        return False

    # Extract Google Meet ID for directory name
    meet_id = extract_meet_id(meeting.get('meet_link'))
    if not meet_id:
        # Fallback to event_id if no meet_link
        meet_id = meeting['event_id']

    # Get filename and ensure it has proper extension
    filename = meeting.get('recording_filename', meet_id)
    mime_type = meeting.get('recording_mime_type')
    filename = ensure_filename_extension(filename, mime_type)

    # Create output path: {output_dir}/{meet_id}/{recording_filename}
    output_path = os.path.join(output_dir, meet_id, filename)

    if verbose:
        print(f"  Output file: {filename}")
        print(f"  Full path: {output_path}")

    # Create directory if needed
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Use default credential paths relative to script directory
    credentials_path = os.path.join(script_dir, '../client_secret.json')
    token_path = os.path.join(script_dir, '../token.json')

    # Download file
    try:
        success = download_drive_file(
            file_id,
            output_path,
            credentials_path,
            token_path=token_path,
            verbose=verbose
        )
        if verbose:
            print(f"  Download result: {'success' if success else 'failed'}")
        # Ensure we return explicit boolean
        return bool(success)
    except Exception as e:
        print(f"  ✗ Download error: {e}")
        return False


# =============================================================================
# Process Launcher
# =============================================================================

def build_process_command(meeting: dict, config: dict, script_dir: str) -> list:
    """Build command-line arguments for process_gmeet_recording.py."""
    process_script = os.path.join(script_dir, 'process_gmeet_recording.py')

    cmd = [
        sys.executable,  # Python interpreter
        process_script,
        meeting['recording_link'],      # video_input (Google Drive URL)
        meeting['sg_playlist_link'],    # sg_playlist_url (not CSV anymore)
        '--version-pattern', config['version_pattern'],
        '--version-column', config['version_column'],
        '--model', config['model'],
        '--prompt-type', config['prompt_type'],
        '--reference-threshold', str(config['reference_threshold']),
        '--audio-model', config['audio_model'],
        '--frame-interval', str(config['frame_interval']),
        '--batch-size', str(config['batch_size']),
    ]

    # Add optional parameters
    if config.get('thumbnail_url'):
        cmd.extend(['--thumbnail-url', config['thumbnail_url']])

    if config.get('email_subject'):
        cmd.extend(['--email-subject', config['email_subject']])

    if config.get('cache_dir'):
        # Cache dir is handled by process_gmeet_recording.py via .env
        pass

    if config.get('duration'):
        cmd.extend(['--duration', str(config['duration'])])

    # Add boolean flags
    if config['parallel']:
        cmd.append('--parallel')

    if config['keep_intermediate']:
        cmd.append('--keep-intermediate')

    return cmd


def launch_processing_job(meeting: dict, config: dict, script_dir: str, verbose: bool = False) -> bool:
    """Launch process_gmeet_recording.py in background for a meeting."""
    cmd = build_process_command(meeting, config, script_dir)

    if verbose:
        print(f"  Command: {' '.join(cmd)}")

    try:
        # Launch in background (detached subprocess)
        # stdout/stderr redirected to DEVNULL to avoid blocking
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # Detach from parent process
        )
        return True
    except Exception as e:
        print(f"  Error launching process: {e}")
        return False


# =============================================================================
# Main Logic
# =============================================================================

def process_pending_meetings(config: dict, verbose: bool = False, dry_run: bool = False,
                             download_only: bool = False, output_dir: str = './downloads'):
    """Main processing loop."""
    backend_url = config['backend_url']
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Fetch pending meetings
    print("Fetching pending meetings from API...")
    meetings = get_pending_meetings(backend_url)

    if not meetings:
        print("No pending meetings found.")
        return

    print(f"Found {len(meetings)} pending meeting(s)\n")

    launched = 0
    downloaded = 0
    failed = 0

    for meeting in meetings:
        title = meeting['title']
        event_id = meeting['event_id']
        recording = meeting['recording_filename']
        sg_link = meeting['sg_playlist_link']
        meet_link = meeting.get('meet_link', '')

        # Extract Google Meet ID for display
        meet_id = extract_meet_id(meet_link)
        display_id = meet_id if meet_id else event_id

        print(f"Processing: {title}")
        print(f"  Meet ID:      {display_id}")
        print(f"  Recording:    {recording}")
        print(f"  SG Playlist:  {sg_link}")

        if dry_run:
            if download_only:
                print(f"  [DRY RUN] Would download to: {output_dir}/{display_id}/")
                print(f"  [DRY RUN] Would update status to: downloaded\n")
            else:
                cmd = build_process_command(meeting, config, script_dir)
                print(f"  [DRY RUN] Would launch: {' '.join(cmd)}")
                print(f"  [DRY RUN] Would update status to: processing\n")
            continue

        if download_only:
            # Download mode
            success = download_meeting_recording(meeting, output_dir, script_dir, verbose)

            if success is True:
                # Update status to "downloaded"
                if update_meeting_status(backend_url, event_id, 'downloaded'):
                    print(f"  ✓ Downloaded and marked as downloaded\n")
                    downloaded += 1
                else:
                    print(f"  ✗ Downloaded but failed to update status to 'downloaded'\n")
                    failed += 1
            else:
                # Download failed - update status to "failed"
                if verbose:
                    print(f"  Download returned failure, updating status to 'failed'")
                if update_meeting_status(backend_url, event_id, 'failed',
                                        error_message='Download failed'):
                    print(f"  ✗ Download failed, marked as failed\n")
                else:
                    print(f"  ✗ Download failed and status update also failed\n")
                failed += 1
        else:
            # Processing mode (existing functionality)
            success = launch_processing_job(meeting, config, script_dir, verbose)

            if success:
                # Update status to "processing"
                if update_meeting_status(backend_url, event_id, 'processing'):
                    print(f"  ✓ Launched and marked as processing\n")
                    launched += 1
                else:
                    print(f"  ✗ Launched but failed to update status\n")
                    failed += 1
            else:
                print(f"  ✗ Failed to launch processing job\n")
                failed += 1

    # Summary
    print("=" * 80)
    print(f"Summary:")
    if download_only:
        print(f"  Downloaded: {downloaded}")
        print(f"  Failed:     {failed}")
        print(f"  Total:      {len(meetings)}")
    else:
        print(f"  Launched:   {launched}")
        print(f"  Failed:     {failed}")
        print(f"  Total:      {len(meetings)}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Launch background processing jobs for pending meetings'
    )
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output (show commands)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without launching jobs')

    # Download-only mode arguments
    parser.add_argument('--download-only', action='store_true',
                        help='Download recordings only (skip processing)')
    parser.add_argument('--output-dir', default='./downloads',
                        help='Output directory for downloads (default: ./downloads)')

    args = parser.parse_args()

    # Load configuration
    config = load_config()

    if args.verbose:
        print("Configuration:")
        for key, value in config.items():
            print(f"  {key}: {value}")
        print()

    # Process pending meetings
    process_pending_meetings(
        config,
        verbose=args.verbose,
        dry_run=args.dry_run,
        download_only=args.download_only,
        output_dir=args.output_dir
    )


if __name__ == '__main__':
    main()
