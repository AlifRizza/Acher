"""Windows implementation of the Platform interface.

Phase 2 lands here:
- `capture_screenshot` — `mss` grabs the primary monitor, `Pillow` writes PNG.
- `get_active_window` — `win32gui.GetForegroundWindow()` -> process id ->
  `psutil.Process(pid).name()` for the app name. For Chrome/Brave, walk the
  window's UI Automation tree to find the active tab and read its name.

Phase 9 (`install_autostart` / `uninstall_autostart`) is still a stub.

Notes:
- Arc on Windows is in beta as of 2026; tab detection is not implemented
  yet because its UI Automation patterns aren't stable. The app is still
  detected and recorded, just without a tab title.
- This file imports `mss`, `pywin32`, `psutil`, `uiautomation` lazily inside
  methods so the module is importable on macOS (lets us write cross-platform
  tests).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import ActiveWindow, Platform

log = logging.getLogger(__name__)

# Maps short browser names from config.json to (process_exe_name, ui_automation_supported).
# Process names are matched case-insensitively against psutil's `Process.name()`.
_BROWSER_PROCESS_REGISTRY: dict[str, tuple[str, bool]] = {
    "Chrome":  ("chrome.exe",  True),
    "Brave":   ("brave.exe",   True),
    "Edge":    ("msedge.exe",  True),     # not in user's tracked list; here for completeness
    "Arc":     ("arc.exe",     False),    # Arc Windows beta — UIA tree unstable
    "Firefox": ("firefox.exe", False),    # UIA accessible but ad-hoc; skip for now
}


class WindowsPlatform(Platform):
    @property
    def app_data_dir(self) -> Path:
        # %APPDATA% is the standard per-user, per-app config root. Falls back
        # to ~/AppData/Roaming if the env var is missing (rare on Windows).
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / "Acher"
        else:
            path = Path.home() / "AppData" / "Roaming" / "Acher"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ----- Phase 2: capture -----

    def capture_screenshot(self, dest: Path) -> None:
        """Save a PNG of the primary monitor to `dest` using mss + Pillow.

        mss uses BitBlt under the hood — significantly faster than alternatives
        like PIL.ImageGrab. monitors[1] is the primary display; monitors[0] is
        the union of all monitors which is rarely what the user wants on
        multi-display setups.
        """
        import mss
        from PIL import Image

        dest.parent.mkdir(parents=True, exist_ok=True)
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(dest, "PNG", optimize=False)

    def get_active_window(self, tracked_browsers: list[str]) -> ActiveWindow:
        """Foreground app name (always) + tab title (if app is a UIA-supported
        tracked browser)."""
        hwnd, _pid, app_name = _foreground_window_info()
        if app_name is None:
            return ActiveWindow(app_name="(unknown)", tab_title=None)

        tab_title = _tab_title_for_browser(hwnd, app_name, tracked_browsers)
        return ActiveWindow(app_name=app_name, tab_title=tab_title)

    # ----- activity / presence -----

    def get_idle_seconds(self) -> float:
        """Seconds since last input via GetLastInputInfo. 0.0 on failure."""
        return _win_idle_seconds()

    def is_screen_locked(self) -> bool:
        """True if the workstation is locked or the session is not active.

        Detected by checking for an open desktop input handle: when the screen
        is locked the foreground/input desktop can't be opened by our process.
        """
        return _win_is_locked()

    # ----- Phase 5: manual capture -----

    def prompt_manual_note(self) -> tuple[str, str] | None:
        """Ask for a note then tags via two VB InputBox dialogs (PowerShell).

        Cancelling the note dialog aborts the capture (returns None).
        Cancelling the tags dialog keeps the note with empty tags.
        """
        note = _input_box("Activity note for this screenshot:", "Acher - Manual Capture")
        if note is None:
            return None
        tags = _input_box("Tags (comma-separated, optional):", "Acher - Manual Capture")
        return (note, tags or "")

    # ----- Phase 9: autostart (Registry Run key) -----

    def install_autostart(self, daemon_command: list[str]) -> Path:
        """Add a HKCU Run entry so `daemon_command` runs at login.

        Idempotent: overwrites any existing value. Returns a pseudo-path naming
        the registry value (there's no file, but the interface promises a Path).
        """
        import winreg

        command = _quote_command(daemon_command)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
        log.info("set HKCU Run entry %s = %s", _RUN_VALUE_NAME, command)
        return Path(f"HKCU\\{_RUN_KEY}\\{_RUN_VALUE_NAME}")

    def uninstall_autostart(self) -> None:
        """Remove the HKCU Run entry. Safe if it doesn't exist."""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
            log.info("removed HKCU Run entry %s", _RUN_VALUE_NAME)
        except FileNotFoundError:
            pass  # nothing installed; nothing to do


# ---------- helpers ----------

# Standard per-user autostart location on Windows.
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "Acher"


def _quote_command(daemon_command: list[str]) -> str:
    """Join argv into a single command string, quoting args that contain spaces.

    The Run key stores one string, not an argv array, so paths with spaces
    (e.g. "C:\\Program Files\\...") must be double-quoted.
    """
    parts = []
    for arg in daemon_command:
        parts.append(f'"{arg}"' if " " in arg else arg)
    return " ".join(parts)


def _input_box(prompt: str, title: str) -> str | None:
    """Show a VB InputBox via PowerShell. Returns text, or None if cancelled.

    InputBox returns "" on Cancel AND on an empty-but-OK entry; they're
    indistinguishable, so we treat a literal Cancel via a sentinel: we wrap the
    call so a cancelled box prints the sentinel and an OK box prints the text.
    """
    import subprocess

    sentinel = "\x00ACHER_CANCEL\x00"
    ps = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        f"$r = [Microsoft.VisualBasic.Interaction]::InputBox('{_ps_quote(prompt)}',"
        f"'{_ps_quote(title)}','');"
        # InputBox can't distinguish Cancel from empty-OK; an empty result is
        # treated as Cancel for the note (caller aborts) — acceptable: a manual
        # capture with no note and the user pressing Cancel are the same intent.
        f"if ([string]::IsNullOrEmpty($r)) {{ Write-Output '{sentinel}' }} else {{ Write-Output $r }}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.debug("manual-note InputBox failed/timed out")
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.decode(errors="replace").rstrip("\r\n")
    return None if out == sentinel else out


def _ps_quote(text: str) -> str:
    """Escape a string for embedding inside a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def _win_idle_seconds() -> float:
    """Seconds since the last input via the Win32 GetLastInputInfo API.

    Uses ctypes so it needs no extra dependency. Returns 0.0 on any failure
    (treated as active — fail-open).
    """
    try:
        import ctypes

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:  # pragma: no cover — non-Windows / API failure
        log.debug("GetLastInputInfo failed", exc_info=True)
        return 0.0


def _win_is_locked() -> bool:
    """True if the workstation is locked.

    OpenInputDesktop fails when the secure (lock) desktop is active, so an
    inability to open the input desktop is a reliable lock signal. Returns False
    on failure (fail-open).
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # DESKTOP_SWITCHDESKTOP = 0x0100
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if not hdesk:
            return True  # can't open input desktop → locked
        user32.CloseDesktop(hdesk)
        return False
    except Exception:  # pragma: no cover — non-Windows / API failure
        log.debug("OpenInputDesktop check failed", exc_info=True)
        return False


def _foreground_window_info() -> tuple[int, int, str | None]:
    """Returns (hwnd, pid, process_exe_name) for the current foreground window.

    `process_exe_name` is the basename of the EXE (e.g. "chrome.exe"). Returns
    None for the third element if anything fails — caller falls back to
    "(unknown)".
    """
    try:
        import psutil
        import win32gui
        import win32process
    except ImportError:  # pragma: no cover — only on non-Windows
        log.warning("win32gui / psutil not available; cannot detect foreground window")
        return 0, 0, None

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return 0, 0, None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return hwnd, 0, None
        name = psutil.Process(pid).name()
        return hwnd, pid, name
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        # AccessDenied happens for elevated processes when Acher itself is not
        # elevated — documented in docs/permissions-setup.md.
        log.debug("foreground process lookup failed: %s", exc)
        return 0, 0, None
    except Exception:
        log.exception("unexpected error reading foreground window")
        return 0, 0, None


def _tab_title_for_browser(hwnd: int, process_name: str, tracked_browsers: list[str]) -> str | None:
    """If the foreground process is a UIA-supported tracked browser, walk its
    window tree and return the active tab's name. Returns None otherwise.

    UI Automation lookups can be slow (50-200 ms). We only do them for known
    browsers in the user's config — never on a tick where the foreground app
    is something else.
    """
    process_lc = process_name.lower()
    match = next(
        (
            (short, exe, supported)
            for short, (exe, supported) in _BROWSER_PROCESS_REGISTRY.items()
            if short in tracked_browsers and exe.lower() == process_lc
        ),
        None,
    )
    if match is None or not match[2]:
        return None  # not a tracked browser, or browser doesn't support UIA detection

    try:
        import uiautomation as auto
    except ImportError:  # pragma: no cover
        log.warning("uiautomation not available; cannot detect browser tab")
        return None

    try:
        # ControlFromHandle wraps the window's UIA element. Chromium browsers
        # expose the tab strip as a TabControl; the selected tab is the one
        # whose SelectionItemPattern reports IsSelected == True.
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            return None
        tab_strip = window.TabControl()
        if not tab_strip.Exists(0.2):
            return None
        for child in tab_strip.GetChildren():
            pattern = getattr(child, "GetSelectionItemPattern", lambda: None)()
            if pattern is not None and getattr(pattern, "IsSelected", False):
                return child.Name or None
        return None
    except Exception:
        # UIA can throw various COMError variants. None of them should crash
        # the daemon — just skip the tab title this tick.
        log.debug("UIA tab lookup failed for %s", process_name, exc_info=True)
        return None
