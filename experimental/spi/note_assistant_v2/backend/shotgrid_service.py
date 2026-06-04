import os
import hashlib
import re
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from shotgun_api3 import Shotgun
import argparse
import yaml
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

load_dotenv()

# --- Configuration ---
SG_URL = os.environ.get("SG_URL")
SG_SCRIPT_NAME = os.environ.get("SG_SCRIPT_NAME")
SG_API_KEY = os.environ.get("SG_API_KEY")
# Configurable field names for version and shot
SG_PLAYLIST_VERSION_FIELD = os.environ.get("SG_PLAYLIST_VERSION_FIELD", "version")
SG_PLAYLIST_SHOT_FIELD = os.environ.get("SG_PLAYLIST_SHOT_FIELD", "shot")
SG_PLAYLIST_NOTES_FIELD = os.environ.get("SG_PLAYLIST_NOTES_FIELD", "")
SG_PLAYLIST_TYPE_FILTER = os.environ.get("SG_PLAYLIST_TYPE_FILTER", "")
SG_PLAYLIST_TYPE_LIST = [t.strip() for t in SG_PLAYLIST_TYPE_FILTER.split(",") if t.strip()]
# Demo mode configuration
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

def anonymize_text(text, prefix="DEMO"):
    """
    Anonymize text by creating a consistent hash-based replacement.
    This ensures the same input always produces the same anonymized output.
    """
    if not text or not DEMO_MODE:
        return text
    
    # Create a hash of the original text
    hash_object = hashlib.md5(text.encode())
    hash_hex = hash_object.hexdigest()[:8]  # Use first 8 characters
    
    # Extract any numeric parts to preserve structure
    numbers = re.findall(r'\d+', text)
    number_suffix = f"_{numbers[0]}" if numbers else ""
    
    return f"{prefix}_{hash_hex.upper()}{number_suffix}"

def anonymize_project_data(projects):
    """Anonymize project data for demo mode."""
    if not DEMO_MODE:
        return projects
    
    anonymized = []
    for project in projects:
        project_copy = project.copy()
        if 'code' in project_copy:
            project_copy['code'] = anonymize_text(project_copy['code'], "PROJ")
        if 'name' in project_copy:
            project_copy['name'] = anonymize_text(project_copy['name'], "PROJECT")
        anonymized.append(project_copy)
    return anonymized

def anonymize_playlist_data(playlists):
    """Anonymize playlist data for demo mode."""
    if not DEMO_MODE:
        return playlists
    
    anonymized = []
    for playlist in playlists:
        playlist_copy = playlist.copy()
        if 'code' in playlist_copy:
            playlist_copy['code'] = anonymize_text(playlist_copy['code'], "PLAYLIST")
        anonymized.append(playlist_copy)
    return anonymized

def anonymize_shot_name(shot_text):
    """Anonymize shot name to be max 5 characters."""
    if not shot_text or not DEMO_MODE:
        return shot_text
    
    # Create a hash and take first 5 characters as uppercase
    hash_object = hashlib.md5(shot_text.encode())
    hash_hex = hash_object.hexdigest()[:5].upper()
    return hash_hex

def anonymize_version_name(version_text):
    """Anonymize version name to be a 5-digit integer."""
    if not version_text or not DEMO_MODE:
        return version_text
    
    # Create a hash and convert to a 5-digit number
    hash_object = hashlib.md5(version_text.encode())
    hash_int = int(hash_object.hexdigest()[:8], 16)  # Convert hex to int
    # Ensure it's a 5-digit number (10000-99999)
    version_num = (hash_int % 90000) + 10000
    return str(version_num)

def anonymize_shot_names(shot_names):
    """Anonymize shot/version names for demo mode."""
    if not DEMO_MODE:
        return shot_names
    
    anonymized = []
    for shot_name in shot_names:
        # Split shot/version format
        if '/' in shot_name:
            parts = shot_name.split('/', 1)
            shot_part = anonymize_shot_name(parts[0])
            version_part = anonymize_version_name(parts[1])
            anonymized.append(f"{shot_part}/{version_part}")
        else:
            anonymized.append(anonymize_shot_name(shot_name))
    return anonymized

def get_project_by_code(project_code):
    """Fetch a single project from ShotGrid by code."""
    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    filters = [["code", "is", project_code]]
    fields = ["id", "code", "name", "sg_status", "created_at"]
    project = sg.find_one("Project", filters, fields)
    
    if project and DEMO_MODE:
        project_copy = project.copy()
        if 'code' in project_copy:
            project_copy['code'] = anonymize_text(project_copy['code'], "PROJ")
        if 'name' in project_copy:
            project_copy['name'] = anonymize_text(project_copy['name'], "PROJECT")
        return project_copy
    
    return project

def get_latest_playlists_for_project(project_id, limit=20):
    """Fetch the latest playlists for a given project id."""
    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    filters = [["project", "is", {"type": "Project", "id": project_id}]]
    fields = ["id", "code", "created_at", "updated_at"]
    playlists = sg.find("Playlist", filters, fields, order=[{"field_name": "created_at", "direction": "desc"}], limit=limit)
    return anonymize_playlist_data(playlists)

def get_active_projects():
    """Fetch all active projects from ShotGrid (sg_status == 'Active' and sg_type in configured list), sorted by code."""
    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    filters = [
        ["sg_status", "is", "Active"],
        {"filter_operator": "any", "filters": [
            ["sg_type", "is", t] for t in SG_PLAYLIST_TYPE_LIST
        ]}
    ]
    fields = ["id", "code", "created_at", "sg_type"]
    projects = sg.find("Project", filters, fields, order=[{"field_name": "code", "direction": "asc"}])
    return anonymize_project_data(projects)

def get_playlist_shot_names(playlist_id):
    """
    Fetch the list of shot/version names from a playlist, using configurable field names.

    Returns:
        dict: {
            "shot_names": list of str,  # List of shot/version names
            "playlist_name": str or None  # Playlist name (code field) if found
        }
    """
    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    fields = ["versions", "code"]  # Include 'code' field to get playlist name
    playlist = sg.find_one("Playlist", [["id", "is", playlist_id]], fields)
    if not playlist:
        return {"shot_names": [], "playlist_name": None}

    playlist_name = playlist.get("code")

    if not playlist.get("versions"):
        return {"shot_names": [], "playlist_name": playlist_name}

    version_ids = [v["id"] for v in playlist["versions"] if v.get("id")]
    if not version_ids:
        return {"shot_names": [], "playlist_name": playlist_name}

    version_fields = ["id", SG_PLAYLIST_VERSION_FIELD, SG_PLAYLIST_SHOT_FIELD]
    versions = sg.find("Version", [["id", "in", version_ids]], version_fields)
    shot_names = [
        f"{v.get(SG_PLAYLIST_SHOT_FIELD)}/{v.get(SG_PLAYLIST_VERSION_FIELD)}"
        for v in versions if v.get(SG_PLAYLIST_VERSION_FIELD) or v.get(SG_PLAYLIST_SHOT_FIELD)
    ]
    return {
        "shot_names": anonymize_shot_names(shot_names),
        "playlist_name": playlist_name
    }

def parse_sg_playlist_url(url_or_id: str):
    """
    Extract the numeric playlist ID from a ShotGrid URL or a plain integer string.

    Supports:
        https://spi.shotgrid.autodesk.com/detail/Playlist/435694
        https://studio.shotgrid.autodesk.com/page/12345#Playlist_435694
        https://studio.shotgunstudio.com/page/12345#Playlist_435694
        435694  (plain integer string)

    Returns int playlist ID, or None if not parseable.
    """
    s = str(url_or_id).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r'#Playlist_(\d+)', s)
    if m:
        return int(m.group(1))
    m = re.search(r'/playlist/(\d+)', s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def fetch_playlist_to_csv(playlist_id: int, output_path: str) -> str:
    """
    Fetch a ShotGrid playlist and write a CSV with shot/jts/notes columns.

    Preserves the playlist's display order. Returns the playlist name.
    Raises RuntimeError / ValueError on configuration or API failures.
    """
    import csv

    if not SG_URL or not SG_SCRIPT_NAME or not SG_API_KEY:
        raise RuntimeError(
            "ShotGrid credentials not configured (SG_URL, SG_SCRIPT_NAME, SG_API_KEY)"
        )

    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    playlist = sg.find_one("Playlist", [["id", "is", playlist_id]], ["versions", "code"])

    if not playlist:
        raise ValueError(f"Playlist {playlist_id} not found in ShotGrid")

    playlist_name = playlist.get("code") or str(playlist_id)
    version_ids = [v["id"] for v in (playlist.get("versions") or []) if v.get("id")]

    if not version_ids:
        raise ValueError(f"Playlist '{playlist_name}' has no versions")

    version_fields = ["id", SG_PLAYLIST_VERSION_FIELD, SG_PLAYLIST_SHOT_FIELD]
    if SG_PLAYLIST_NOTES_FIELD:
        version_fields.append(SG_PLAYLIST_NOTES_FIELD)

    versions = sg.find("Version", [["id", "in", version_ids]], version_fields)

    id_to_version = {v["id"]: v for v in versions}
    ordered = [id_to_version[vid] for vid in version_ids if vid in id_to_version]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["shot", "jts", "notes"])
        writer.writeheader()
        for v in ordered:
            raw_notes = v.get(SG_PLAYLIST_NOTES_FIELD, "") if SG_PLAYLIST_NOTES_FIELD else ""
            if isinstance(raw_notes, list):
                notes = "\n".join(n.get("name", "") for n in raw_notes if n.get("name"))
            else:
                notes = raw_notes or ""
            writer.writerow({
                "shot": v.get(SG_PLAYLIST_SHOT_FIELD) or "",
                "jts": v.get(SG_PLAYLIST_VERSION_FIELD) or "",
                "notes": notes,
            })

    return playlist_name


def validate_shot_version_input(input_value, project_id=None):
    """
    Validate shot/version input and return the proper shot/version format.
    
    Args:
        input_value (str): User input - could be a version number or shot/asset name
        project_id (int, optional): Project ID to limit search scope
    
    Returns:
        dict: {
            "success": bool,
            "shot_version": str or None,  # Formatted shot/version string
            "message": str,              # Error message or success info
            "type": str                  # "version" or "shot" indicating what was matched
        }
    """
    if not input_value or not input_value.strip():
        return {
            "success": False,
            "shot_version": None,
            "message": "Input value cannot be empty",
            "type": None
        }
    
    input_value = input_value.strip()
    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    
    # Check if input is a number (version)
    if input_value.isdigit():
        # Search for version by version number using the custom version field
        # Convert to integer since ShotGrid expects integer for this field
        version_number = int(input_value)
        filters = [[SG_PLAYLIST_VERSION_FIELD, "is", version_number]]
        if project_id:
            filters.append(["project", "is", {"type": "Project", "id": project_id}])
        
        fields = ["id", "code", SG_PLAYLIST_SHOT_FIELD, SG_PLAYLIST_VERSION_FIELD]
        version = sg.find_one("Version", filters, fields)
        
        if version:
            shot_name = version.get(SG_PLAYLIST_SHOT_FIELD, "")
            version_name = version.get(SG_PLAYLIST_VERSION_FIELD, input_value)
            shot_version = f"{shot_name}/{version_name}"
            
            if DEMO_MODE:
                shot_version = f"{anonymize_shot_name(shot_name)}/{anonymize_version_name(version_name)}"
            
            return {
                "success": True,
                "shot_version": shot_version,
                "message": f"Found version {input_value}",
                "type": "version"
            }
        else:
            return {
                "success": False,
                "shot_version": None,
                "message": f"Version {input_value} not found",
                "type": "version"
            }
    
    else:
        # Search for shot/asset by name
        filters = [["code", "is", input_value]]
        if project_id:
            filters.append(["project", "is", {"type": "Project", "id": project_id}])
        
        fields = ["id", "code"]
        
        # Try to find as Shot first
        shot = sg.find_one("Shot", filters, fields)
        if shot:
            shot_name = shot.get("code", input_value)
            
            # Find the latest version for this shot
            version_filters = [
                [SG_PLAYLIST_SHOT_FIELD, "is", shot_name],
            ]
            if project_id:
                version_filters.append(["project", "is", {"type": "Project", "id": project_id}])
            
            version_fields = ["id", SG_PLAYLIST_VERSION_FIELD]
            latest_version = sg.find_one("Version", version_filters, version_fields, 
                                       order=[{"field_name": "created_at", "direction": "desc"}])
            
            if latest_version:
                version_name = latest_version.get(SG_PLAYLIST_VERSION_FIELD, "001")
                shot_version = f"{shot_name}/{version_name}"
            else:
                shot_version = f"{shot_name}/001"  # Default version if no versions found
            
            if DEMO_MODE:
                shot_version = f"{anonymize_shot_name(shot_name)}/{anonymize_version_name(version_name if latest_version else '001')}"
            
            return {
                "success": True,
                "shot_version": shot_version,
                "message": f"Found shot {input_value}",
                "type": "shot"
            }
        
        # Try to find as Asset if not found as Shot
        asset = sg.find_one("Asset", filters, fields)
        if asset:
            asset_name = asset.get("code", input_value)
            
            # Find the latest version for this asset
            version_filters = [
                [SG_PLAYLIST_SHOT_FIELD, "is", asset_name],  # Assuming assets use the same field
            ]
            if project_id:
                version_filters.append(["project", "is", {"type": "Project", "id": project_id}])
            
            version_fields = ["id", SG_PLAYLIST_VERSION_FIELD]
            latest_version = sg.find_one("Version", version_filters, version_fields,
                                       order=[{"field_name": "created_at", "direction": "desc"}])
            
            if latest_version:
                version_name = latest_version.get(SG_PLAYLIST_VERSION_FIELD, "001")
                shot_version = f"{asset_name}/{version_name}"
            else:
                shot_version = f"{asset_name}/001"  # Default version if no versions found
            
            if DEMO_MODE:
                shot_version = f"{anonymize_shot_name(asset_name)}/{anonymize_version_name(version_name if latest_version else '001')}"
            
            return {
                "success": True,
                "shot_version": shot_version,
                "message": f"Found asset {input_value}",
                "type": "asset"
            }
        
        # Not found as version, shot, or asset
        return {
            "success": False,
            "shot_version": None,
            "message": f"Shot/asset '{input_value}' not found",
            "type": "shot"
        }

# =============================================================================
# Calendar → SG Playlist Matching
# =============================================================================

_DEFAULT_MAPPING = {
    'default': {
        'strip_suffixes': ['[Virtual]', '(Virtual)', '- Virtual', '[Online]', '(Online)'],
    },
    'title_mappings': {},
}

_MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'tools', 'show_calendar_mapping.yaml')


def load_show_mapping(mapping_path: str = None) -> dict:
    path = mapping_path or _MAPPING_PATH
    if not os.path.exists(path):
        return _DEFAULT_MAPPING
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault('default', _DEFAULT_MAPPING['default'])
    data.setdefault('title_mappings', {})
    return data


def _strip_calendar_suffix(title: str, mapping: dict) -> str:
    suffixes = mapping.get('default', {}).get('strip_suffixes', [])
    result = title
    for suffix in suffixes:
        if result.endswith(suffix):
            result = result[:-len(suffix)].strip()
    return result


def _apply_title_mapping(stripped_title: str, title_mappings: dict) -> str:
    """
    Match stripped_title against title_mappings keys where $SHOW is a wildcard
    for the show code. Returns the mapped SG playlist prefix, or stripped_title
    if no entry matches.
    """
    for pattern_key, pattern_value in title_mappings.items():
        regex = re.escape(pattern_key).replace(r'\$SHOW', r'(.+?)')
        m = re.fullmatch(regex, stripped_title)
        if m:
            show = m.group(1)
            return pattern_value.replace('$SHOW', show)
    return stripped_title


def find_playlist_for_meeting(meeting_title: str, meeting_date: datetime,
                               mapping: dict = None) -> Optional[str]:
    """
    Find a ShotGrid playlist URL matching a calendar meeting by naming convention.

    Convention:
      Calendar: "ZORR: Model Dailies [Virtual]"  →  "ZORR: Model Dailies"
      SG:       "ZORR: Model Dailies 05/19/26"

    Matches on month/day only (MM/DD) to stay robust across year boundaries.

    Returns the SG playlist URL string, or None if not found.
    """
    if not SG_URL or not SG_SCRIPT_NAME or not SG_API_KEY:
        return None

    if mapping is None:
        mapping = load_show_mapping()

    stripped = _strip_calendar_suffix(meeting_title, mapping)
    playlist_prefix = _apply_title_mapping(stripped, mapping.get('title_mappings', {}))

    show_code = (stripped.split(':')[0] if ':' in stripped else stripped.split()[0]).strip()
    project = get_project_by_code(show_code)
    if not project:
        return None

    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    playlists = sg.find(
        'Playlist',
        [
            ['project', 'is', {'type': 'Project', 'id': project['id']}],
            ['code', 'starts_with', playlist_prefix],
        ],
        ['id', 'code'],
        order=[{'field_name': 'created_at', 'direction': 'desc'}],
        limit=50,
    )

    # Match on MM/DD only — year is intentionally ignored per spec
    month_day = meeting_date.strftime('%m/%d')
    for playlist in playlists:
        if month_day in (playlist.get('code') or ''):
            return f"{SG_URL}/detail/Playlist/{playlist['id']}"

    return None


def find_playlists_by_date(
    show_code: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list:
    """
    Return URLs of ALL SG playlists for the given show whose created_at falls
    within [start_dt, end_dt]. No title-prefix matching is performed.
    """
    if not SG_URL or not SG_SCRIPT_NAME or not SG_API_KEY:
        return []

    project = get_project_by_code(show_code)
    if not project:
        return []

    sg = Shotgun(SG_URL, SG_SCRIPT_NAME, SG_API_KEY)
    playlists = sg.find(
        'Playlist',
        [
            ['project', 'is', {'type': 'Project', 'id': project['id']}],
            ['created_at', 'greater_than', start_dt],
            ['created_at', 'less_than', end_dt],
        ],
        ['id', 'code'],
        order=[{'field_name': 'created_at', 'direction': 'asc'}],
    )

    return [f"{SG_URL}/detail/Playlist/{p['id']}" for p in playlists]


router = APIRouter()

class ValidateShotVersionRequest(BaseModel):
    input_value: str
    project_id: Optional[int] = None

@router.get("/shotgrid/active-projects")
def shotgrid_active_projects():
    try:
        projects = get_active_projects()
        return {"status": "success", "projects": projects}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@router.get("/shotgrid/latest-playlists/{project_id}")
def shotgrid_latest_playlists(project_id: int, limit: int = 20):
    try:
        playlists = get_latest_playlists_for_project(project_id, limit=limit)
        return {"status": "success", "playlists": playlists}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@router.get("/shotgrid/playlist-items/{playlist_id}")
def shotgrid_playlist_items(playlist_id: int):
    try:
        result = get_playlist_shot_names(playlist_id)
        return {
            "status": "success",
            "items": result["shot_names"],
            "playlist_name": result["playlist_name"]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@router.post("/shotgrid/validate-shot-version")
def shotgrid_validate_shot_version(request: ValidateShotVersionRequest):
    """
    Validate shot/version input and return the proper shot/version format.
    If input is a number, treat as version and find associated shot.
    If input is text, treat as shot/asset name and find latest version.
    """
    try:
        result = validate_shot_version_input(request.input_value, request.project_id)
        return {"status": "success", **result}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "error", 
            "success": False,
            "shot_version": None,
            "message": f"Error validating input: {str(e)}",
            "type": None
        })

@router.get("/shotgrid/most-recent-playlist-items")
def shotgrid_most_recent_playlist_items():
    try:
        projects = get_active_projects()
        if not projects:
            return {"status": "error", "message": "No active projects found"}
        # Get most recent project
        project = projects[0]
        playlists = get_latest_playlists_for_project(project['id'], limit=1)
        if not playlists:
            return {"status": "error", "message": "No playlists found for most recent project"}
        playlist = playlists[0]
        result = get_playlist_shot_names(playlist['id'])
        return {
            "status": "success",
            "project": project,
            "playlist": playlist,
            "items": result["shot_names"]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="ShotGrid Service Test CLI")
    parser.add_argument("--project", "-p", type=str, help="Optional project code to use for testing")
    args = parser.parse_args()
    
    # Convert project code to project ID if provided
    project_id_from_args = None
    if args.project:
        try:
            project = get_project_by_code(args.project)
            if project:
                project_id_from_args = project['id']
                print(f"🎯 Using project: {args.project} (ID: {project_id_from_args})")
            else:
                print(f"⚠️  Project code '{args.project}' not found, proceeding without project filter")
        except Exception as e:
            print(f"⚠️  Error looking up project '{args.project}': {str(e)}")
            print("Proceeding without project filter")
    
    print("ShotGrid Service Test CLI")
    if DEMO_MODE:
        print("🎭 DEMO MODE ACTIVE - Data will be anonymized")
    print("1. List all active projects")
    print("2. List latest playlists for a project")
    print("3. List shot/version info for a playlist")
    print("4. Test shot/version validation")
    choice = input("Enter choice (1/2/3/4): ").strip()

    if choice == "1":
        projects = get_active_projects()
        print(f"Active projects ({len(projects)}):")
        for pr in projects:
            print(f" - [id: {pr['id']}] code: {pr['code']} name: {pr.get('name', '')} status: {pr.get('sg_status', '')} created: {pr['created_at']}")
    elif choice == "2":
        project_id = project_id_from_args
        if not project_id:
            project_id_input = input("Enter project id: ").strip()
            try:
                project_id = int(project_id_input)
            except Exception:
                print("Invalid project id")
                exit(1)
        playlists = get_latest_playlists_for_project(project_id, limit=5)
        print(f"Playlists for project {project_id} ({len(playlists)}):")
        for pl in playlists:
            print(f" - [id: {pl['id']}] code: {pl['code']} created: {pl['created_at']} updated: {pl['updated_at']}")
    elif choice == "3":
        playlist_id = input("Enter playlist id: ").strip()
        try:
            playlist_id = int(playlist_id)
        except Exception:
            print("Invalid playlist id")
            exit(1)
        result = get_playlist_shot_names(playlist_id)
        print(f"Playlist: {result['playlist_name']}")
        print(f"Shots/Versions in playlist {playlist_id} ({len(result['shot_names'])}):")
        for item in result['shot_names']:
            print(f" - {item}")
    elif choice == "4":
        print("\n=== Shot/Version Validation Test ===")
        print("This will test the validate_shot_version_input function")
        print("You can enter:")
        print("- A number (e.g., '12345') to test version lookup")
        print("- A shot/asset name (e.g., 'SH010') to test shot lookup")
        print("- Type 'quit' to exit test mode")
        
        # Use command line project ID if provided, otherwise ask user
        project_id = project_id_from_args
        if not project_id:
            use_project = input("\nDo you want to limit search to a specific project? (y/n): ").strip().lower()
            if use_project == 'y':
                project_id_input = input("Enter project ID: ").strip()
                try:
                    project_id = int(project_id_input)
                    print(f"Using project ID: {project_id}")
                except ValueError:
                    print("Invalid project ID, proceeding without project filter")
                    project_id = None
        
        print(f"\n--- Starting validation tests ---")
        if project_id:
            print(f"Project filter: {project_id}")
        else:
            print("Project filter: None (searching all projects)")
        print("Enter test values or 'quit' to exit:\n")
        
        while True:
            test_input = input("Test input: ").strip()
            if test_input.lower() == 'quit':
                break
            if not test_input:
                continue
                
            print(f"\n🔍 Testing: '{test_input}'")
            try:
                result = validate_shot_version_input(test_input, project_id)
                print(f"✅ Success: {result['success']}")
                print(f"📝 Message: {result['message']}")
                print(f"🎯 Type: {result['type']}")
                if result['shot_version']:
                    print(f"📋 Shot/Version: {result['shot_version']}")
                else:
                    print("📋 Shot/Version: None")
                print("-" * 50)
            except Exception as e:
                print(f"❌ Error during validation: {str(e)}")
                print("-" * 50)
        
        print("Validation test completed.")
    else:
        print("Invalid choice.")
