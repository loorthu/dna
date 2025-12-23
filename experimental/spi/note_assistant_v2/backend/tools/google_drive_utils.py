#!/usr/bin/env python3
"""
Google Drive Utilities for File Downloads

This module provides utilities to download files from Google Drive using OAuth2 user authentication.

Features:
- Parse Google Drive URLs and extract file IDs
- Authenticate using OAuth2 user credentials (one-time browser login)
- Download files with progress tracking and retry logic
- Comprehensive error handling with actionable messages

OAuth2 Setup:
1. Enable Google Drive API:
   - Go to https://console.cloud.google.com/apis/library/drive.googleapis.com
   - Select your project (imageworks-ml-experiments)
   - Click "Enable" if not already enabled

2. Configure OAuth Consent Screen (if needed):
   - Go to https://console.cloud.google.com/apis/credentials/consent
   - Add Drive scopes if prompted

3. First Run Authentication:
   - Script will open browser automatically
   - Log in with your Google account (@imageworks.com)
   - Grant permissions to access Drive
   - Token saved to token.json for future use

4. Subsequent Runs:
   - No authentication needed
   - Automatically uses cached token from token.json
   - Auto-refreshes when expired (transparent to user)

Usage Example:
    from google_drive_utils import parse_drive_url, download_drive_file

    # Parse URL to get file ID
    file_id = parse_drive_url("https://drive.google.com/file/d/1a2b3c4d/view")

    # Download file (OAuth2 - will prompt for login on first run)
    if file_id:
        success = download_drive_file(
            file_id,
            "output.mp4",
            "client_secret.json",  # OAuth2 credentials
            verbose=True
        )
"""

import os
import re
import io
import json
import time
import shutil
from typing import Optional, Dict
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError


# Google Drive API configuration
# Include both regular Drive and Shared Drives (Team Drives) access
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.metadata.readonly'
]

# Regular expressions for parsing Google Drive URLs
DRIVE_URL_PATTERNS = [
    r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',  # Standard share URL
    r'https://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',  # Open URL
    r'https://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)',  # Direct download URL
    r'^([a-zA-Z0-9_-]{25,})$'  # Raw file ID (25+ chars, alphanumeric with dash/underscore)
]


def parse_drive_url(input_string: str) -> Optional[str]:
    """
    Parse Google Drive URL or file ID from input string.

    This function detects whether the input is a Google Drive URL/ID or a local file path.
    If it's a Drive URL, it extracts and returns the file ID. If it's a local file path
    that exists, it returns None to indicate local file processing should be used.

    Args:
        input_string: URL, file ID, or local file path

    Returns:
        File ID if Drive URL/ID detected, None if local path or invalid input

    Examples:
        >>> parse_drive_url("https://drive.google.com/file/d/1a2b3c4d/view")
        '1a2b3c4d'

        >>> parse_drive_url("1a2b3c4d5e6f7g8h9i0j1k2l3m")
        '1a2b3c4d5e6f7g8h9i0j1k2l3m'

        >>> parse_drive_url("/path/to/local/file.mp4")
        None
    """
    # First check if it's a local file path that exists
    if os.path.exists(input_string) and os.path.isfile(input_string):
        return None

    # Try to match against Drive URL patterns
    for pattern in DRIVE_URL_PATTERNS:
        match = re.search(pattern, input_string)
        if match:
            return match.group(1)

    # No match found
    return None


def is_drive_url(input_string: str) -> bool:
    """
    Quick check if input string is a Google Drive URL or file ID.

    Args:
        input_string: String to check

    Returns:
        True if appears to be Drive URL/ID, False otherwise
    """
    return parse_drive_url(input_string) is not None


def get_drive_service_oauth(credentials_path: str, token_path: str = 'token.json'):
    """
    Create Google Drive API service using OAuth2 user credentials.

    On first run, opens a browser for user authentication. Subsequent runs
    use the cached token from token.json.

    Args:
        credentials_path: Path to OAuth2 client credentials JSON file
        token_path: Path to store/load OAuth2 token (default: token.json)

    Returns:
        Google Drive API v3 service object

    Raises:
        FileNotFoundError: Credentials file not found
        ValueError: Invalid credentials format
        Exception: Authentication failed
    """
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"OAuth2 credentials not found at: {credentials_path}\n"
            f"Please ensure client_secret.json exists in the parent directory."
        )

    creds = None

    # Load token from file if it exists
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"Warning: Could not load token from {token_path}: {e}")
            creds = None

    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}")
                print("Re-authenticating...")
                creds = None

        if not creds:
            # Run OAuth2 flow
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                raise Exception(f"OAuth2 authentication failed: {e}")

        # Save the credentials for the next run
        try:
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"Warning: Could not save token to {token_path}: {e}")

    # Build and return Drive service
    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        raise Exception(f"Failed to create Drive API service: {e}")


def get_file_metadata(file_id: str, credentials_path: str, token_path: str = 'token.json') -> Optional[Dict]:
    """
    Get file metadata from Google Drive (name, size, mimeType).

    Args:
        file_id: Google Drive file ID
        credentials_path: Path to OAuth2 credentials JSON
        token_path: Path to OAuth2 token file

    Returns:
        Dictionary with file metadata, or None if failed

    Example:
        >>> metadata = get_file_metadata("1a2b3c4d", "client_secret.json")
        >>> print(metadata['name'], metadata['size'])
    """
    try:
        service = get_drive_service_oauth(credentials_path, token_path)
        file_metadata = service.files().get(
            fileId=file_id,
            fields='name,size,mimeType',
            supportsAllDrives=True  # Support Shared Drives (Team Drives)
        ).execute()
        return file_metadata
    except HttpError as e:
        if e.resp.status == 404:
            print(f"Error: File not found on Google Drive (ID: {file_id})")
        elif e.resp.status == 403:
            print(f"Error: Permission denied to access file (ID: {file_id})")
        else:
            print(f"Error getting file metadata: {e}")
        return None
    except Exception as e:
        print(f"Error getting file metadata: {e}")
        return None


def download_drive_file(
    file_id: str,
    output_path: str,
    credentials_path: str,
    verbose: bool = False,
    max_retries: int = 3,
    token_path: str = 'token.json'
) -> bool:
    """
    Download file from Google Drive to local path using OAuth2 authentication.

    Features:
    - Downloads in 1MB chunks with optional progress tracking
    - Validates file access before downloading
    - Checks disk space before download
    - Implements retry logic for network errors
    - Comprehensive error handling with actionable messages
    - First run: Opens browser for authentication
    - Subsequent runs: Uses cached token

    Args:
        file_id: Google Drive file ID
        output_path: Local path to save file
        credentials_path: Path to OAuth2 credentials JSON
        verbose: Print progress information
        max_retries: Maximum retry attempts for network errors (default: 3)
        token_path: Path to OAuth2 token file (default: token.json)

    Returns:
        True if successful, False otherwise

    Raises:
        FileNotFoundError: Credentials file not found
        ValueError: Invalid credentials format
    """
    # Get Drive service with OAuth2
    try:
        service = get_drive_service_oauth(credentials_path, token_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Authentication error: {e}")
        return False
    except Exception as e:
        print(f"Failed to authenticate with Google Drive: {e}")
        return False

    # Get file metadata to validate access and get file info
    try:
        file_metadata = service.files().get(
            fileId=file_id,
            fields='name,size,mimeType',
            supportsAllDrives=True  # Support Shared Drives (Team Drives)
        ).execute()

        file_name = file_metadata.get('name', 'unknown')
        file_size = int(file_metadata.get('size', 0))

        if verbose:
            print(f"File found: {file_name}")
            print(f"Size: {file_size / (1024**2):.2f} MB")

    except HttpError as e:
        if e.resp.status == 404:
            print(f"Error: File not found on Google Drive (ID: {file_id})")
            print("Possible causes:")
            print("  - File ID is incorrect")
            print("  - File has been deleted")
            print("  - File is in trash")
        elif e.resp.status == 403:
            print(f"Error: Permission denied to access file (ID: {file_id})")
            print("\nPossible causes:")
            print("  - File is not shared with you")
            print("  - You don't have permission to view this file")
            print("  - Try re-authenticating with --use-oauth flag")
        else:
            print(f"Error accessing file: {e}")
        return False
    except Exception as e:
        print(f"Error getting file metadata: {e}")
        return False

    # Check available disk space
    try:
        output_dir = os.path.dirname(output_path) or '.'
        stat = shutil.disk_usage(output_dir)
        available_space = stat.free

        # Require 1.2x file size for safety margin
        required_space = int(file_size * 1.2)

        if available_space < required_space:
            print(f"Error: Insufficient disk space")
            print(f"  Required: {required_space / (1024**3):.2f} GB")
            print(f"  Available: {available_space / (1024**3):.2f} GB")
            return False
    except Exception as e:
        if verbose:
            print(f"Warning: Could not check disk space: {e}")

    # Download file with retry logic
    for attempt in range(max_retries):
        try:
            if verbose and attempt > 0:
                print(f"Retry attempt {attempt + 1}/{max_retries}...")

            # Create download request
            request = service.files().get_media(
                fileId=file_id,
                supportsAllDrives=True  # Support Shared Drives (Team Drives)
            )

            # Download to file
            fh = io.FileIO(output_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024)  # 1MB chunks

            done = False
            while not done:
                status, done = downloader.next_chunk()
                if verbose and status:
                    progress = int(status.progress() * 100)
                    # Create progress bar that updates on same line
                    bar_length = 40
                    filled = int(bar_length * status.progress())
                    bar = '█' * filled + '░' * (bar_length - filled)
                    print(f'\rDownloading: |{bar}| {progress}%', end='', flush=True)

            if verbose:
                print()  # New line after progress bar completes

            fh.close()

            if verbose:
                print(f"Download complete: {output_path}")

            return True

        except HttpError as e:
            # Retry on server errors (5xx)
            if e.resp.status in [500, 502, 503, 504]:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    if verbose:
                        print(f"Server error ({e.resp.status}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

            # Don't retry on client errors
            print(f"Download failed: {e}")
            return False

        except Exception as e:
            # Retry on connection errors
            error_str = str(e).lower()
            if attempt < max_retries - 1 and ('connection' in error_str or 'timeout' in error_str):
                wait_time = 2 ** attempt  # Exponential backoff
                if verbose:
                    print(f"Connection error, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            print(f"Download failed: {e}")
            return False

    # All retries exhausted
    print(f"Error: Failed to download file after {max_retries} attempts")
    return False
