import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Ensure local imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gdrive_service import GDriveService

class TestGDriveService(unittest.TestCase):
    def setUp(self):
        # Create a clean mock or clear state
        self.service = GDriveService()
        self.service._tokens = None
        self.service._config = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }

    def test_is_configured(self):
        self.assertTrue(self.service.is_configured())
        
        self.service._config = {"client_id": "", "client_secret": ""}
        self.assertFalse(self.service.is_configured())

    def test_is_linked(self):
        self.assertFalse(self.service.is_linked())
        
        self.service._tokens = {"refresh_token": "abc", "access_token": "def"}
        self.assertTrue(self.service.is_linked())
        
        self.service.unlink()
        self.assertFalse(self.service.is_linked())

    @patch("requests.post")
    def test_exchange_code_for_tokens(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600
        }
        mock_post.return_value = mock_response

        # Mock email fetch
        self.service._fetch_user_email = MagicMock(return_value="user@gmail.com")

        self.service.exchange_code_for_tokens("test_code")
        self.assertTrue(self.service.is_linked())
        self.assertEqual(self.service.get_email(), "user@gmail.com")

    @patch("requests.get")
    def test_get_or_create_backups_folder_exists(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [{"id": "folder_123"}]
        }
        mock_get.return_value = mock_response

        folder_id = self.service._get_or_create_backups_folder({"Authorization": "Bearer token"})
        self.assertEqual(folder_id, "folder_123")


if __name__ == "__main__":
    unittest.main()
