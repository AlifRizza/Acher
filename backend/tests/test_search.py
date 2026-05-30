"""Search tests (timeline search): matches across app/tab/note/tags."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from acher import db, queries
from acher.api import create_app


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    with db.transaction(path) as conn:
        rows = [
            ("2026-05-30T09:00:00+00:00", "Code", "main.py", None, None, 0),
            ("2026-05-30T09:03:00+00:00", "Chrome", "GitHub - pull request", None, None, 0),
            ("2026-05-30T09:06:00+00:00", "Chrome", "notes", "call with Acme", "work,client", 1),
        ]
        for ts, app, tab, note, tags, manual in rows:
            conn.execute(
                "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
                "upload_status, is_manual, activity_note, tags) "
                "VALUES (?, ?, ?, '/x.png', 'pending', ?, ?, ?);",
                (ts, app, tab, manual, note, tags),
            )
    return path


def test_search_matches_app(dbp):
    assert queries.search("code", db_path=dbp)["total"] == 1


def test_search_matches_tab(dbp):
    assert queries.search("github", db_path=dbp)["total"] == 1


def test_search_matches_note(dbp):
    out = queries.search("acme", db_path=dbp)
    assert out["total"] == 1
    assert out["items"][0]["activity_note"] == "call with Acme"


def test_search_matches_tag(dbp):
    assert queries.search("client", db_path=dbp)["total"] == 1


def test_search_is_case_insensitive(dbp):
    assert queries.search("CHROME", db_path=dbp)["total"] == 2


def test_search_empty_returns_nothing(dbp):
    assert queries.search("   ", db_path=dbp) == {"total": 0, "limit": 50, "offset": 0, "items": []}


def test_search_no_match(dbp):
    assert queries.search("zzznomatch", db_path=dbp)["total"] == 0


def test_api_search(dbp):
    client = TestClient(create_app(dbp))
    r = client.get("/api/search", params={"q": "chrome"})
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_api_search_requires_q(dbp):
    client = TestClient(create_app(dbp))
    assert client.get("/api/search").status_code == 422
