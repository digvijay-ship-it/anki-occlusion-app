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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        state = params.get("state", [None])[0]
        
        # Verify CSRF state token
        expected_state = getattr(self.server, "oauth_state", None)
        if expected_state and state != expected_state:
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("""
                <html>
                <body style="font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding-top: 100px; background-color: #1E1E2E; color: #F38BA8; line-height: 1.6;">
                    <h2 style="font-size: 28px;">❌ CSRF State Verification Failed</h2>
                    <p style="font-size: 16px;">The state token returned by Google did not match. This could indicate a CSRF attack.</p>
                </body>
                </html>
            """.encode("utf-8"))
            return

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
_SYNC_DISABLED_LOGGED = False
_SYNC_DISABLED_LOGGED_LOCK = threading.Lock()


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
        self._sync_cache = {}
        self._folder_cache = {}
        self._folder_contents_cache = {}
        self._initialized = True
        self._load_tokens()
        self._load_config()
        self._load_sync_cache()
        self._load_folder_cache()

        import queue
        self._upload_queue = queue.Queue()
        self._uploader_thread = threading.Thread(
            target=self._uploader_worker_loop, daemon=True, name="GDrive-QueueUploader"
        )
        self._uploader_thread.start()

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
            try:
                os.chmod(path, 0o600)
            except Exception as e:
                print(f"[GDriveService] Failed to set token permissions: {e}")
        except Exception as e:
            print(f"[GDriveService] Failed to save tokens: {e}")

    def _load_config(self):
        global _SYNC_DISABLED_LOGGED
        
        # Load local .env file manually from the project root if it exists
        try:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            os.environ[k] = v
        except Exception:
            pass

        # First check the home folder
        path = storage_paths._home_file(CONFIG_FILE_NAME)
        has_loaded = False
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                    if not self._config.get("client_secret"):
                        self._config["client_secret"] = os.environ.get("ANKI_GDRIVE_CLIENT_SECRET", "")
                    has_loaded = True
            except Exception:
                pass
        
        if not has_loaded:
            # Fall back to default placeholders
            self._config = {
                "client_id": "205261143452-r2tv7nc4ndp2s4ncd4u6n2tfl4a4hjcb.apps.googleusercontent.com",
                "client_secret": os.environ.get("ANKI_GDRIVE_CLIENT_SECRET", "")
            }

        # Check if secret is empty and log it once per process
        if not self._config.get("client_secret"):
            with _SYNC_DISABLED_LOGGED_LOCK:
                if not _SYNC_DISABLED_LOGGED:
                    print("[gdrive] ANKI_GDRIVE_CLIENT_SECRET not set — sync disabled")
                    _SYNC_DISABLED_LOGGED = True

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

    def _load_sync_cache(self):
        path = storage_paths._home_file("anki_gdrive_sync_cache.json")
        self._sync_cache = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._sync_cache = json.load(f)
            except Exception as e:
                print(f"[GDriveService] Failed to load sync cache: {e}")

    def _save_sync_cache(self):
        path = storage_paths._home_file("anki_gdrive_sync_cache.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._sync_cache, f, indent=2)
        except Exception as e:
            print(f"[GDriveService] Failed to save sync cache: {e}")

    def _load_folder_cache(self):
        path = storage_paths._home_file("anki_gdrive_folder_cache.json")
        self._folder_cache = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._folder_cache = json.load(f)
            except Exception as e:
                print(f"[GDriveService] Failed to load folder cache: {e}")

    def _save_folder_cache(self):
        path = storage_paths._home_file("anki_gdrive_folder_cache.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._folder_cache, f, indent=2)
        except Exception as e:
            print(f"[GDriveService] Failed to save folder cache: {e}")

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
        self._sync_cache = {}
        self._folder_cache = {}
        self._folder_contents_cache = {}
        path = storage_paths._home_file(TOKEN_FILE_NAME)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        cache_path = storage_paths._home_file("anki_gdrive_sync_cache.json")
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception:
                pass
        folder_cache_path = storage_paths._home_file("anki_gdrive_folder_cache.json")
        if os.path.exists(folder_cache_path):
            try:
                os.remove(folder_cache_path)
            except Exception:
                pass

    def start_oauth_flow(self, port=8080):
        if not self.is_configured():
            raise ValueError("Google OAuth credentials (Client ID / Secret) are not configured.")

        # 1. Start local receiver
        server = HTTPServer(("localhost", port), OAuthReceiverHandler)
        server.auth_code = None
        server.timeout = 0.5
        server.running = True

        import secrets
        state = secrets.token_urlsafe(16)
        server.oauth_state = state

        def _run():
            start_time = time.time()
            while server.running and not server.auth_code and (time.time() - start_time < 120.0):
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
            "prompt=consent&"
            f"state={urllib.parse.quote(state)}"
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

        r = requests.post(token_url, data=payload, timeout=15)
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
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.json().get("email")
        except Exception as e:
            print(f"[GDriveService] Failed to fetch user email: {e}")
        return None

    def get_access_token(self):
        if not self.is_linked() or not self.is_configured():
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

        r = requests.post(token_url, data=payload, timeout=15)
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
                    file_data = f.read()
                r = requests.patch(url, headers=headers, data=file_data, timeout=15)
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
                with open(local_file_path, "rb") as f:
                    file_data = f.read()
                files = {
                    "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (drive_filename, file_data, "application/octet-stream")
                }
                r = requests.post(multipart_url, headers=headers, files=files, timeout=15)
                if r.status_code == 200:
                    print(f"[GDriveService] Successfully uploaded: {drive_filename} to Drive")
                    return True
        except Exception as e:
            print(f"[GDriveService] Exception during file upload: {e}")
        return False

    def _escape_drive_query(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _get_or_create_backups_folder(self, headers):
        folder_name = "Anki Occlusion Backups"
        escaped_folder_name = self._escape_drive_query(folder_name)
        
        # Search for folder
        query = f"name = '{escaped_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id)"
        
        try:
            r = requests.get(url, headers=headers, timeout=15)
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
            r = requests.post(create_url, headers=headers, json=metadata, timeout=15)
            if r.status_code == 200:
                return r.json().get("id")
        except Exception as e:
            print(f"[GDriveService] Folder check failed: {e}")
        return None

    def _find_file_in_folder(self, headers, filename, folder_id):
        if folder_id not in self._folder_contents_cache:
            files = self.list_files_in_folder(folder_id)
            self._folder_contents_cache[folder_id] = {
                f["name"]: {
                    "id": f["id"],
                    "size": f.get("size", "0"),
                    "mimeType": f.get("mimeType"),
                    "createdTime": f.get("createdTime")
                }
                for f in files
            }
        
        file_info = self._folder_contents_cache[folder_id].get(filename)
        if file_info:
            return file_info["id"]
        return None

    def _get_or_create_subfolder(self, headers, folder_name, parent_id):
        cache_key = f"{parent_id}:{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        escaped_name = self._escape_drive_query(folder_name)
        query = f"name = '{escaped_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id)"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                files = r.json().get("files", [])
                if files:
                    folder_id = files[0]["id"]
                    self._folder_cache[cache_key] = folder_id
                    self._save_folder_cache()
                    return folder_id
            
            # Create folder if not found
            create_url = "https://www.googleapis.com/drive/v3/files"
            metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id]
            }
            r = requests.post(create_url, headers=headers, json=metadata, timeout=15)
            if r.status_code == 200:
                folder_id = r.json().get("id")
                self._folder_cache[cache_key] = folder_id
                self._save_folder_cache()
                return folder_id
        except Exception as e:
            print(f"[GDriveService] Subfolder check failed for '{folder_name}': {e}")
        return None

    def _resolve_gdrive_folder_path(self, headers, parent_id, path_segments):
        current_parent = parent_id
        for segment in path_segments:
            current_parent = self._get_or_create_subfolder(headers, segment, current_parent)
            if not current_parent:
                return None
        return current_parent

    def _upload_file_to_folder_id(self, headers, local_file_path, folder_id, drive_filename=None):
        if not os.path.exists(local_file_path):
            return "failed"
        if not drive_filename:
            drive_filename = os.path.basename(local_file_path)
            
        file_id = self._find_file_in_folder(headers, drive_filename, folder_id)
        file_size = os.path.getsize(local_file_path)
        local_file_path_norm = os.path.abspath(local_file_path).replace("\\", "/")
        
        try:
            if file_id:
                # Get drive size from folder contents cache if present
                drive_size_str = "0"
                if folder_id in self._folder_contents_cache and drive_filename in self._folder_contents_cache[folder_id]:
                    drive_size_str = self._folder_contents_cache[folder_id][drive_filename].get("size", "0")
                else:
                    # Fallback to API if cache missing (e.g. background uploads)
                    url_get = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size"
                    r_get = requests.get(url_get, headers=headers, timeout=15)
                    if r_get.status_code == 200:
                        drive_size_str = r_get.json().get("size", "0")
                    elif r_get.status_code == 404:
                        file_id = None
                
                if file_id and int(drive_size_str) == file_size:
                    try:
                        mtime = os.path.getmtime(local_file_path)
                        self._sync_cache[local_file_path_norm] = {"mtime": mtime, "size": file_size, "drive_file_id": file_id}
                        self._save_sync_cache()
                    except Exception:
                        pass
                    return "skipped"
            
            if file_id:
                # Update existing file
                url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
                with open(local_file_path, "rb") as f:
                    file_data = f.read()
                r = requests.patch(url, headers=headers, data=file_data, timeout=30)
                if r.status_code == 200:
                    try:
                        mtime = os.path.getmtime(local_file_path)
                        self._sync_cache[local_file_path_norm] = {"mtime": mtime, "size": file_size, "drive_file_id": file_id}
                        self._save_sync_cache()
                        # Update folder contents cache
                        if folder_id in self._folder_contents_cache:
                            self._folder_contents_cache[folder_id][drive_filename] = {
                                "id": file_id,
                                "size": str(file_size)
                            }
                    except Exception:
                        pass
                    return "updated"
                elif r.status_code == 404:
                    print(f"[GDriveService] File {file_id} or folder {folder_id} returned 404 during update, invalidating cache...")
                    keys_to_remove = [k for k, v in self._folder_cache.items() if v == folder_id]
                    for k in keys_to_remove:
                        self._folder_cache.pop(k, None)
                    self._save_folder_cache()
            else:
                # Create new file
                metadata_url = "https://www.googleapis.com/drive/v3/files"
                metadata = {
                    "name": drive_filename,
                    "parents": [folder_id]
                }
                multipart_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
                with open(local_file_path, "rb") as f:
                    file_data = f.read()
                files = {
                    "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (drive_filename, file_data, "application/octet-stream")
                }
                r = requests.post(multipart_url, headers=headers, files=files, timeout=30)
                if r.status_code == 200:
                    res_json = r.json()
                    uploaded_file_id = res_json.get("id")
                    try:
                        mtime = os.path.getmtime(local_file_path)
                        self._sync_cache[local_file_path_norm] = {"mtime": mtime, "size": file_size, "drive_file_id": uploaded_file_id}
                        self._save_sync_cache()
                        # Add to folder contents cache
                        if folder_id in self._folder_contents_cache:
                            self._folder_contents_cache[folder_id][drive_filename] = {
                                "id": uploaded_file_id,
                                "size": str(file_size)
                            }
                    except Exception:
                        pass
                    return "uploaded"
                elif r.status_code == 404:
                    print(f"[GDriveService] Parent folder {folder_id} returned 404 during upload, invalidating cache...")
                    keys_to_remove = [k for k, v in self._folder_cache.items() if v == folder_id]
                    for k in keys_to_remove:
                        self._folder_cache.pop(k, None)
                    self._save_folder_cache()
        except Exception as e:
            print(f"[GDriveService] Exception during file upload to folder: {e}")
        return "failed"

    def upload_file_to_drive_subfolder(self, local_file_path, subfolder_name, drive_filename=None):
        if not self.is_linked() or not os.path.exists(local_file_path):
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
            
        headers = {"Authorization": f"Bearer {access_token}"}
        parent_id = self._get_or_create_backups_folder(headers)
        if not parent_id:
            return False
            
        subfolder_id = self._get_or_create_subfolder(headers, subfolder_name, parent_id)
        if not subfolder_id:
            return False
            
        status = self._upload_file_to_folder_id(headers, local_file_path, subfolder_id, drive_filename)
        if status == "uploaded":
            print(f"[GDriveService] Successfully uploaded: {drive_filename or os.path.basename(local_file_path)}")
        elif status == "updated":
            print(f"[GDriveService] Successfully updated: {drive_filename or os.path.basename(local_file_path)}")
        elif status == "skipped":
            print(f"[GDriveService] Skipped upload, file size matches: {drive_filename or os.path.basename(local_file_path)}")
            
        return status in ("skipped", "uploaded", "updated")

    def upload_asset_async(self, local_file_path, kind):
        """Asynchronously upload a newly added PDF or image in the background."""
        if not self.is_linked():
            return
        self._upload_queue.put((local_file_path, kind))

    def _uploader_worker_loop(self):
        while True:
            try:
                item = self._upload_queue.get()
                if item is None:
                    break
                local_file_path, kind = item
                if not self.is_linked():
                    self._upload_queue.task_done()
                    continue
                subfolder_name = kind
                self.upload_file_to_drive_subfolder(local_file_path, subfolder_name)
                self._upload_queue.task_done()
            except Exception as e:
                print(f"[GDriveService] Background uploader loop error: {e}")
                time.sleep(1)

    def delete_file_from_drive(self, file_id):
        if not self.is_linked():
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        try:
            r = requests.delete(url, headers=headers, timeout=15)
            if r.status_code in (200, 204):
                print(f"[GDriveService] Deleted file {file_id} from Drive")
                return True
        except Exception as e:
            print(f"[GDriveService] Delete failed for file {file_id}: {e}")
        return False

    def download_file_from_drive(self, file_id, local_dest_path):
        if not self.is_linked():
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        try:
            os.makedirs(os.path.dirname(local_dest_path) or ".", exist_ok=True)
            r = requests.get(url, headers=headers, stream=True, timeout=60)
            if r.status_code == 200:
                with open(local_dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                print(f"[GDriveService] Downloaded file {file_id} to {local_dest_path}")
                return True
            else:
                print(f"[GDriveService] Download failed: {r.status_code} - {r.text}")
        except Exception as e:
            print(f"[GDriveService] Exception during file download: {e}")
        return False

    def list_files_in_folder(self, folder_id):
        if not self.is_linked():
            return []
        access_token = self.get_access_token()
        if not access_token:
            return []
        headers = {"Authorization": f"Bearer {access_token}"}
        query = f"'{folder_id}' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id,name,size,mimeType,createdTime)"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.json().get("files", [])
            elif r.status_code == 404:
                # Invalidate from cache
                print(f"[GDriveService] Folder {folder_id} returned 404, invalidating from cache...")
                keys_to_remove = [k for k, v in self._folder_cache.items() if v == folder_id]
                for k in keys_to_remove:
                    self._folder_cache.pop(k, None)
                self._save_folder_cache()
        except Exception as e:
            print(f"[GDriveService] List files failed for folder {folder_id}: {e}")
        return []

    def sync_referenced_assets(self, local_archive_root, referenced_pdfs, referenced_images):
        if not self.is_linked():
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
            
        headers = {"Authorization": f"Bearer {access_token}"}
        parent_id = self._get_or_create_backups_folder(headers)
        if not parent_id:
            return False
            
        success = True
        self._folder_contents_cache.clear()
        
        all_referenced = []
        for p in referenced_pdfs:
            all_referenced.append((p, "pdfs"))
        for img in referenced_images:
            all_referenced.append((img, "images"))
            
        total_files = len(all_referenced)
        
        # Check local sync cache first without doing any GDrive API call!
        skipped_count = 0
        downloaded_count = 0
        failed_count = 0
        to_check_assets = []
        
        for rel_path, kind in all_referenced:
            rel_path_norm = rel_path.replace("\\", "/")
            local_dest_path = os.path.join(local_archive_root, rel_path_norm)
            local_file_path_norm = os.path.abspath(local_dest_path).replace("\\", "/")
            
            try:
                if os.path.exists(local_dest_path):
                    local_mtime = os.path.getmtime(local_dest_path)
                    local_size = os.path.getsize(local_dest_path)
                    cached = self._sync_cache.get(local_file_path_norm)
                    if cached and cached.get("mtime") == local_mtime and cached.get("size") == local_size and cached.get("drive_file_id"):
                        skipped_count += 1
                        continue
            except Exception:
                pass
            to_check_assets.append((rel_path, kind, local_dest_path, local_file_path_norm))
            
        total_to_check = len(to_check_assets)
        if total_to_check > 0:
            print(f"[GDriveService] Checking and restoring {total_to_check} assets (out of {total_files} total)...")
        else:
            print(f"[GDriveService] All {total_files} assets are already up to date locally.")
            if skipped_count > 0:
                print(f"[GDriveService] Skipped {skipped_count} unchanged files (already up to date locally).")
            return True
        
        for idx, (rel_path, kind, local_dest_path, local_file_path_norm) in enumerate(to_check_assets):
            if total_to_check > 15 and (idx + 1) % 10 == 0:
                print(f"[GDriveService] Progress: Checked {idx + 1}/{total_to_check} assets...")
                
            rel_path_norm = rel_path.replace("\\", "/")
            parts = rel_path_norm.split("/")
            if not parts:
                continue
                
            filename = parts[-1]
            folder_segments = parts[:-1]
            
            cloud_folder_id = self._resolve_gdrive_folder_path(headers, parent_id, folder_segments)
            if not cloud_folder_id:
                print(f"[GDriveService] Could not resolve cloud folder for {rel_path_norm}")
                failed_count += 1
                continue
                
            file_id = self._find_file_in_folder(headers, filename, cloud_folder_id)
            if not file_id:
                print(f"[GDriveService] Referenced file {rel_path_norm} not found on Drive")
                failed_count += 1
                continue
                
            need_download = False
            if not os.path.exists(local_dest_path):
                need_download = True
            else:
                local_size = os.path.getsize(local_dest_path)
                drive_size_str = "0"
                if cloud_folder_id in self._folder_contents_cache and filename in self._folder_contents_cache[cloud_folder_id]:
                    drive_size_str = self._folder_contents_cache[cloud_folder_id][filename].get("size", "0")
                else:
                    url_get = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size"
                    try:
                        r_get = requests.get(url_get, headers=headers, timeout=15)
                        if r_get.status_code == 200:
                            drive_size_str = r_get.json().get("size", "0")
                    except Exception:
                        pass
                
                if int(drive_size_str) != local_size:
                    need_download = True
                    
            if need_download:
                print(f"[GDriveService] Downloading {rel_path_norm}...")
                dl_ok = self.download_file_from_drive(file_id, local_dest_path)
                if not dl_ok:
                    success = False
                    failed_count += 1
                else:
                    downloaded_count += 1
                    try:
                        mtime = os.path.getmtime(local_dest_path)
                        size = os.path.getsize(local_dest_path)
                        self._sync_cache[local_file_path_norm] = {"mtime": mtime, "size": size, "drive_file_id": file_id}
                        self._save_sync_cache()
                    except Exception:
                        pass
            else:
                skipped_count += 1
                try:
                    mtime = os.path.getmtime(local_dest_path)
                    size = os.path.getsize(local_dest_path)
                    self._sync_cache[local_file_path_norm] = {"mtime": mtime, "size": size, "drive_file_id": file_id}
                    self._save_sync_cache()
                except Exception:
                    pass
                
        if skipped_count > 0:
            print(f"[GDriveService] Skipped {skipped_count} unchanged files (already up to date locally).")
        if downloaded_count > 0 or failed_count > 0:
            print(f"[GDriveService] Restore summary: {downloaded_count} downloaded, {failed_count} failed.")
                    
        return success

    def backup_referenced_assets(self, local_archive_root, referenced_pdfs, referenced_images):
        if not self.is_linked():
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
            
        headers = {"Authorization": f"Bearer {access_token}"}
        parent_id = self._get_or_create_backups_folder(headers)
        if not parent_id:
            return False
            
        success = True
        self._folder_contents_cache.clear()
        
        all_referenced = []
        for p in referenced_pdfs:
            all_referenced.append((p, "pdfs"))
        for img in referenced_images:
            all_referenced.append((img, "images"))
            
        total_files = len(all_referenced)
        
        skipped_count = 0
        uploaded_count = 0
        updated_count = 0
        failed_count = 0
        changed_assets = []
        
        # Filter out unchanged files using local sync cache first!
        for rel_path, kind in all_referenced:
            rel_path_norm = rel_path.replace("\\", "/")
            local_file_path = os.path.join(local_archive_root, rel_path_norm)
            
            if not os.path.exists(local_file_path):
                print(f"[GDriveService] Local referenced file {rel_path_norm} not found on disk, skipping backup")
                continue
                
            local_file_path_norm = os.path.abspath(local_file_path).replace("\\", "/")
            try:
                local_mtime = os.path.getmtime(local_file_path)
                local_size = os.path.getsize(local_file_path)
                cached = self._sync_cache.get(local_file_path_norm)
                if cached and cached.get("mtime") == local_mtime and cached.get("size") == local_size:
                    skipped_count += 1
                    continue
            except Exception:
                pass
            changed_assets.append((rel_path, kind, local_file_path))
            
        total_changed = len(changed_assets)
        if total_changed > 0:
            print(f"[GDriveService] Scanning and backing up {total_changed} modified/new assets (out of {total_files} total)...")
        else:
            print(f"[GDriveService] All {total_files} assets are already up to date locally.")
            if skipped_count > 0:
                print(f"[GDriveService] Skipped {skipped_count} unchanged files (already up to date).")
            return True
        
        for idx, (rel_path, kind, local_file_path) in enumerate(changed_assets):
            if total_changed > 15 and (idx + 1) % 10 == 0:
                print(f"[GDriveService] Progress: Checked {idx + 1}/{total_changed} assets...")
                
            rel_path_norm = rel_path.replace("\\", "/")
            parts = rel_path_norm.split("/")
            if not parts:
                continue
                
            filename = parts[-1]
            folder_segments = parts[:-1]
            
            cloud_folder_id = self._resolve_gdrive_folder_path(headers, parent_id, folder_segments)
            if not cloud_folder_id:
                print(f"[GDriveService] Could not resolve cloud folder for {rel_path_norm}")
                success = False
                failed_count += 1
                continue
                
            status = self._upload_file_to_folder_id(headers, local_file_path, cloud_folder_id, filename)
            if status == "skipped":
                skipped_count += 1
            elif status == "uploaded":
                print(f"[GDriveService] Uploaded new file: {rel_path_norm}")
                uploaded_count += 1
            elif status == "updated":
                print(f"[GDriveService] Updated modified file: {rel_path_norm}")
                updated_count += 1
            else:
                success = False
                failed_count += 1
                
        if skipped_count > 0:
            print(f"[GDriveService] Skipped {skipped_count} unchanged files (sizes matched on Drive).")
        if uploaded_count > 0 or updated_count > 0 or failed_count > 0:
            print(f"[GDriveService] Backup summary: {uploaded_count} uploaded, {updated_count} updated, {failed_count} failed.")
            
        return success

    def _recursive_list_and_prune(self, headers, cloud_folder_id, local_path_prefix, active_rel_paths, visited=None):
        if visited is None:
            visited = set()
            
        if cloud_folder_id in visited:
            print(f"[GDriveService] Circular reference or duplicate folder {cloud_folder_id} detected, skipping recursion")
            return
        visited.add(cloud_folder_id)
        
        query = f"'{cloud_folder_id}' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id,name,mimeType)"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                items = r.json().get("files", [])
                for item in items:
                    item_name = item.get("name")
                    item_id = item.get("id")
                    item_mime = item.get("mimeType")
                    
                    if item_mime == "application/vnd.google-apps.folder":
                        new_prefix = f"{local_path_prefix}/{item_name}" if local_path_prefix else item_name
                        self._recursive_list_and_prune(headers, item_id, new_prefix, active_rel_paths, visited)
                    else:
                        file_rel_path = f"{local_path_prefix}/{item_name}"
                        if file_rel_path not in active_rel_paths:
                            print(f"[GDriveService] Pruning unreferenced cloud file: {file_rel_path}")
                            self.delete_file_from_drive(item_id)
        except Exception as e:
            print(f"[GDriveService] Error during recursive pruning of {local_path_prefix}: {e}")

    def prune_unreferenced_assets(self, referenced_pdfs, referenced_images):
        if not self.is_linked():
            return False
        access_token = self.get_access_token()
        if not access_token:
            return False
            
        headers = {"Authorization": f"Bearer {access_token}"}
        parent_id = self._get_or_create_backups_folder(headers)
        if not parent_id:
            return False
            
        # Compile active relative paths
        active_rel_paths = set()
        for p in referenced_pdfs:
            active_rel_paths.add(p.replace("\\", "/"))
        for img in referenced_images:
            active_rel_paths.add(img.replace("\\", "/"))
            
        # Prune pdfs subfolder
        pdfs_folder_id = self._get_or_create_subfolder(headers, "pdfs", parent_id)
        if pdfs_folder_id:
            self._recursive_list_and_prune(headers, pdfs_folder_id, "pdfs", active_rel_paths)
            
        # Prune images subfolder
        images_folder_id = self._get_or_create_subfolder(headers, "images", parent_id)
        if images_folder_id:
            self._recursive_list_and_prune(headers, images_folder_id, "images", active_rel_paths)
            
        return True


# Singleton instance
gdrive_store = GDriveService()
