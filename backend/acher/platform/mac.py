"""macOS implementation of the Platform interface.

Phase 2 lands here:
- `capture_screenshot` — `/usr/sbin/screencapture -x -t png <dest>`
- `get_active_window` — `NSWorkspace.frontmostApplication()` for the app name;
  AppleScript via `/usr/bin/osascript` for the active tab title of Chromium
  browsers (Chrome, Arc, Brave).

Phase 9 (`install_autostart` / `uninstall_autostart`) is still a stub.

Permissions the user must grant manually (documented in docs/permissions-setup.md):
- Screen Recording: required for `screencapture` to produce non-blank PNGs.
- Automation: required for `osascript tell application "Google Chrome"...`
  AppleScript control. macOS prompts on first use; subsequent runs reuse the
  grant. AppleScript control of System Events does NOT need Accessibility
  for our usage — NSWorkspace is enough for the frontmost app.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .base import ActiveWindow, Platform

log = logging.getLogger(__name__)

# Maps the short browser names from config.json to the (macOS_app_name,
# AppleScript_target). Most Chromium-based browsers share the same AppleScript
# dictionary; Safari uses different terminology.
_BROWSER_REGISTRY: dict[str, tuple[str, str, str]] = {
    # config_name : (mac_app_name_from_NSWorkspace, applescript_target, applescript_command)
    "Chrome": (
        "Google Chrome",
        "Google Chrome",
        'tell application "Google Chrome" to get title of active tab of front window',
    ),
    "Arc": (
        "Arc",
        "Arc",
        'tell application "Arc" to get title of active tab of front window',
    ),
    "Brave": (
        "Brave Browser",
        "Brave Browser",
        'tell application "Brave Browser" to get title of active tab of front window',
    ),
    "Safari": (
        "Safari",
        "Safari",
        'tell application "Safari" to get name of current tab of front window',
    ),
    # Firefox barely supports AppleScript — leave it out for now; falls through
    # to "no tab title detected".
}

# `osascript` can hang if a permission dialog is on screen or AppleScript is
# misbehaving. 2 seconds is plenty for a one-line tab-title query.
_OSASCRIPT_TIMEOUT_SEC = 2.0


class MacPlatform(Platform):
    @property
    def app_data_dir(self) -> Path:
        # Standard macOS location for per-app user state. Always writable
        # without elevation.
        path = Path.home() / "Library" / "Application Support" / "Acher"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ----- Phase 2: capture -----

    def capture_screenshot(self, dest: Path) -> None:
        """Capture the primary display to `dest` as PNG.

        Uses the built-in `screencapture` CLI:
            -x   silent (no shutter sound)
            -t   output format
            -C   capture the cursor too (off by default)  — we omit; cursor noise

        Requires Screen Recording permission (System Settings → Privacy &
        Security → Screen Recording → Terminal/Python). Without it, the PNG
        is produced but contains only the wallpaper.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        # capture_output=True so the daemon log doesn't get polluted by
        # screencapture's stdout (it prints nothing useful on success).
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-t", "png", str(dest)],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"screencapture failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace').strip()}"
            )

    def get_active_window(self, tracked_browsers: list[str]) -> ActiveWindow:
        """Foreground app name (always) + tab title (if app is a tracked browser).

        We use NSWorkspace for the app name (fast, no subprocess) and only
        spawn `osascript` when the frontmost app matches a tracked browser.
        """
        app_name = _frontmost_app_name()
        if not app_name:
            return ActiveWindow(app_name="(unknown)", tab_title=None)

        tab_title = _tab_title_for_app(app_name, tracked_browsers)
        return ActiveWindow(app_name=app_name, tab_title=tab_title)

    # ----- activity / presence -----

    def get_idle_seconds(self) -> float:
        """Seconds since last input via Quartz CGEventSource. 0.0 on failure."""
        return _quartz_idle_seconds()

    def is_screen_locked(self) -> bool:
        """True if the screen is locked or display asleep (Quartz session dict)."""
        return _screen_is_locked()

    # ----- Phase 5: manual capture -----

    def prompt_manual_note(self) -> tuple[str, str] | None:
        """Ask for a note then tags via two `osascript` text dialogs.

        Cancelling the note dialog aborts the whole capture (returns None).
        Cancelling the tags dialog keeps the note with empty tags.
        """
        note = _text_dialog("Activity note for this screenshot:", "Acher — Manual Capture")
        if note is None:
            return None  # user cancelled — abort capture
        tags = _text_dialog("Tags (comma-separated, optional):", "Acher — Manual Capture")
        return (note, tags or "")

    # ----- Phase 9: autostart (launchd) -----

    def install_autostart(self, daemon_command: list[str]) -> Path:
        """Write a LaunchAgent plist so `daemon_command` runs at login.

        Idempotent: overwrites any existing plist. Loads it into the current
        session with `launchctl` so it starts without a re-login (best effort —
        a load failure is logged, not raised, since the plist is still valid for
        the next login).
        """
        plist_path = _launch_agent_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(_render_plist(daemon_command), encoding="utf-8")
        log.info("wrote LaunchAgent: %s", plist_path)

        # Reload: bootout then bootstrap so a changed command takes effect.
        subprocess.run(
            ["/bin/launchctl", "bootout", f"gui/{_uid()}/{_LAUNCH_AGENT_LABEL}"],
            capture_output=True, check=False,
        )
        result = subprocess.run(
            ["/bin/launchctl", "bootstrap", f"gui/{_uid()}", str(plist_path)],
            capture_output=True, check=False,
        )
        if result.returncode != 0:
            log.warning(
                "launchctl bootstrap failed (plist is still installed for next login): %s",
                result.stderr.decode(errors="replace").strip(),
            )
        return plist_path

    def uninstall_autostart(self) -> None:
        """Unload and delete the LaunchAgent plist. Safe if nothing is installed."""
        plist_path = _launch_agent_path()
        subprocess.run(
            ["/bin/launchctl", "bootout", f"gui/{_uid()}/{_LAUNCH_AGENT_LABEL}"],
            capture_output=True, check=False,
        )
        plist_path.unlink(missing_ok=True)
        log.info("removed LaunchAgent: %s", plist_path)


# Reverse-DNS label for the LaunchAgent — also its plist filename stem.
_LAUNCH_AGENT_LABEL = "id.acher.daemon"


def _launch_agent_path() -> Path:
    """Path to Acher's per-user LaunchAgent plist."""
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCH_AGENT_LABEL}.plist"


def _uid() -> int:
    """Current user's uid, for `launchctl` gui/<uid> domain targeting."""
    return os.getuid()


def _render_plist(daemon_command: list[str]) -> str:
    """Render a LaunchAgent plist that runs `daemon_command` at login.

    RunAtLoad starts it on login; KeepAlive restarts it if it crashes. stdout/
    stderr go to the app-data dir so launchd-managed runs are debuggable.
    """
    from xml.sax.saxutils import escape

    args_xml = "\n".join(f"        <string>{escape(arg)}</string>" for arg in daemon_command)
    log_dir = Path.home() / "Library" / "Application Support" / "Acher"
    out_log = escape(str(log_dir / "launchd.out.log"))
    err_log = escape(str(log_dir / "launchd.err.log"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{out_log}</string>
    <key>StandardErrorPath</key>
    <string>{err_log}</string>
</dict>
</plist>
"""


def _text_dialog(prompt: str, title: str) -> str | None:
    """Show a one-field text dialog via osascript. Returns text, or None if cancelled.

    `display dialog` exits non-zero (code 1, "User canceled") when the user
    clicks Cancel — we map that to None. On OK it prints the entered text.
    """
    script = (
        f'display dialog {_as_str(prompt)} with title {_as_str(title)} '
        'default answer "" buttons {"Cancel", "Save"} default button "Save"\n'
        "return text returned of result"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            timeout=120,  # the user may take a while to type
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.debug("manual-note dialog timed out")
        return None
    if result.returncode != 0:
        return None  # cancelled or AppleScript error
    return result.stdout.decode(errors="replace").rstrip("\n")


def _as_str(text: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------- helpers (module-level so we don't pay import cost at class scope) ----------


# Quartz event type for "any input" — CGEventSourceSecondsSinceLastEventType
# with this constant returns seconds since the last keyboard OR mouse event.
_K_CG_ANY_INPUT_EVENT_TYPE = 0xFFFFFFFF  # kCGAnyInputEventType
_K_CG_EVENT_SOURCE_STATE_COMBINED = 0  # kCGEventSourceStateCombinedSessionState


def _quartz_idle_seconds() -> float:
    """Seconds since the last input event, via Quartz. 0.0 if unavailable.

    Lazy import so the module stays importable where pyobjc-Quartz is absent;
    on failure we return 0.0 (treated as "active" — fail-open, never wrongly
    pause capture).
    """
    try:
        from Quartz import (  # type: ignore
            CGEventSourceSecondsSinceLastEventType,
        )
    except ImportError:  # pragma: no cover — only on misconfigured installs
        return 0.0
    try:
        return float(
            CGEventSourceSecondsSinceLastEventType(
                _K_CG_EVENT_SOURCE_STATE_COMBINED, _K_CG_ANY_INPUT_EVENT_TYPE
            )
        )
    except Exception:
        log.debug("Quartz idle query failed", exc_info=True)
        return 0.0


def _screen_is_locked() -> bool:
    """True if the screen is locked or the display is asleep.

    Reads the current session dictionary; `CGSSessionScreenIsLocked` is set when
    the lock screen is up. We also treat display-asleep as locked. On failure we
    return False (fail-open — keep capturing rather than silently going dark).
    """
    try:
        from Quartz import CGSessionCopyCurrentDictionary  # type: ignore
    except ImportError:  # pragma: no cover
        return False
    try:
        session = CGSessionCopyCurrentDictionary()
        if not session:
            return False
        # Value is 1 when locked. Key absent when unlocked.
        return bool(session.get("CGSSessionScreenIsLocked", 0))
    except Exception:
        log.debug("Quartz session query failed", exc_info=True)
        return False


def _frontmost_app_name() -> str | None:
    """Returns the localized name of the frontmost app, or None on failure.

    Pyobjc import is lazy so this module can still be unit-tested on a host
    where pyobjc isn't installed.
    """
    try:
        from AppKit import NSWorkspace  # type: ignore
    except ImportError:  # pragma: no cover — only on misconfigured installs
        log.warning("AppKit (pyobjc) not available; cannot detect frontmost app")
        return None

    workspace = NSWorkspace.sharedWorkspace()
    app = workspace.frontmostApplication()
    if app is None:
        return None
    name = app.localizedName()
    return str(name) if name else None


def _tab_title_for_app(mac_app_name: str, tracked_browsers: list[str]) -> str | None:
    """If `mac_app_name` is one of the user's tracked browsers, return its active
    tab title via AppleScript. Returns None for non-browser apps or on AppleScript
    failure (e.g. browser has no open window, permission denied).
    """
    # Find the registry entry whose first tuple element matches the OS-reported
    # app name AND whose short name is in the user's tracked-browsers config.
    entry = next(
        (
            (short, reg)
            for short, reg in _BROWSER_REGISTRY.items()
            if short in tracked_browsers and reg[0] == mac_app_name
        ),
        None,
    )
    if entry is None:
        return None

    _, (_, _, applescript) = entry
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", applescript],
            capture_output=True,
            timeout=_OSASCRIPT_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.debug("osascript timed out for %s", mac_app_name)
        return None

    if result.returncode != 0:
        # First-run will fail with `errAEEventNotPermitted (-1743)` until the
        # user clicks "OK" on the Automation permission prompt. Log at DEBUG —
        # it's noisy at INFO.
        log.debug(
            "osascript failed for %s: %s",
            mac_app_name,
            result.stderr.decode(errors="replace").strip(),
        )
        return None

    title = result.stdout.decode(errors="replace").strip()
    return title or None
