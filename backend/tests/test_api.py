"""API tests (Phase 4) via FastAPI TestClient over a temp DB + real PNG files."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from acher import db
from acher.api import create_app

# Smallest valid PNG (1x1 transparent), so FileResponse serves real bytes.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da6360000002000001e221bc330000000049454e44ae426082"
)


@pytest.fixture
def client(tmp_path):
    dbp = tmp_path / "acher.db"
    db.init_db(dbp)

    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_BYTES)

    with db.transaction(dbp) as conn:
        conn.execute(
            "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
            "upload_status, is_manual) VALUES (?, ?, ?, ?, 'uploaded', 0);",
            ("2026-05-30T10:00:00+00:00", "Chrome", "Inbox", str(png)),
        )
        conn.execute(
            "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
            "upload_status, is_manual) VALUES (?, ?, ?, ?, 'pending', 1);",
            ("2026-05-30T11:00:00+00:00", "Code", None, "/nonexistent/gone.png"),
        )
    return TestClient(create_app(dbp))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_screenshots(client):
    r = client.get("/api/screenshots")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["items"][0]["app_name"] == "Code"  # newest first


def test_list_filter_by_app(client):
    r = client.get("/api/screenshots", params={"app": "Chrome"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["app_name"] == "Chrome"


def test_list_search_and_paging(client):
    assert client.get("/api/screenshots", params={"q": "Inbox"}).json()["total"] == 1
    page = client.get("/api/screenshots", params={"limit": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1


def test_list_rejects_bad_limit(client):
    assert client.get("/api/screenshots", params={"limit": 0}).status_code == 422
    assert client.get("/api/screenshots", params={"limit": 9999}).status_code == 422


def test_get_screenshot_and_404(client):
    first = client.get("/api/screenshots").json()["items"][0]
    r = client.get(f"/api/screenshots/{first['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == first["id"]
    assert client.get("/api/screenshots/99999").status_code == 404


def test_get_image_serves_png(client):
    # The Chrome row points at a real file on disk.
    rows = client.get("/api/screenshots", params={"app": "Chrome"}).json()["items"]
    sid = rows[0]["id"]
    r = client.get(f"/api/screenshots/{sid}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _PNG_BYTES


def test_get_image_404_when_file_missing(client):
    # The Code row points at a path that doesn't exist on disk.
    rows = client.get("/api/screenshots", params={"app": "Code"}).json()["items"]
    sid = rows[0]["id"]
    r = client.get(f"/api/screenshots/{sid}/image")
    assert r.status_code == 404


def test_get_image_404_for_unknown_id(client):
    assert client.get("/api/screenshots/99999/image").status_code == 404


def test_stats(client):
    s = client.get("/api/stats").json()
    assert s["total"] == 2
    assert s["manual"] == 1
    assert s["by_status"] == {"uploaded": 1, "pending": 1}
