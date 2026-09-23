"""
Unit tests for Secrets Manager (services/secrets_manager.py).
Tests gitignored credential persistence, multi-key parsing, priority fallbacks,
and Google Drive sync secret retrieval.
"""

import os
import json
import unittest
from unittest.mock import patch
from PyQt5.QtCore import QSettings

import storage_paths
from services.secrets_manager import (
    parse_api_keys, get_secrets_file_path, load_secrets, save_secrets,
    get_gemini_api_keys, save_gemini_api_keys, get_gdrive_secrets, save_gdrive_secrets,
    SETTINGS_GROUP, SETTINGS_SECTION, KEY_API_KEY, _settings
)


class TestSecretsManager(unittest.TestCase):

    def setUp(self):
        # Clean up test secrets file in test temp dir if present
        path = get_secrets_file_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        # Clean test QSettings
        s = _settings()
        s.remove(KEY_API_KEY)

    def tearDown(self):
        path = get_secrets_file_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        s = _settings()
        s.remove(KEY_API_KEY)

    def test_parse_api_keys(self):
        # Mixed delimiters, duplicates, and example placeholders
        raw = "AIzaSyKey1, AIzaSyKey2\nAIzaSyKey1; AIzaSyYourFirstKeyHere\nYOUR_API_KEY\nAIzaSyKey3"
        keys = parse_api_keys(raw)
        self.assertEqual(keys, ["AIzaSyKey1", "AIzaSyKey2", "AIzaSyKey3"])

        # List input
        list_input = ["AIzaSyKeyA", "AIzaSyKeyB, AIzaSyKeyC", "YOUR_GEMINI_API_KEY"]
        keys_list = parse_api_keys(list_input)
        self.assertEqual(keys_list, ["AIzaSyKeyA", "AIzaSyKeyB", "AIzaSyKeyC"])

    def test_test_environment_isolates_path(self):
        # Under tests, path must be inside test temp directory
        path = get_secrets_file_path()
        self.assertTrue(path.endswith("secrets.json"))
        temp_dir = storage_paths._get_test_temp_dir()
        self.assertTrue(path.startswith(temp_dir))

    def test_save_and_load_secrets(self):
        data = {
            "gemini_api_keys": ["KEY_1", "KEY_2"],
            "gdrive_sync": {
                "client_id": "test-client-id",
                "client_secret": "test-client-sec"
            }
        }
        success = save_secrets(data)
        self.assertTrue(success)

        loaded = load_secrets()
        self.assertEqual(loaded["gemini_api_keys"], ["KEY_1", "KEY_2"])
        self.assertEqual(loaded["gdrive_sync"]["client_id"], "test-client-id")

    def test_get_gemini_api_keys_from_secrets_file(self):
        save_secrets({"gemini_api_keys": ["KEY_FROM_FILE_1", "KEY_FROM_FILE_2"]})
        keys = get_gemini_api_keys()
        self.assertEqual(keys, ["KEY_FROM_FILE_1", "KEY_FROM_FILE_2"])

    def test_get_gemini_api_keys_fallback_to_qsettings(self):
        # With empty secrets.json, falls back to QSettings
        s = _settings()
        s.setValue(KEY_API_KEY, "KEY_FROM_SETTINGS")
        keys = get_gemini_api_keys()
        self.assertEqual(keys, ["KEY_FROM_SETTINGS"])

    @patch.dict(os.environ, {"GEMINI_API_KEYS": "ENV_KEY_1, ENV_KEY_2"})
    def test_get_gemini_api_keys_env_var_fallback(self):
        # When no secrets.json exists, env var takes precedence over QSettings
        keys = get_gemini_api_keys()
        self.assertEqual(keys, ["ENV_KEY_1", "ENV_KEY_2"])

    def test_save_gemini_api_keys_syncs_both(self):
        save_gemini_api_keys(["SYNC_KEY_1", "SYNC_KEY_2"])
        # Check secrets.json
        loaded = load_secrets()
        self.assertEqual(loaded["gemini_api_keys"], ["SYNC_KEY_1", "SYNC_KEY_2"])
        # Check QSettings
        s = _settings()
        self.assertIn("SYNC_KEY_1", s.value(KEY_API_KEY, "", type=str))

    def test_gdrive_secrets_load_and_save(self):
        save_gdrive_secrets("my_drive_id", "my_drive_sec")
        cid, csec = get_gdrive_secrets()
        self.assertEqual(cid, "my_drive_id")
        self.assertEqual(csec, "my_drive_sec")


if __name__ == "__main__":
    unittest.main()
