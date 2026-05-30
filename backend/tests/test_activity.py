"""Activity watcher tests: classification, span merging, capture gating, API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from acher import activity, db, queries
from acher.activity import ActivityWatcher, Presence, classify, record_sample
from acher.api import create_app
from acher.config import Config


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    return path


def _spans(dbp):
    with db.transaction(dbp) as conn:
        return conn.execute(
            "SELECT state, app_name, tab_title, start_ts, end_ts FROM activity ORDER BY id;"
        ).fetchall()


# ---- classification ----


def test_classify_locked_wins(monkeypatch):
    monkeypatch.setattr(activity.platform, "is_screen_locked", lambda: True)
    monkeypatch.setattr(activity.platform, "get_idle_seconds", lambda: 9999)
    assert classify(Config()).state == "locked"


def test_classify_idle_over_threshold(monkeypatch):
    monkeypatch.setattr(activity.platform, "is_screen_locked", lambda: False)
    monkeypatch.setattr(activity.platform, "get_idle_seconds", lambda: 6 * 60)  # 6 min > 5
    assert classify(Config(idle_threshold_minutes=5)).state == "idle"


def test_classify_active_records_app(monkeypatch):
    from acher.platform.base import ActiveWindow

    monkeypatch.setattr(activity.platform, "is_screen_locked", lambda: False)
    monkeypatch.setattr(activity.platform, "get_idle_seconds", lambda: 2)
    monkeypatch.setattr(
        activity.platform, "get_active_window", lambda b: ActiveWindow("Code", "main.py")
    )
    p = classify(Config())
    assert p == Presence("active", "Code", "main.py")


# ---- span merging ----


def test_record_sample_merges_same_state(dbp):
    record_sample(Presence("active", "Code", None), "2026-05-30T15:30:00+00:00", dbp)
    record_sample(Presence("active", "Code", None), "2026-05-30T15:30:05+00:00", dbp)
    record_sample(Presence("active", "Code", None), "2026-05-30T15:30:10+00:00", dbp)
    rows = _spans(dbp)
    assert len(rows) == 1
    assert rows[0]["start_ts"].endswith("15:30:00+00:00")
    assert rows[0]["end_ts"].endswith("15:30:10+00:00")


def test_record_sample_splits_on_change(dbp):
    record_sample(Presence("active", "Code", None), "2026-05-30T15:30:00+00:00", dbp)
    record_sample(Presence("idle", None, None), "2026-05-30T15:36:00+00:00", dbp)
    record_sample(Presence("active", "Chrome", "GitHub"), "2026-05-30T15:40:00+00:00", dbp)
    rows = _spans(dbp)
    assert [r["state"] for r in rows] == ["active", "idle", "active"]
    assert rows[2]["app_name"] == "Chrome"


def test_record_sample_splits_on_app_change(dbp):
    record_sample(Presence("active", "Code", None), "2026-05-30T15:30:00+00:00", dbp)
    record_sample(Presence("active", "Slack", None), "2026-05-30T15:30:05+00:00", dbp)
    assert len(_spans(dbp)) == 2


# ---- capture gating ----


def test_should_capture_true_when_active(monkeypatch):
    w = ActivityWatcher(Config())
    w._last = Presence("active", "Code", None)
    assert w.should_capture() is True


def test_should_capture_false_when_idle_or_locked(monkeypatch):
    w = ActivityWatcher(Config())
    w._last = Presence("idle", None, None)
    assert w.should_capture() is False
    w._last = Presence("locked", None, None)
    assert w.should_capture() is False


def test_should_capture_defaults_true_before_first_sample():
    assert ActivityWatcher(Config()).should_capture() is True


# ---- query + API ----


def test_activity_query_window(dbp):
    record_sample(Presence("active", "Code", None), "2026-05-30T09:00:00+00:00", dbp)
    record_sample(Presence("active", "Chrome", None), "2026-05-30T12:00:00+00:00", dbp)
    out = queries.activity(start="2026-05-30T11:00:00+00:00", db_path=dbp)
    # Only the Chrome span ends after 11:00.
    assert len(out["rows"]) == 1
    assert out["rows"][0]["app_name"] == "Chrome"


def test_api_activity(dbp):
    record_sample(Presence("active", "Code", None), "2026-05-30T09:00:00+00:00", dbp)
    client = TestClient(create_app(dbp))
    r = client.get("/api/activity")
    assert r.status_code == 200
    assert r.json()["rows"][0]["state"] == "active"


# ---- daemon integration: capture is actually gated on presence ----


def test_prime_makes_first_tick_accurate(monkeypatch, tmp_path):
    """ActivityWatcher.prime() records a real sample so should_capture() is
    correct before the background loop's first iteration."""
    from acher import activity as act
    from acher.activity import ActivityWatcher

    # Point the watcher's DB writes at a temp file.
    orig_txn = db.transaction
    monkeypatch.setattr(act, "transaction", lambda db_path=None: orig_txn(tmp_path / "a.db"))
    db.init_db(tmp_path / "a.db")

    monkeypatch.setattr(act.platform, "is_screen_locked", lambda: False)
    monkeypatch.setattr(act.platform, "get_idle_seconds", lambda: 9999)  # idle

    w = ActivityWatcher(Config(idle_threshold_minutes=5))
    assert w.should_capture() is True  # fail-open before priming
    w.prime()
    assert w.current_state() == "idle"
    assert w.should_capture() is False  # accurate after priming
