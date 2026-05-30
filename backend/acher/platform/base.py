"""Abstract platform interface.

Each OS module (mac.py, windows.py) subclasses `Platform` and implements every
method. Methods that don't make sense until a later phase raise
`NotImplementedError` for now; they'll be filled in when that phase lands.

Keeping the full surface listed here (rather than growing it phase by phase)
makes the contract obvious — anyone reading this file sees exactly what each
platform module owes the rest of the system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ActiveWindow:
    """One snapshot of what the user is currently looking at.

    `tab_title` is None when the active app is not a tracked browser, or when
    the browser has no open window. `app_name` is always populated.
    """

    app_name: str
    tab_title: str | None


class Platform(ABC):
    """Contract every OS implementation must satisfy."""

    # ----- paths (Phase 1) -----

    @property
    @abstractmethod
    def app_data_dir(self) -> Path:
        """Root dir for Acher's local state.

        macOS:   ~/Library/Application Support/Acher/
        Windows: %APPDATA%\\Acher\\

        Subdirs: screenshots/, db file, token.json, logs.
        Created on first access.
        """

    @property
    def screenshots_dir(self) -> Path:
        """Where screenshot PNGs are stored, partitioned by YYYY-MM."""
        return self.app_data_dir / "screenshots"

    @property
    def db_path(self) -> Path:
        """SQLite file path."""
        return self.app_data_dir / "acher.db"

    @property
    def log_path(self) -> Path:
        """Upload errors + daemon log file."""
        return self.app_data_dir / "acher.log"

    @property
    def token_path(self) -> Path:
        """Cached Google Drive OAuth token (Phase 3). Never in the repo."""
        return self.app_data_dir / "token.json"

    # ----- capture (Phase 2) -----

    @abstractmethod
    def capture_screenshot(self, dest: Path) -> None:
        """Save a screenshot of the primary display to `dest` (PNG)."""

    @abstractmethod
    def get_active_window(self, tracked_browsers: list[str]) -> ActiveWindow:
        """Return the foreground app and (if it's a tracked browser) its tab title.

        `tracked_browsers` is the user's enabled-browsers list from config.
        Implementations should only attempt tab-title detection for apps in
        this list — it's the expensive call.
        """

    # ----- manual capture (Phase 5) -----

    @abstractmethod
    def prompt_manual_note(self) -> tuple[str, str] | None:
        """Pop a native dialog asking for an activity note + tags.

        Returns `(note, tags)` (either may be ""), or `None` if the user
        cancelled — in which case the caller must abort the manual capture.
        Runs on the hotkey-listener thread, so it must not touch the main loop.
        """

    # ----- auto-start (Phase 9) -----

    @abstractmethod
    def install_autostart(self, daemon_command: list[str]) -> Path:
        """Install login-launch hook. Returns the path of the file we wrote.

        Must be idempotent — calling twice is safe.
        Must NOT be called without explicit user approval (spec stop condition).
        """

    @abstractmethod
    def uninstall_autostart(self) -> None:
        """Remove the login-launch hook. Safe to call when nothing is installed."""
