"""SQLite schema, connection, and migrations.

One database file lives at `platform.db_path`. Three tables:

- `screenshots`   — one row per capture (auto or manual)
- `upload_queue`  — pending/failed Drive uploads
- `activity`      — continuous active/idle/locked spans (the activity watcher)

Concurrency: the daemon writes; the FastAPI server reads. We open the DB in
WAL mode so readers never block the writer and vice versa.

Schema changes after Phase 1 require explicit approval (spec stop condition).
If you need to evolve the schema, add a new `_migrate_vN()` function rather
than editing CREATE TABLE statements in place.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .platform import platform

# Bump this whenever the schema changes (then add a matching _migrate_v{N} fn).
SCHEMA_VERSION = 2


SCHEMA_SQL = """
-- One row per captured screenshot, automatic or manual.
CREATE TABLE IF NOT EXISTS screenshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,                  -- ISO8601 UTC
    app_name        TEXT    NOT NULL,
    tab_title       TEXT,                              -- nullable: only for browsers
    local_path      TEXT    NOT NULL,                  -- absolute path to PNG on disk
    drive_file_id   TEXT,                              -- nullable until uploaded
    upload_status   TEXT    NOT NULL DEFAULT 'pending' -- 'pending' | 'uploaded' | 'failed'
                            CHECK (upload_status IN ('pending', 'uploaded', 'failed')),
    is_manual       INTEGER NOT NULL DEFAULT 0         -- 0 = auto-capture, 1 = hotkey
                            CHECK (is_manual IN (0, 1)),
    activity_note   TEXT,                              -- nullable: only set by manual capture
    tags            TEXT                               -- nullable: comma-separated tags
);

-- Hot lookups:
CREATE INDEX IF NOT EXISTS idx_screenshots_timestamp     ON screenshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_screenshots_is_manual     ON screenshots(is_manual);
CREATE INDEX IF NOT EXISTS idx_screenshots_upload_status ON screenshots(upload_status);

-- Offline buffer: one row per screenshot that needs upload retry.
-- Removed on success; updated on failure; marked 'failed' after 10 attempts.
CREATE TABLE IF NOT EXISTS upload_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL UNIQUE             -- one queue row per screenshot
                             REFERENCES screenshots(id) ON DELETE CASCADE,
    created_at       TEXT    NOT NULL,                   -- ISO8601 UTC
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_attempt_at  TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending'  -- 'pending' | 'failed'
                             CHECK (status IN ('pending', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON upload_queue(status);

-- Continuous activity spans (schema v2). The activity watcher samples the
-- foreground app every few seconds and merges consecutive same-state samples
-- into one span, so this stays small (a few rows per app session, not one row
-- per sample). `state` distinguishes real work from idle/locked time:
--   'active' — user present, app in foreground (app_name set)
--   'idle'   — no input for longer than the idle threshold (app_name nullable)
--   'locked' — screen locked / display asleep (no app, no screenshots taken)
CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts    TEXT    NOT NULL,                 -- ISO8601 UTC, span start
    end_ts      TEXT    NOT NULL,                 -- ISO8601 UTC, span end (extended as it grows)
    state       TEXT    NOT NULL                  -- 'active' | 'idle' | 'locked'
                        CHECK (state IN ('active', 'idle', 'locked')),
    app_name    TEXT,                             -- foreground app while 'active'; else NULL
    tab_title   TEXT                              -- foreground browser tab while 'active'; else NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_start ON activity(start_ts);
CREATE INDEX IF NOT EXISTS idx_activity_end   ON activity(end_ts);

-- Tracks applied migrations.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL mode + foreign keys enabled.

    Callers usually want `transaction()` instead of using this directly.
    """
    path = db_path or platform.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; we manage txns manually
    conn.row_factory = sqlite3.Row
    # WAL: writers don't block readers. Crucial for daemon (writer) + API (reader).
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")  # WAL-safe; faster than FULL
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def transaction(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager: BEGIN on enter, COMMIT on success, ROLLBACK on error."""
    conn = connect(db_path)
    try:
        conn.execute("BEGIN;")
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create tables + indexes if they don't exist, then record schema version.

    Idempotent — safe to run on every daemon start. Bare-minimum migration
    bookkeeping; real upgrades land in `_migrate_v{N}()` functions later.
    """
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        current = _current_schema_version(conn)
        if current < SCHEMA_VERSION:
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?);",
                (SCHEMA_VERSION,),
            )
    finally:
        conn.close()


def _current_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version;").fetchone()
    return (row["v"] if row and row["v"] is not None else 0)


if __name__ == "__main__":
    # Lets you bootstrap the DB without running the full daemon:
    #     python -m acher.db
    init_db()
    print(f"Initialized database at {platform.db_path}")
