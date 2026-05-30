"""Upload-queue worker: drain pending screenshots to Google Drive.

Phase 3 scope. The capture path enqueues one `upload_queue` row per screenshot
(in the same transaction as the screenshot insert — see `capture._insert_screenshot`).
This module owns the other side: a background worker that periodically uploads
due rows, with exponential backoff on failure and offline buffering.

Design:
- A row stays `pending` and is retried with backoff until it either uploads
  (row deleted, screenshot marked 'uploaded') or hits MAX_ATTEMPTS (row +
  screenshot marked 'failed').
- "Offline" is just a transient upload error: the row stays pending and drains
  once the network returns. That's what satisfies the Phase 3 stop condition.

The Drive client is injected so the queue logic is testable without google libs
or a network — `process_once()` takes any object with an
`upload(local_path, remote_name, ts) -> file_id` method.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import transaction

log = logging.getLogger(__name__)

# Stop retrying after this many failed attempts (matches the upload_queue
# schema comment in db.py). The row + screenshot are then marked 'failed'.
MAX_ATTEMPTS = 10

# Exponential backoff between retries: base * 2**(attempts-1), capped.
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 300

# How often the worker wakes to look for due rows.
DEFAULT_POLL_SECONDS = 10


def enqueue(conn: sqlite3.Connection, screenshot_id: int, created_at: str) -> None:
    """Insert an upload_queue row for `screenshot_id`. Caller owns the transaction.

    Called from `capture._insert_screenshot` so the screenshot and its queue row
    commit atomically. `INSERT OR IGNORE` keeps the UNIQUE(screenshot_id)
    invariant idempotent if a capture path ever retries.
    """
    conn.execute(
        "INSERT OR IGNORE INTO upload_queue (screenshot_id, created_at) VALUES (?, ?);",
        (screenshot_id, created_at),
    )


def _backoff_seconds(attempts: int) -> int:
    """Delay before the next retry given how many attempts have already failed."""
    if attempts <= 0:
        return 0
    return min(BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), BACKOFF_CAP_SECONDS)


def _is_due(attempts: int, last_attempt_at: str | None, now: datetime) -> bool:
    """A pending row is due if never tried, or its backoff window has elapsed."""
    if last_attempt_at is None:
        return True
    last = datetime.fromisoformat(last_attempt_at)
    return now >= last + timedelta(seconds=_backoff_seconds(attempts))


def fetch_due(now: datetime, db_path: Path | None = None) -> list[sqlite3.Row]:
    """Pending queue rows (joined with their screenshot) that are ready to retry."""
    with transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT q.screenshot_id   AS screenshot_id,
                   q.attempts        AS attempts,
                   q.last_attempt_at AS last_attempt_at,
                   s.local_path      AS local_path,
                   s.timestamp       AS timestamp
            FROM upload_queue q
            JOIN screenshots s ON s.id = q.screenshot_id
            WHERE q.status = 'pending'
            ORDER BY q.screenshot_id;
            """
        ).fetchall()
    return [r for r in rows if _is_due(r["attempts"], r["last_attempt_at"], now)]


def record_success(screenshot_id: int, drive_file_id: str, db_path: Path | None = None) -> None:
    """Mark the screenshot uploaded and remove its queue row, atomically."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE screenshots SET upload_status = 'uploaded', drive_file_id = ? WHERE id = ?;",
            (drive_file_id, screenshot_id),
        )
        conn.execute("DELETE FROM upload_queue WHERE screenshot_id = ?;", (screenshot_id,))


def record_failure(screenshot_id: int, now: datetime, db_path: Path | None = None) -> None:
    """Bump the attempt count; mark 'failed' once MAX_ATTEMPTS is reached."""
    now_iso = now.isoformat(timespec="seconds")
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT attempts FROM upload_queue WHERE screenshot_id = ?;", (screenshot_id,)
        ).fetchone()
        if row is None:
            return  # already drained by another pass; nothing to do
        attempts = row["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            conn.execute(
                "UPDATE upload_queue SET attempts = ?, last_attempt_at = ?, status = 'failed' "
                "WHERE screenshot_id = ?;",
                (attempts, now_iso, screenshot_id),
            )
            conn.execute(
                "UPDATE screenshots SET upload_status = 'failed' WHERE id = ?;",
                (screenshot_id,),
            )
        else:
            conn.execute(
                "UPDATE upload_queue SET attempts = ?, last_attempt_at = ? WHERE screenshot_id = ?;",
                (attempts, now_iso, screenshot_id),
            )


def process_once(client, now: datetime, db_path: Path | None = None) -> dict[str, int]:
    """Attempt one upload pass over all due rows. Returns counts for logging/tests.

    `client` is anything with `upload(local_path: Path, remote_name: str,
    ts: datetime) -> str`. Any exception is treated as transient (offline /
    rate-limit / server error): the row stays pending and is retried with backoff.
    """
    due = fetch_due(now, db_path)
    uploaded = failed = 0
    for row in due:
        screenshot_id = row["screenshot_id"]
        local_path = Path(row["local_path"])
        ts = datetime.fromisoformat(row["timestamp"])
        try:
            file_id = client.upload(local_path, local_path.name, ts)
            record_success(screenshot_id, file_id, db_path)
            uploaded += 1
        except Exception:
            log.warning("upload failed for screenshot #%d (will retry)", screenshot_id)
            record_failure(screenshot_id, now, db_path)
            failed += 1
    return {"due": len(due), "uploaded": uploaded, "failed": failed}


class UploaderWorker:
    """Background thread that drains the upload queue on an interval."""

    def __init__(self, client=None, poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        self._client = client
        self._poll = poll_seconds
        self._stop = threading.Event()

    def request_stop(self) -> None:
        """Signal the worker to exit after the current pass. Thread-safe."""
        self._stop.set()

    def _get_client(self):
        if self._client is None:
            from .drive import DriveClient  # lazy: only needs google libs when active

            self._client = DriveClient()
        return self._client

    def run(self) -> None:
        """Loop until stopped. Never raises — a bad pass is logged and retried."""
        log.info("uploader worker starting (poll=%ds)", self._poll)
        while not self._stop.is_set():
            try:
                result = process_once(self._get_client(), datetime.now(timezone.utc))
                if result["due"]:
                    log.info(
                        "upload pass: %d due, %d uploaded, %d failed",
                        result["due"], result["uploaded"], result["failed"],
                    )
            except Exception:
                log.exception("uploader pass crashed")
            self._stop.wait(timeout=self._poll)
        log.info("uploader worker stopped")
