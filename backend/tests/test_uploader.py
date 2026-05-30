"""Upload-queue worker tests — queue/retry/offline logic, no google libs needed.

The Drive client is faked, so these exercise the DB-backed queue behaviour that
backs Phase 3's stop condition: uploads drain the queue, offline failures stay
queued and retry with backoff, and a reconnect drains the backlog.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from acher import db
from acher.uploader import (
    MAX_ATTEMPTS,
    _backoff_seconds,
    enqueue,
    fetch_due,
    process_once,
)

T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)

# Larger than BACKOFF_CAP_SECONDS so every retry is due regardless of attempt count.
BACKOFF_OVER_CAP = 400


class FakeClient:
    """Stand-in for DriveClient. Either uploads or raises (simulating offline)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline
        self.uploaded: list[str] = []

    def upload(self, local_path, remote_name, ts) -> str:
        if self.offline:
            raise ConnectionError("network down")
        self.uploaded.append(remote_name)
        return f"drive-{remote_name}"


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    return path


def _add_screenshot(dbp, *, ts=T0, local_path="shot.png", with_queue=True) -> int:
    with db.transaction(dbp) as conn:
        cur = conn.execute(
            "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
            "upload_status, is_manual) VALUES (?, ?, NULL, ?, 'pending', 0);",
            (ts.isoformat(timespec="seconds"), "TestApp", local_path),
        )
        sid = int(cur.lastrowid)
        if with_queue:
            enqueue(conn, sid, ts.isoformat(timespec="seconds"))
    return sid


def _screenshot(dbp, sid):
    with db.transaction(dbp) as conn:
        return conn.execute("SELECT * FROM screenshots WHERE id = ?;", (sid,)).fetchone()


def _queue_row(dbp, sid):
    with db.transaction(dbp) as conn:
        return conn.execute(
            "SELECT * FROM upload_queue WHERE screenshot_id = ?;", (sid,)
        ).fetchone()


def test_enqueue_creates_pending_queue_row(dbp):
    sid = _add_screenshot(dbp)
    row = _queue_row(dbp, sid)
    assert row is not None
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["last_attempt_at"] is None


def test_enqueue_is_idempotent(dbp):
    sid = _add_screenshot(dbp)
    with db.transaction(dbp) as conn:
        enqueue(conn, sid, T0.isoformat(timespec="seconds"))  # second time, same id
    with db.transaction(dbp) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM upload_queue WHERE screenshot_id = ?;", (sid,)
        ).fetchone()["c"]
    assert n == 1


def test_successful_upload_drains_and_marks_uploaded(dbp):
    sid = _add_screenshot(dbp)
    client = FakeClient()

    result = process_once(client, T0, dbp)

    assert result == {"due": 1, "uploaded": 1, "failed": 0}
    assert client.uploaded == ["shot.png"]
    assert _queue_row(dbp, sid) is None  # drained
    s = _screenshot(dbp, sid)
    assert s["upload_status"] == "uploaded"
    assert s["drive_file_id"] == "drive-shot.png"


def test_offline_keeps_row_pending_and_counts_attempt(dbp):
    sid = _add_screenshot(dbp)
    client = FakeClient(offline=True)

    result = process_once(client, T0, dbp)

    assert result == {"due": 1, "uploaded": 0, "failed": 1}
    row = _queue_row(dbp, sid)
    assert row["status"] == "pending"  # still queued
    assert row["attempts"] == 1
    assert _screenshot(dbp, sid)["upload_status"] == "pending"


def test_backoff_defers_retry_until_window_elapses(dbp):
    sid = _add_screenshot(dbp)
    process_once(FakeClient(offline=True), T0, dbp)  # attempts -> 1, last_attempt_at = T0

    # Within the backoff window (5s for attempt 1): not due, so skipped.
    soon = T0 + timedelta(seconds=_backoff_seconds(1) - 1)
    assert fetch_due(soon, dbp) == []
    assert process_once(FakeClient(), soon, dbp)["due"] == 0
    assert _queue_row(dbp, sid)["status"] == "pending"  # untouched

    # After the window: due again.
    later = T0 + timedelta(seconds=_backoff_seconds(1) + 1)
    assert len(fetch_due(later, dbp)) == 1


def test_offline_then_online_drains_backlog(dbp):
    """The Phase 3 stop condition, in miniature: queue while offline, drain on reconnect."""
    sids = [_add_screenshot(dbp, local_path=f"s{i}.png") for i in range(3)]

    # Network is down: nothing uploads, everything stays queued.
    offline_result = process_once(FakeClient(offline=True), T0, dbp)
    assert offline_result["failed"] == 3
    assert all(_queue_row(dbp, s)["status"] == "pending" for s in sids)

    # Reconnect after the backoff window: the whole backlog drains.
    online = FakeClient()
    later = T0 + timedelta(seconds=_backoff_seconds(1) + 1)
    online_result = process_once(online, later, dbp)

    assert online_result["uploaded"] == 3
    assert len(online.uploaded) == 3
    assert all(_queue_row(dbp, s) is None for s in sids)
    assert all(_screenshot(dbp, s)["upload_status"] == "uploaded" for s in sids)


def test_marks_failed_after_max_attempts(dbp):
    sid = _add_screenshot(dbp)
    client = FakeClient(offline=True)

    # Keep failing, advancing time past each backoff window so the row stays due.
    now = T0
    for _ in range(MAX_ATTEMPTS):
        process_once(client, now, dbp)
        now += timedelta(seconds=BACKOFF_OVER_CAP)

    row = _queue_row(dbp, sid)
    assert row["attempts"] == MAX_ATTEMPTS
    assert row["status"] == "failed"
    assert _screenshot(dbp, sid)["upload_status"] == "failed"
    # A failed row is no longer due for retry.
    assert fetch_due(now, dbp) == []


def test_backoff_seconds_is_capped_and_exponential():
    assert _backoff_seconds(0) == 0
    assert _backoff_seconds(1) == 5
    assert _backoff_seconds(2) == 10
    assert _backoff_seconds(3) == 20
    assert _backoff_seconds(100) == 300  # capped at BACKOFF_CAP_SECONDS
