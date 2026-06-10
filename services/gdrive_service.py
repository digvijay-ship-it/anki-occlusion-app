# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import urllib.parse
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import storage paths
sys.path.append(r"C:\Users\Digvijay\Desktop\Anki gs3236208")
import storage_paths

TOKEN_FILE_NAME = "anki_gdrive_tokens.json"
CONFIG_FILE_NAME = "anki_gdrive_config.json"

# Local receiver handler for OAuth redirect
class OAuthReceiverHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress logging

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        code = params.get("code", [None])[0]
        
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        if code:
            self.server.auth_code = code
            self.wfile.write("""
                <html>
                <body style="font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding-top: 100px; background-color: #1E1E2E; color: #CDD6F4; line-height: 1.6;">
                    <h2 style="color: #A6E3A1; font-size: 28px;">✔ Authentication Successful!</h2>
                    <p style="font-size: 16px;">Google Drive has been successfully linked to Anki Occlusion.</p>
                    <p style="font-size: 14px; color: #6C7086;">You can now close this tab and return to the application.</p>
                </body>
                </html>
            """.encode("utf-8"))
        else:
            self.wfile.write("""
                <html>
                <body style="font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding-top: 100px; background-color: #1E1E2E; color: #F38BA8; line-height: 1.6;">
                    <h2 style="font-size: 28px;">❌ Authentication Failed</h2>
                    <p style="font-size: 16px;">No authorization code was returned by Google.</p>
                    <p style="font-size: 14px; color: #6C7086;">Please try linking your account again.</p>
                </body>
                </html>
            """.encode("utf-8"))


class GDriveService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GDriveService, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tokens = None
        self._config = None
        self._initialized = True
        self._load_tokens()
        self._load_config()

    def _load_tokens(self):
        path = storage_paths._home_file(TOKEN_FILE_NAME)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._tokens = json.load(f)
            except Exception as e:
                print(f"[GDriveService] Failed to load tokens: {e}")
                self._tokens = None

    def _save_tokens(self):
        path = storage_paths._home_file(TOKEN_FILE_NAME)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._tokens, f, indent=2)
        except Exception as e:
            print(f"[GDriveService] Failed to save tokens: {e}")

    def _load_config(self):
        # First check the home folder
        path = storage_paths._home_file(CONFIG_FILE_NAME)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                    return
            except Exception:
                pass
        # Fall back to default placeholders
        self._config = {
            "client_id": "205261143452-r2tv7nc4ndp2s4ncd4u6n2tfl4a4hjcb.apps.googleusercontent.com",
            "client_secret": "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"
        }

    def save_config(self, client_id, client_secret):
        self._config = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip()
        }
        path = storage_paths._home_file(CONFIG_FILE_NAME)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"[GDriveService] Failed to save config: {e}")

    def get_config(self):
        return self._config

    def is_configured(self):
        return bool(self._config.get("client_id")) and bool(self._config.get("client_secret"))

    def is_linked(self):
        return self._tokens is not None and "refresh_token" in self._tokens

    def get_email(self):
        if self._tokens:
            return self._tokens.get("email", "Connected Account")
        return ""

    def unlink(self):
        self._tokens = None
        path = storage_paths._home_file(TOKEN_FILE_NAME)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def start_oauth_flow(self, port=8080):
        if not self.is_configured():
            raise ValueError("Google OAuth credentials (Client ID / Secret) are not configured.")

        # 1. Start local receiver
        server = HTTPServer(("localhost", port), OAuthReceiverHandler)
        server.auth_code = None
        server.timeout = 120.0  # 2 minute timeout

        def _run():
            server.handle_request()
            server.server_close()

        threading.Thread(target=_run, daemon=True, name="GDrive-OAuthReceiver").start()

        # 2. Build OAuth consent URL
        client_id = self._config["client_id"]
        redirect_uri = f"http://localhost:{port}"
        scope = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"
        
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={urllib.parse.quote(client_id)}&"
            f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
            "response_type=code&"
            f"scope={urllib.parse.quote(scope)}&"
            "access_type=offline&"
            "prompt=consent"
        )
        return auth_url, server

    def exchange_code_for_tokens(self, code, port=8080):
        client_id = self._config["client_id"]
        client_secret = self._config["client_secret"]
        redirect_uri = f"http://localhost:{port}"

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }

        r = requests.post(token_url, data=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Token exchange failed: {r.text}")

        res = r.json()
        self._tokens = {
            "access_token": res.get("access_token"),
            "refresh_token": res.get("refresh_token"),
            "expires_in": res.get("expires_in"),
            "token_type": res.get("token_type"),
            "created_at": time.time()
        }

        # Fetch email address of authenticated user
        email = self._fetch_user_email(res.get("access_token"))
        if email:
            self._tokens["email"] = email

        self._save_tokens()
        return True

    def _fetch_user_email(self, access_token):
        try:
            url = "https://www.googleapis.com/oauth2/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                return r.json().get("email")
        except Exception as e:
            print(f"[GDriveService] Failed to fetch user email: {e}")
        return None

    def get_access_token(self):
        if not self.is_linked():
            return None

        # Check if expired
        now = time.time()
        created = self._tokens.get("created_at", 0)
        expires_in = self._tokens.get("expires_in", 3600)
        
        # Buffer of 5 minutes
        if now - created < expires_in - 300:
            return self._tokens["access_token"]

        # Token is expired, refresh it
        print("[GDriveService] Access token expired. Refreshing...")
        client_id = self._config["client_id"]
        client_secret = self._config["client_secret"]
        refresh_token = self._tokens["refresh_token"]

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }

        r = requests.post(token_url, data=payload)
        if r.status_code != 200:
            print(f"[GDriveService] Token refresh failed: {r.text}")
            # If the refresh token was revoked, unlink
            if "invalid_grant" in r.text:
                self.unlink()
            return None

        res = r.json()
        self._tokens["access_token"] = res.get("access_token")
        self._tokens["expires_in"] = res.get("expires_in", 3600)
        self._tokens["created_at"] = time.time()
        self._save_tokens()
        return self._tokens["access_token"]

    def upload_file_to_drive(self, local_file_path, drive_filename=None):
        if not self.is_linked() or not os.path.exists(local_file_path):
            return False

        access_token = self.get_access_token()
        if not access_token:
            return False

        if not drive_filename:
            drive_filename = os.path.basename(local_file_path)

        headers = {"Authorization": f"Bearer {access_token}"}

        # 1. Get or create target backups folder
        folder_id = self._get_or_create_backups_folder(headers)
        if not folder_id:
            print("[GDriveService] Failed to resolve target backups folder on Drive")
            return False

        # 2. Check if file already exists in folder
        file_id = self._find_file_in_folder(headers, drive_filename, folder_id)

        file_size = os.path.getsize(local_file_path)

        # 3. Perform upload
        try:
            if file_id:
                # Update existing file (using simple upload protocol for typical small DB files)
                url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
                with open(local_file_path, "rb") as f:
                    r = requests.patch(url, headers=headers, data=f)
                if r.status_code == 200:
                    print(f"[GDriveService] Successfully updated: {drive_filename} on Drive")
                    return True
            else:
                # Create new file metadata
                metadata_url = "https://www.googleapis.com/drive/v3/files"
                metadata = {
                    "name": drive_filename,
                    "parents": [folder_id]
                }
                
                # Upload using multipart upload protocol
                # For simplicity and robustness on typical file sizes (<5MB):
                multipart_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
                files = {
                    "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (drive_filename, open(local_file_path, "rb"), "application/octet-stream")
                }
                r = requests.post(multipart_url, headers=headers, files=files)
                if r.status_code == 200:
                    print(f"[GDriveService] Successfully uploaded: {drive_filename} to Drive")
                    return True
        except Exception as e:
            print(f"[GDriveService] Exception during file upload: {e}")
        return False

    def _get_or_create_backups_folder(self, headers):
        folder_name = "Anki Occlusion Backups"
        
        # Search for folder
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id)"
        
        try:
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                files = r.json().get("files", [])
                if files:
                    return files[0]["id"]
            
            # Create folder if not found
            create_url = "https://www.googleapis.com/drive/v3/files"
            metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            r = requests.post(create_url, headers=headers, json=metadata)
            if r.status_code == 200:
                return r.json().get("id")
        except Exception as e:
            print(f"[GDriveService] Folder check failed: {e}")
        return None

    def _find_file_in_folder(self, headers, filename, folder_id):
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id)"
        try:
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                files = r.json().get("files", [])
                if files:
                    return files[0]["id"]
        except Exception as e:
            print(f"[GDriveService] File check failed: {e}")
        return None


# Singleton instance
gdrive_store = GDriveService()
