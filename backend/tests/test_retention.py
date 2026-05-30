"""Retention tests (Phase 6): cutoff math + purge deletes old rows and files."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from acher import db, retention
from acher.config import Config

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    return path


def _add(dbp, tmp_path, *, ts, name):
    """Insert a screenshot row whose PNG actually exists on disk."""
    png = tmp_path / name
    png.write_bytes(b"\x89PNG fake")
    with db.transaction(dbp) as conn:
        conn.execute(
            "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
            "upload_status, is_manual) VALUES (?, 'App', NULL, ?, 'pending', 0);",
            (ts.isoformat(timespec="seconds"), str(png)),
        )
    return png


def _count(dbp):
    with db.transaction(dbp) as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM screenshots;").fetchone()["c"]


def test_cutoff_for_each_period():
    assert retention.cutoff_for("never", NOW) is None
    assert retention.cutoff_for("1_week", NOW) == NOW - timedelta(weeks=1)
    assert retention.cutoff_for("1_month", NOW) == NOW - timedelta(days=30)
    assert retention.cutoff_for("3_months", NOW) == NOW - timedelta(days=90)
    assert retention.cutoff_for("6_months", NOW) == NOW - timedelta(days=180)


def test_purge_deletes_old_keeps_recent(dbp, tmp_path):
    old = _add(dbp, tmp_path, ts=NOW - timedelta(days=40), name="old.png")
    recent = _add(dbp, tmp_path, ts=NOW - timedelta(days=5), name="recent.png")

    result = retention.purge_once(Config(retention_period="1_month"), now=NOW, db_path=dbp)

    assert result == {"expired": 1, "files_deleted": 1, "rows_deleted": 1}
    assert not old.exists()       # old PNG gone
    assert recent.exists()        # recent PNG kept
    assert _count(dbp) == 1       # only the recent row remains


def test_purge_boundary_is_strict_less_than(dbp, tmp_path):
    # A row exactly at the cutoff is NOT expired (cutoff uses `timestamp < cutoff`).
    _add(dbp, tmp_path, ts=NOW - timedelta(weeks=1), name="edge.png")
    result = retention.purge_once(Config(retention_period="1_week"), now=NOW, db_path=dbp)
    assert result["rows_deleted"] == 0
    assert _count(dbp) == 1


def test_purge_never_is_noop(dbp, tmp_path):
    old = _add(dbp, tmp_path, ts=NOW - timedelta(days=999), name="ancient.png")
    result = retention.purge_once(Config(retention_period="never"), now=NOW, db_path=dbp)
    assert result == {"expired": 0, "files_deleted": 0, "rows_deleted": 0}
    assert old.exists()
    assert _count(dbp) == 1


def test_purge_removes_row_even_if_file_missing(dbp, tmp_path):
    png = _add(dbp, tmp_path, ts=NOW - timedelta(days=40), name="gone.png")
    png.unlink()  # file already deleted out from under us

    result = retention.purge_once(Config(retention_period="1_month"), now=NOW, db_path=dbp)

    # File wasn't there to delete, but unlink(missing_ok=True) counts as success.
    assert result["rows_deleted"] == 1
    assert _count(dbp) == 0


def test_purge_cascades_upload_queue(dbp, tmp_path):
    # An old row with a queued upload: deleting the row must drop the queue row too.
    from acher.uploader import enqueue

    _add(dbp, tmp_path, ts=NOW - timedelta(days=40), name="q.png")
    with db.transaction(dbp) as conn:
        sid = conn.execute("SELECT id FROM screenshots;").fetchone()["id"]
        enqueue(conn, sid, NOW.isoformat(timespec="seconds"))

    retention.purge_once(Config(retention_period="1_month"), now=NOW, db_path=dbp)

    with db.transaction(dbp) as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM upload_queue;").fetchone()["c"] == 0
