"""Read-side DB queries for the local API (Phase 4).

The daemon owns all writes (capture, upload bookkeeping). This module owns the
reads the API serves: list/filter the timeline, fetch one screenshot, and roll
up stats. Keeping the SQL here keeps the HTTP layer (`api.py`) thin and lets the
queries be tested without spinning up a server.

Reads use a plain autocommit connection (`db.connect`, isolation_level=None) —
no transaction needed for SELECTs, and WAL means we never block the writer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import connect

# Cap how many rows one list call can return, regardless of what's requested.
MAX_LIMIT = 500
DEFAULT_LIMIT = 50

# Columns exposed by the API (excludes nothing sensitive; the whole row is local).
_COLUMNS = (
    "id, timestamp, app_name, tab_title, local_path, "
    "drive_file_id, upload_status, is_manual, activity_note, tags"
)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # is_manual is stored 0/1; surface it as a bool for API consumers.
    if "is_manual" in d:
        d["is_manual"] = bool(d["is_manual"])
    return d


def list_screenshots(
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    app: str | None = None,
    query: str | None = None,
    start: str | None = None,
    end: str | None = None,
    is_manual: bool | None = None,
    db_path: Path | None = None,
) -> dict:
    """Return a page of screenshots (newest first) plus the total match count.

    Filters (all optional, AND-combined):
    - `app`:    exact `app_name` match
    - `query`:  substring match against `app_name` or `tab_title`
    - `start`/`end`: inclusive ISO8601 bounds on `timestamp`
    - `is_manual`: restrict to manual (True) or auto (False) captures

    Returns `{"total", "limit", "offset", "items"}`.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    clauses: list[str] = []
    params: list[object] = []
    if app:
        clauses.append("app_name = ?")
        params.append(app)
    if query:
        clauses.append("(app_name LIKE ? OR tab_title LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])
    if start:
        clauses.append("timestamp >= ?")
        params.append(start)
    if end:
        clauses.append("timestamp <= ?")
        params.append(end)
    if is_manual is not None:
        clauses.append("is_manual = ?")
        params.append(1 if is_manual else 0)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = connect(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM screenshots{where};", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM screenshots{where} "
            "ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?;",
            (*params, limit, offset),
        ).fetchall()
    finally:
        conn.close()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_row_to_dict(r) for r in rows],
    }


def get_screenshot(screenshot_id: int, db_path: Path | None = None) -> dict | None:
    """One screenshot row as a dict, or None if no such id."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM screenshots WHERE id = ?;", (screenshot_id,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def stats(db_path: Path | None = None) -> dict:
    """Timeline roll-up: totals, per-status, per-app (top 10), and time span."""
    conn = connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM screenshots;").fetchone()["c"]
        manual = conn.execute(
            "SELECT COUNT(*) AS c FROM screenshots WHERE is_manual = 1;"
        ).fetchone()["c"]
        by_status = {
            r["upload_status"]: r["c"]
            for r in conn.execute(
                "SELECT upload_status, COUNT(*) AS c FROM screenshots GROUP BY upload_status;"
            ).fetchall()
        }
        by_app = [
            {"app_name": r["app_name"], "count": r["c"]}
            for r in conn.execute(
                "SELECT app_name, COUNT(*) AS c FROM screenshots "
                "GROUP BY app_name ORDER BY c DESC, app_name LIMIT 10;"
            ).fetchall()
        ]
        span = conn.execute(
            "SELECT MIN(timestamp) AS earliest, MAX(timestamp) AS latest FROM screenshots;"
        ).fetchone()
    finally:
        conn.close()

    return {
        "total": total,
        "manual": manual,
        "by_status": by_status,
        "by_app": by_app,
        "earliest": span["earliest"],
        "latest": span["latest"],
    }


def timesheet(
    interval_minutes: int,
    *,
    start: str | None = None,
    end: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Per-app time roll-up over an optional [start, end] window.

    Each screenshot is a point-in-time tick taken every `interval_minutes`, so
    estimated time on an app = (tick count) × interval. This mirrors the
    ActivityWatch heartbeat idea, simplified (research.md §1.4): we don't merge
    adjacent events, we just multiply counts by the sampling interval.

    Returns `{"start", "end", "interval_minutes", "total_minutes", "total_shots",
    "rows": [{app_name, shots, minutes}]}`, apps sorted by time desc.
    """
    clauses: list[str] = []
    params: list[object] = []
    if start:
        clauses.append("timestamp >= ?")
        params.append(start)
    if end:
        clauses.append("timestamp <= ?")
        params.append(end)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = connect(db_path)
    try:
        grouped = conn.execute(
            f"SELECT app_name, COUNT(*) AS shots FROM screenshots{where} "
            "GROUP BY app_name ORDER BY shots DESC, app_name;",
            params,
        ).fetchall()
    finally:
        conn.close()

    rows = [
        {
            "app_name": r["app_name"],
            "shots": r["shots"],
            "minutes": r["shots"] * interval_minutes,
        }
        for r in grouped
    ]
    total_shots = sum(r["shots"] for r in rows)
    return {
        "start": start,
        "end": end,
        "interval_minutes": interval_minutes,
        "total_minutes": total_shots * interval_minutes,
        "total_shots": total_shots,
        "rows": rows,
    }


def activity(
    *, start: str | None = None, end: str | None = None, db_path: Path | None = None
) -> dict:
    """Continuous activity spans overlapping the optional [start, end] window.

    Returns `{"rows": [{id, start_ts, end_ts, state, app_name, tab_title}]}`,
    oldest first — the shape the timeline uses to draw accurate app bars and the
    Computer Usage row. A span overlaps the window if it starts before `end` and
    ends after `start`.
    """
    clauses: list[str] = []
    params: list[object] = []
    if end:
        clauses.append("start_ts <= ?")
        params.append(end)
    if start:
        clauses.append("end_ts >= ?")
        params.append(start)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, start_ts, end_ts, state, app_name, tab_title "
            f"FROM activity{where} ORDER BY start_ts;",
            params,
        ).fetchall()
    finally:
        conn.close()
    return {"rows": [dict(r) for r in rows]}


def search(query: str, *, limit: int = DEFAULT_LIMIT, db_path: Path | None = None) -> dict:
    """Full-text-ish search across app name, tab title, activity note, and tags.

    Case-insensitive substring match (SQLite LIKE) over the four free-text
    columns, newest first. Returns the same `{total, limit, offset, items}`
    shape as `list_screenshots` so the UI can reuse one renderer. An empty or
    whitespace-only query returns no results (the UI shouldn't call it then).
    """
    limit = max(1, min(limit, MAX_LIMIT))
    term = query.strip()
    if not term:
        return {"total": 0, "limit": limit, "offset": 0, "items": []}

    like = f"%{term}%"
    where = (
        "WHERE app_name LIKE ? OR tab_title LIKE ? "
        "OR activity_note LIKE ? OR tags LIKE ?"
    )
    params = [like, like, like, like]

    conn = connect(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM screenshots {where};", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM screenshots {where} "
            "ORDER BY timestamp DESC, id DESC LIMIT ?;",
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()

    return {
        "total": total,
        "limit": limit,
        "offset": 0,
        "items": [_row_to_dict(r) for r in rows],
    }
