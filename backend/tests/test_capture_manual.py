"""capture_manual (Phase 5): manual captures persist is_manual + note + tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from acher import capture, db
from acher.config import Config
from acher.platform.base import ActiveWindow


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point capture's DB at a temp file and stub the OS screenshot/window calls."""
    dbp = tmp_path / "acher.db"
    db.init_db(dbp)

    orig_txn = db.transaction
    monkeypatch.setattr(capture, "transaction", lambda: orig_txn(dbp))
    monkeypatch.setattr(
        capture.platform, "get_active_window",
        lambda browsers: ActiveWindow(app_name="Code", tab_title=None),
    )
    monkeypatch.setattr(
        capture.platform, "capture_screenshot", lambda dest: Path(dest).write_bytes(b"x")
    )
    monkeypatch.setattr(capture, "_month_partition_dir", lambda ts: tmp_path)
    return dbp, orig_txn


def _row(orig_txn, dbp, sid):
    with orig_txn(dbp) as conn:
        return conn.execute("SELECT * FROM screenshots WHERE id = ?;", (sid,)).fetchone()


def test_manual_capture_sets_flag_and_fields(wired):
    dbp, orig_txn = wired
    sid = capture.capture_manual(Config(), note="fixing bug", tags="work,acher")
    assert sid is not None
    row = _row(orig_txn, dbp, sid)
    assert row["is_manual"] == 1
    assert row["activity_note"] == "fixing bug"
    assert row["tags"] == "work,acher"


def test_manual_capture_allows_empty_note(wired):
    dbp, orig_txn = wired
    sid = capture.capture_manual(Config(), note=None, tags=None)
    row = _row(orig_txn, dbp, sid)
    assert row["is_manual"] == 1
    assert row["activity_note"] is None
    assert row["tags"] is None


def test_auto_capture_stays_unmanual(wired):
    dbp, orig_txn = wired
    sid = capture.capture_once(Config())
    row = _row(orig_txn, dbp, sid)
    assert row["is_manual"] == 0
    assert row["activity_note"] is None


def test_manual_capture_uses_passed_active_window(wired):
    """When `active` is supplied (hotkey path), the row records THAT window — not
    whatever get_active_window() returns afterward (the focus-stealing dialog,
    e.g. 'osascript'). Regression for the wrong-app manual-capture bug."""
    dbp, orig_txn = wired
    # Fixture stubs get_active_window -> "Code"; make live detection return the
    # dialog to prove the passed-in window wins.
    capture.platform.get_active_window = lambda browsers: ActiveWindow("osascript", None)

    sid = capture.capture_manual(
        Config(), note="real note", tags="a,b",
        active=ActiveWindow(app_name="Brave Browser", tab_title="GitHub"),
    )
    row = _row(orig_txn, dbp, sid)
    assert row["app_name"] == "Brave Browser"
    assert row["tab_title"] == "GitHub"
    assert "osascript" not in row["local_path"]
