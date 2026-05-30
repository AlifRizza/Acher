"""Google Drive v3 client + OAuth 2.0 desktop flow.

Optional feature: Drive sync is additive, never required. The google libraries
are an optional extra — install with `pip install -e ".[drive]"`. All google
imports are lazy so the rest of the app (and the test suite) runs without them.

Auth model:
- A Google Cloud OAuth "Desktop app" client. Its id/secret come from the
  environment (`.env`: GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET).
- `DriveClient.authorize()` runs the interactive consent flow once and caches
  the refresh token at `platform.token_path` (app-data dir, never the repo).
- `DriveClient()` thereafter loads + refreshes that token silently.

Scope is `drive.file` (least privilege): the app only ever sees files it created.

Files are uploaded into  <root folder> / YYYY-MM /  mirroring the local layout.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from .platform import platform

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ROOT_FOLDER_NAME = "Acher Screenshots"
_FOLDER_MIME = "application/vnd.google-apps.folder"

_INSTALL_HINT = 'Google Drive sync needs extra deps. Install with: pip install -e ".[drive]"'


def _load_dotenv() -> None:
    """Best-effort load of project-root `.env` into os.environ (no overwrite).

    Tiny by design — avoids a python-dotenv dependency for two variables.
    Real environment variables always win over the file.
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _client_config() -> dict:
    """Build the OAuth 'installed app' client config from the environment."""
    _load_dotenv()
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set. "
            "See docs/drive-setup.md."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


class DriveClient:
    """Thin wrapper over the Drive v3 API for our one use case: upload a PNG."""

    def __init__(self, token_path: Path | None = None) -> None:
        self._token_path = token_path or platform.token_path
        self._service = None
        self._folder_ids: dict[str, str] = {}  # cache: folder cache-key -> id

    # ---- auth ----

    @classmethod
    def authorize(cls, token_path: Path | None = None) -> Path:
        """Run the interactive OAuth flow and cache the token. Returns its path.

        Opens a browser for consent (desktop flow via a transient localhost
        server). Call once during setup (`acher auth`).
        """
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as e:
            raise RuntimeError(_INSTALL_HINT) from e

        dest = token_path or platform.token_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
        creds = flow.run_local_server(port=0)
        dest.write_text(creds.to_json(), encoding="utf-8")
        log.info("Drive token saved to %s", dest)
        return dest

    def _creds(self):
        """Load cached creds, refreshing if expired. Raises if not authorized."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as e:
            raise RuntimeError(_INSTALL_HINT) from e

        if not self._token_path.exists():
            raise RuntimeError(
                f"No Drive token at {self._token_path}. Run `acher auth` first."
            )
        creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _svc(self):
        if self._service is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as e:
                raise RuntimeError(_INSTALL_HINT) from e
            self._service = build(
                "drive", "v3", credentials=self._creds(), cache_discovery=False
            )
        return self._service

    # ---- folders ----

    def _find_or_create_folder(self, name: str, parent_id: str | None) -> str:
        cache_key = f"{parent_id or 'root'}/{name}"
        if cache_key in self._folder_ids:
            return self._folder_ids[cache_key]

        svc = self._svc()
        # Escape single quotes in the name for the Drive query language.
        safe = name.replace("'", "\\'")
        q = f"name = '{safe}' and mimeType = '{_FOLDER_MIME}' and trashed = false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        found = (
            svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
        )
        if found:
            folder_id = found[0]["id"]
        else:
            body = {"name": name, "mimeType": _FOLDER_MIME}
            if parent_id:
                body["parents"] = [parent_id]
            folder_id = svc.files().create(body=body, fields="id").execute()["id"]

        self._folder_ids[cache_key] = folder_id
        return folder_id

    def _month_folder_id(self, ts: datetime) -> str:
        """`<ROOT_FOLDER_NAME>/YYYY-MM` folder id, creating folders as needed."""
        root_id = self._find_or_create_folder(ROOT_FOLDER_NAME, None)
        return self._find_or_create_folder(ts.strftime("%Y-%m"), root_id)

    # ---- upload ----

    def upload(self, local_path: Path, remote_name: str, ts: datetime) -> str:
        """Upload `local_path` as `remote_name` into the month folder. Returns file id."""
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as e:
            raise RuntimeError(_INSTALL_HINT) from e

        folder_id = self._month_folder_id(ts)
        media = MediaFileUpload(str(local_path), mimetype="image/png", resumable=False)
        created = (
            self._svc()
            .files()
            .create(
                body={"name": remote_name, "parents": [folder_id]},
                media_body=media,
                fields="id",
            )
            .execute()
        )
        return created["id"]
