"""Retention / cleanup job (Phase 6).

Deletes screenshots older than the configured retention window — both the PNG
on disk and the DB row. The `upload_queue` row (if any) goes with it via the
`ON DELETE CASCADE` foreign key in the schema.

`retention_period` comes from config: one of `1_week`, `1_month`, `3_months`,
`6_months`, or `never`. `never` disables cleanup entirely.

Design:
- One pass = `purge_once(cfg)`: compute the cutoff, find rows older than it,
  delete each PNG then its row. File deletion failures are logged but don't
  stop the row from being removed — a missing/locked file shouldn't wedge
  retention forever.
- The daemon runs a `RetentionWorker` thread that purges on startup then once
  per day. Cleanup is not time-critical, so a coarse interval is fine.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .db import transaction

log = logging.getLogger(__name__)

# Maps config `retention_period` to a window length. `never` -> None (no cleanup).
_RETENTION_WINDOWS: dict[str, timedelta | None] = {
    "1_week": timedelta(weeks=1),
    "1_month": timedelta(days=30),
    "3_months": timedelta(days=90),
    "6_months": timedelta(days=180),
    "never": None,
}

# How often the worker runs a purge pass. Cleanup isn't urgent; daily is plenty.
PURGE_INTERVAL_SECONDS = 24 * 60 * 60


def cutoff_for(retention_period: str, now: datetime) -> datetime | None:
    """The timestamp before which screenshots are expired, or None if never.

    Raises KeyError on an unknown period — config.validate() already guards this,
    so reaching that branch means a programming error, not user input.
    """
    window = _RETENTION_WINDOWS[retention_period]
    return None if window is None else now - window


def _delete_file(path_str: str) -> bool:
    """Delete the PNG at `path_str`. Returns True if gone (or already absent)."""
    try:
        Path(path_str).unlink(missing_ok=True)
        return True
    except OSError as e:
        log.warning("could not delete screenshot file %s: %s", path_str, e)
        return False


def purge_once(cfg: Config, now: datetime | None = None, db_path: Path | None = None) -> dict:
    """Delete screenshots older than the retention window. Returns counts.

    Returns `{"expired", "files_deleted", "rows_deleted"}`. A no-op (and zeroed
    counts) when retention is `never`.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = cutoff_for(cfg.retention_period, now)
    if cutoff is None:
        return {"expired": 0, "files_deleted": 0, "rows_deleted": 0}

    cutoff_iso = cutoff.isoformat(timespec="seconds")
    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT id, local_path FROM screenshots WHERE timestamp < ?;", (cutoff_iso,)
        ).fetchall()

        files_deleted = 0
        ids: list[int] = []
        for row in rows:
            if _delete_file(row["local_path"]):
                files_deleted += 1
            ids.append(row["id"])

        # Delete rows even if their file couldn't be removed — the row is the
        # source of truth for "this screenshot exists"; a leftover file is
        # harmless and won't reappear in the timeline once the row is gone.
        for sid in ids:
            conn.execute("DELETE FROM screenshots WHERE id = ?;", (sid,))

    if ids:
        log.info(
            "retention: purged %d screenshots older than %s (%d files removed)",
            len(ids), cutoff_iso, files_deleted,
        )
    return {"expired": len(rows), "files_deleted": files_deleted, "rows_deleted": len(ids)}


class RetentionWorker:
    """Background thread: purge on startup, then once per day."""

    def __init__(self, cfg: Config, interval_seconds: int = PURGE_INTERVAL_SECONDS) -> None:
        self.cfg = cfg
        self._interval = interval_seconds
        self._stop = threading.Event()

    def request_stop(self) -> None:
        """Signal the worker to exit after the current wait. Thread-safe."""
        self._stop.set()

    def run(self) -> None:
        """Loop until stopped. Never raises — a bad pass is logged and retried."""
        log.info("retention worker starting (period=%s)", self.cfg.retention_period)
        while not self._stop.is_set():
            try:
                purge_once(self.cfg)
            except Exception:
                log.exception("retention pass crashed")
            self._stop.wait(timeout=self._interval)
        log.info("retention worker stopped")
