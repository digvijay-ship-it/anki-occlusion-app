"""
Secrets Manager for Anki Occlusion.
Provides secure, centralized management of local API keys and credentials
(Google Gemini AI keys, Google Drive sync credentials, etc.)
strictly isolated from git tracking.
"""

import os
import json
import re
from pathlib import Path
from PyQt5.QtCore import QSettings

try:
    import storage_paths
except ImportError:
    storage_paths = None

# Settings fallback
SETTINGS_GROUP = "AnkiOcclusion"
SETTINGS_SECTION = "AISettings"
KEY_API_KEY = "gemini_api_key"

SECRETS_FILENAME = "secrets.json"
EXAMPLE_FILENAME = "secrets.example.json"


def get_project_root() -> str:
    """Return project root directory."""
    if storage_paths and hasattr(storage_paths, "app_base_dir"):
        return storage_paths.app_base_dir()
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_secrets_file_path() -> str:
    """
    Get the absolute path to secrets.json.
    Under unit tests, isolates into the test temp directory.
    In normal runtime, resolves in the project root directory.
    """
    if storage_paths and hasattr(storage_paths, "is_running_tests") and storage_paths.is_running_tests():
        return os.path.join(storage_paths._get_test_temp_dir(), SECRETS_FILENAME)

    env_path = os.environ.get("ANKI_SECRETS_PATH")
    if env_path and os.path.exists(env_path):
        return os.path.abspath(env_path)

    root_path = os.path.join(get_project_root(), SECRETS_FILENAME)
    if os.path.exists(root_path):
        return root_path

    cwd_path = os.path.join(os.getcwd(), SECRETS_FILENAME)
    if os.path.exists(cwd_path):
        return cwd_path

    return root_path


def parse_api_keys(raw) -> list[str]:
    """
    Parse comma, semicolon, newline, whitespace separated, or list-based keys
    into a clean list of unique valid keys, filtering out placeholder text.
    """
    if not raw:
        return []

    tokens = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str):
                tokens.extend(re.split(r'[\r\n,;\s]+', item.strip()))
    elif isinstance(raw, str):
        tokens = re.split(r'[\r\n,;\s]+', raw.strip())
    else:
        tokens = [str(raw)]

    keys = []
    seen = set()
    for t in tokens:
        cleaned = t.strip().strip("'\"")
        if not cleaned:
            continue
        # Filter out common dummy / example placeholders
        upper = cleaned.upper()
        if "YOUR_" in upper or "EXAMPLE" in upper or cleaned.startswith("AIzaSyYour"):
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            keys.append(cleaned)
    return keys


def load_secrets() -> dict:
    """
    Load secrets dictionary from secrets.json.
    Returns empty dict if file does not exist or fails to parse.
    """
    path = get_secrets_file_path()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[SecretsManager] Failed to read {path}: {e}")
        return {}


def save_secrets(data: dict) -> bool:
    """
    Save dictionary to secrets.json.
    """
    path = get_secrets_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Preserve existing entries if merging
        current = load_secrets()
        current.update(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[SecretsManager] Failed to save {path}: {e}")
        return False


def get_gemini_api_keys() -> list[str]:
    """
    Retrieve Gemini API keys with multi-source priority:
    1. secrets.json ('gemini_api_keys' list or 'gemini_api_key' string)
    2. Environment variables: GEMINI_API_KEYS, GEMINI_API_KEY
    3. QSettings fallback ('gemini_api_key')
    """
    # 1. Check secrets.json
    secrets = load_secrets()
    if secrets:
        raw_keys = secrets.get("gemini_api_keys") or secrets.get("gemini_api_key")
        parsed = parse_api_keys(raw_keys)
        if parsed:
            return parsed

    # 2. Check environment variables
    env_keys = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY")
    if env_keys:
        parsed = parse_api_keys(env_keys)
        if parsed:
            return parsed

    # 3. Check QSettings
    s = QSettings(SETTINGS_GROUP, SETTINGS_SECTION)
    raw = s.value(KEY_API_KEY, "", type=str)
    return parse_api_keys(raw)


def save_gemini_api_keys(keys: list[str] | str, sync_file: bool = True) -> bool:
    """
    Save Gemini API keys to QSettings and optionally update secrets.json.
    """
    parsed = parse_api_keys(keys)
    joined_str = "\n".join(parsed)

    # 1. Update QSettings
    s = QSettings(SETTINGS_GROUP, SETTINGS_SECTION)
    s.setValue(KEY_API_KEY, joined_str)

    # 2. Update secrets.json if requested and not under test
    if sync_file:
        current = load_secrets()
        current["gemini_api_keys"] = parsed
        return save_secrets(current)
    return True


def get_gdrive_secrets() -> tuple[str, str]:
    """
    Retrieve Google Drive Client ID and Client Secret from secrets.json or env.
    Returns (client_id, client_secret).
    """
    secrets = load_secrets()
    client_id = ""
    client_secret = ""

    # Check nested "gdrive_sync" or flat keys
    if isinstance(secrets.get("gdrive_sync"), dict):
        client_id = secrets["gdrive_sync"].get("client_id", "")
        client_secret = secrets["gdrive_sync"].get("client_secret", "")
    if not client_id:
        client_id = secrets.get("gdrive_client_id", "")
    if not client_secret:
        client_secret = secrets.get("gdrive_client_secret", "")

    # Fallback to env vars
    if not client_id:
        client_id = os.environ.get("ANKI_GDRIVE_CLIENT_ID", "")
    if not client_secret:
        client_secret = os.environ.get("ANKI_GDRIVE_CLIENT_SECRET", "")

    return client_id.strip(), client_secret.strip()


def save_gdrive_secrets(client_id: str, client_secret: str) -> bool:
    """
    Save Google Drive credentials to secrets.json.
    """
    current = load_secrets()
    if "gdrive_sync" not in current or not isinstance(current["gdrive_sync"], dict):
        current["gdrive_sync"] = {}
    current["gdrive_sync"]["client_id"] = client_id.strip()
    current["gdrive_sync"]["client_secret"] = client_secret.strip()
    return save_secrets(current)
