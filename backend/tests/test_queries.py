"""Read-query tests (Phase 4) — filtering, paging, and stats over a temp DB."""

from __future__ import annotations

import pytest

from acher import db, queries


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    return path


def _add(dbp, *, ts, app, tab=None, status="pending", manual=0, local_path="x.png"):
    with db.transaction(dbp) as conn:
        conn.execute(
            "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
            "upload_status, is_manual) VALUES (?, ?, ?, ?, ?, ?);",
            (ts, app, tab, local_path, status, manual),
        )


def _seed(dbp):
    _add(dbp, ts="2026-05-30T09:00:00+00:00", app="Chrome", tab="Inbox", status="uploaded")
    _add(dbp, ts="2026-05-30T10:00:00+00:00", app="Code", tab=None, status="pending")
    _add(dbp, ts="2026-05-30T11:00:00+00:00", app="Chrome", tab="GitHub", status="failed", manual=1)


def test_list_empty(dbp):
    out = queries.list_screenshots(db_path=dbp)
    assert out == {"total": 0, "limit": queries.DEFAULT_LIMIT, "offset": 0, "items": []}


def test_list_newest_first_and_bool_coercion(dbp):
    _seed(dbp)
    out = queries.list_screenshots(db_path=dbp)
    assert out["total"] == 3
    tabs = [i["tab_title"] for i in out["items"]]
    assert tabs == ["GitHub", None, "Inbox"]  # 11:00, 10:00, 09:00
    assert out["items"][0]["is_manual"] is True
    assert out["items"][1]["is_manual"] is False


def test_filter_by_app(dbp):
    _seed(dbp)
    out = queries.list_screenshots(app="Chrome", db_path=dbp)
    assert out["total"] == 2
    assert {i["app_name"] for i in out["items"]} == {"Chrome"}


def test_search_matches_app_or_tab(dbp):
    _seed(dbp)
    assert queries.list_screenshots(query="hub", db_path=dbp)["total"] == 1  # GitHub tab
    assert queries.list_screenshots(query="Code", db_path=dbp)["total"] == 1  # app name


def test_filter_by_time_range(dbp):
    _seed(dbp)
    out = queries.list_screenshots(
        start="2026-05-30T09:30:00+00:00", end="2026-05-30T10:30:00+00:00", db_path=dbp
    )
    assert out["total"] == 1
    assert out["items"][0]["app_name"] == "Code"


def test_filter_is_manual(dbp):
    _seed(dbp)
    assert queries.list_screenshots(is_manual=True, db_path=dbp)["total"] == 1
    assert queries.list_screenshots(is_manual=False, db_path=dbp)["total"] == 2


def test_paging_and_total(dbp):
    _seed(dbp)
    page = queries.list_screenshots(limit=2, offset=0, db_path=dbp)
    assert page["total"] == 3 and len(page["items"]) == 2
    nxt = queries.list_screenshots(limit=2, offset=2, db_path=dbp)
    assert nxt["total"] == 3 and len(nxt["items"]) == 1


def test_limit_is_clamped(dbp):
    _seed(dbp)
    out = queries.list_screenshots(limit=10_000, db_path=dbp)
    assert out["limit"] == queries.MAX_LIMIT


def test_get_screenshot(dbp):
    _seed(dbp)
    first = queries.list_screenshots(db_path=dbp)["items"][0]
    got = queries.get_screenshot(first["id"], db_path=dbp)
    assert got["id"] == first["id"]
    assert queries.get_screenshot(99999, db_path=dbp) is None


def test_stats(dbp):
    _seed(dbp)
    s = queries.stats(db_path=dbp)
    assert s["total"] == 3
    assert s["manual"] == 1
    assert s["by_status"] == {"uploaded": 1, "pending": 1, "failed": 1}
    assert s["by_app"][0] == {"app_name": "Chrome", "count": 2}
    assert s["earliest"] == "2026-05-30T09:00:00+00:00"
    assert s["latest"] == "2026-05-30T11:00:00+00:00"
