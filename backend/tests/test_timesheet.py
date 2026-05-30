"""Timesheet + export tests (Phase 8): aggregation, CSV bytes, and API wiring."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from acher import db, export, queries
from acher.api import create_app


@pytest.fixture
def dbp(tmp_path):
    path = tmp_path / "acher.db"
    db.init_db(path)
    with db.transaction(path) as conn:
        for ts, app in [
            ("2026-05-30T09:00:00+00:00", "Code"),
            ("2026-05-30T09:03:00+00:00", "Code"),
            ("2026-05-30T09:06:00+00:00", "Code"),
            ("2026-05-30T09:09:00+00:00", "Chrome"),
        ]:
            conn.execute(
                "INSERT INTO screenshots (timestamp, app_name, tab_title, local_path, "
                "upload_status, is_manual) VALUES (?, ?, NULL, '/x.png', 'pending', 0);",
                (ts, app),
            )
    return path


# ---- aggregation ----


def test_timesheet_counts_and_minutes(dbp):
    ts = queries.timesheet(3, db_path=dbp)
    assert ts["total_shots"] == 4
    assert ts["total_minutes"] == 12
    assert ts["rows"][0] == {"app_name": "Code", "shots": 3, "minutes": 9}
    assert ts["rows"][1] == {"app_name": "Chrome", "shots": 1, "minutes": 3}


def test_timesheet_respects_interval(dbp):
    assert queries.timesheet(5, db_path=dbp)["total_minutes"] == 20  # 4 shots * 5


def test_timesheet_window_filter(dbp):
    ts = queries.timesheet(
        3, start="2026-05-30T09:03:00+00:00", end="2026-05-30T09:06:00+00:00", db_path=dbp
    )
    assert ts["total_shots"] == 2  # 09:03 and 09:06 only
    assert ts["rows"] == [{"app_name": "Code", "shots": 2, "minutes": 6}]


def test_timesheet_empty(dbp):
    ts = queries.timesheet(3, start="2030-01-01T00:00:00+00:00", db_path=dbp)
    assert ts["total_shots"] == 0
    assert ts["rows"] == []


# ---- export module ----


def test_to_csv_has_header_rows_and_total():
    ts = queries.timesheet  # noqa: F841 — keep import obvious
    data = export.to_csv(
        {
            "interval_minutes": 3,
            "total_minutes": 9,
            "total_shots": 3,
            "rows": [
                {"app_name": "Code", "shots": 2, "minutes": 6},
                {"app_name": "Chrome", "shots": 1, "minutes": 3},
            ],
        }
    )
    parsed = list(csv.reader(io.StringIO(data.decode())))
    assert parsed[0] == ["App", "Screenshots", "Minutes", "Hours"]
    assert parsed[1] == ["Code", "2", "6", "0.1"]
    assert parsed[-1] == ["TOTAL", "3", "9", "0.15"]


def test_export_timesheet_unknown_format_raises():
    with pytest.raises(ValueError):
        export.export_timesheet({"rows": [], "total_minutes": 0, "total_shots": 0}, "pdf")


def test_to_xlsx_requires_openpyxl_or_works():
    payload = {"interval_minutes": 3, "total_minutes": 3, "total_shots": 1,
               "rows": [{"app_name": "Code", "shots": 1, "minutes": 3}]}
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError):
            export.to_xlsx(payload)
    else:
        data = export.to_xlsx(payload)
        assert data[:2] == b"PK"  # xlsx is a zip archive


# ---- API ----


def test_api_timesheet_json(dbp):
    client = TestClient(create_app(dbp))
    r = client.get("/api/timesheet")
    assert r.status_code == 200
    body = r.json()
    assert body["total_shots"] == 4
    assert body["rows"][0]["app_name"] == "Code"


def test_api_timesheet_export_csv(dbp):
    client = TestClient(create_app(dbp))
    r = client.get("/api/timesheet/export", params={"fmt": "csv"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "acher-timesheet.csv" in r.headers["content-disposition"]
    assert r.content.splitlines()[0] == b"App,Screenshots,Minutes,Hours"


def test_api_timesheet_export_rejects_bad_format(dbp):
    client = TestClient(create_app(dbp))
    assert client.get("/api/timesheet/export", params={"fmt": "pdf"}).status_code == 422


def test_api_timesheet_export_xlsx_status(dbp):
    client = TestClient(create_app(dbp))
    r = client.get("/api/timesheet/export", params={"fmt": "xlsx"})
    # 200 if openpyxl is installed, 501 with an install hint if not.
    try:
        import openpyxl  # noqa: F401
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
    except ImportError:
        assert r.status_code == 501
