"""One capture tick: detect active window, screenshot it, record in DB.

This module is platform-agnostic — all OS calls go through `platform.platform`.
The daemon (daemon.py) calls `capture_once()` on a loop; the manual-hotkey
flow (Phase 5) calls `capture_manual()` with a note + tags.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .db import transaction
from .platform import platform
from .platform.base import ActiveWindow
from .uploader import enqueue

log = logging.getLogger(__name__)

# Filesystem-safe filename sanitizer.
# Chars unsafe on Windows: < > : " / \ | ? *  plus ASCII control chars (0x00-0x1F).
# Chars unsafe on macOS: : and / (mostly). Strip both sets to be safe everywhere.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Cap basename length: macOS allows 255 bytes per filename component, but very
# long tab titles ("Slack | #general | Acme Inc | ...") make the filesystem
# unpleasant to browse manually. 80 chars is plenty.
_MAX_BASENAME_LEN = 80


def _sanitize(text: str) -> str:
    """Make `text` safe to use as a filename component.

    - replace unsafe chars with `_`
    - collapse whitespace
    - trim leading/trailing dots, spaces, underscores (Windows hates trailing dots)
    - cap length so the final filename doesn't exceed FS limits
    """
    cleaned = _UNSAFE_FILENAME.sub("_", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if len(cleaned) > _MAX_BASENAME_LEN:
        cleaned = cleaned[:_MAX_BASENAME_LEN].rstrip(" ._")
    return cleaned or "untitled"


def _build_filename(app_name: str, tab_title: str | None, ts: datetime) -> str:
    """`{AppName|TabTitle}_{YYYY-MM-DD_HH-MM-SS}.png` per the spec.

    Browser tabs win over app name when present — that's more informative.
    """
    label = _sanitize(tab_title) if tab_title else _sanitize(app_name)
    stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{label}_{stamp}.png"


def _month_partition_dir(ts: datetime) -> Path:
    """`<screenshots_dir>/YYYY-MM/` — created on demand."""
    folder = platform.screenshots_dir / ts.strftime("%Y-%m")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _insert_screenshot(
    ts: datetime,
    app_name: str,
    tab_title: str | None,
    local_path: Path,
    *,
    is_manual: bool = False,
    activity_note: str | None = None,
    tags: str | None = None,
    enqueue_upload: bool = False,
) -> int:
    """Insert a row into `screenshots` with `upload_status='pending'`. Returns row id.

    When `enqueue_upload` is set (Drive sync on), an `upload_queue` row is added
    in the SAME transaction so the screenshot and its pending upload commit
    atomically.
    """
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO screenshots (
                timestamp, app_name, tab_title, local_path,
                upload_status, is_manual, activity_note, tags
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?);
            """,
            (
                ts.isoformat(timespec="seconds"),
                app_name,
                tab_title,
                str(local_path),
                1 if is_manual else 0,
                activity_note,
                tags,
            ),
        )
        row_id = int(cur.lastrowid)
        if enqueue_upload:
            enqueue(conn, row_id, ts.isoformat(timespec="seconds"))
        return row_id


def _capture(
    cfg: Config,
    *,
    is_manual: bool,
    activity_note: str | None = None,
    tags: str | None = None,
    active: ActiveWindow | None = None,
) -> int | None:
    """Shared capture path: detect window, screenshot, insert row. Returns row id.

    `active` lets the caller pass the foreground window detected *earlier* — the
    manual-capture path does this so the note/tags dialog (which steals focus)
    doesn't make us record the dialog ("osascript") as the active app. When None
    we detect it here, which is correct for the automatic loop.

    Failures (e.g. Screen Recording permission not granted) are logged but not
    raised — the daemon loop must keep running.
    """
    try:
        ts = datetime.now(timezone.utc)
        if active is None:
            active = platform.get_active_window(cfg.browsers)
        filename = _build_filename(active.app_name, active.tab_title, ts)
        dest = _month_partition_dir(ts) / filename
        platform.capture_screenshot(dest)
        row_id = _insert_screenshot(
            ts,
            app_name=active.app_name,
            tab_title=active.tab_title,
            local_path=dest,
            is_manual=is_manual,
            activity_note=activity_note,
            tags=tags,
            enqueue_upload=cfg.drive_connected,
        )
        log.info("%s #%d: %s", "manual capture" if is_manual else "captured", row_id, dest.name)
        return row_id
    except Exception:
        log.exception("%s tick failed", "manual capture" if is_manual else "capture")
        return None


def capture_once(cfg: Config) -> int | None:
    """Do one automatic capture tick. Returns the new screenshot row id, or None."""
    return _capture(cfg, is_manual=False)


def capture_manual(
    cfg: Config,
    note: str | None = None,
    tags: str | None = None,
    active: ActiveWindow | None = None,
) -> int | None:
    """Capture triggered by the hotkey, tagged manual with an optional note + tags.

    Pass `active` (the window detected before the note dialog opened) so the row
    records the real foreground app, not the dialog.
    """
    return _capture(cfg, is_manual=True, activity_note=note, tags=tags, active=active)
