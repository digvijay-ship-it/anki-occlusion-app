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

    @patch("requests.get")
    def test_get_or_create_subfolder_escapes_single_quotes(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [{"id": "folder_456"}]
        }
        mock_get.return_value = mock_response

        # Clear cache first to force a GDrive API call
        self.service._folder_cache.clear()

        folder_id = self.service._get_or_create_subfolder(
            {"Authorization": "Bearer token"}, "o'brien", "parent_123"
        )
        self.assertEqual(folder_id, "folder_456")
        
        args, kwargs = mock_get.call_args
        called_url = args[0]
        import urllib.parse
        parsed = urllib.parse.urlparse(called_url)
        params = urllib.parse.parse_qs(parsed.query)
        query_val = params["q"][0]
        self.assertIn("name = 'o\\'brien'", query_val)

    @patch("services.gdrive_service.HTTPServer")
    def test_start_oauth_flow_state(self, mock_http_server):
        mock_server = MagicMock()
        mock_http_server.return_value = mock_server
        
        auth_url, server = self.service.start_oauth_flow()
        
        self.assertIsNotNone(server.oauth_state)
        self.assertIn(f"state={server.oauth_state}", auth_url)

    def test_oauth_receiver_handler_csrf(self):
        from services.gdrive_service import OAuthReceiverHandler
        
        mock_server = MagicMock()
        mock_server.auth_code = None
        mock_server.oauth_state = "expected_csrf_token"
        
        handler = OAuthReceiverHandler.__new__(OAuthReceiverHandler)
        handler.server = mock_server
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        
        # Case 1: missing state
        handler.path = "/?code=123"
        handler.do_GET()
        handler.send_response.assert_called_with(400)
        self.assertIsNone(mock_server.auth_code)
        
        # Case 2: incorrect state
        mock_server.auth_code = None
        handler.send_response.reset_mock()
        handler.path = "/?code=123&state=wrong_token"
        handler.do_GET()
        handler.send_response.assert_called_with(400)
        self.assertIsNone(mock_server.auth_code)
        
        # Case 3: correct state
        mock_server.auth_code = None
        handler.send_response.reset_mock()
        handler.path = "/?code=123&state=expected_csrf_token"
        handler.do_GET()
        handler.send_response.assert_called_with(200)
        self.assertEqual(mock_server.auth_code, "123")

    @patch("os.chmod")
    @patch("requests.post")
    def test_save_tokens_chmod(self, mock_post, mock_chmod):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600
        }
        mock_post.return_value = mock_response
        self.service._fetch_user_email = MagicMock(return_value="user@gmail.com")

        self.service.exchange_code_for_tokens("test_code")
        mock_chmod.assert_called_once()
        args, _ = mock_chmod.call_args
        self.assertEqual(args[1], 0o600)


if __name__ == "__main__":
    unittest.main()
