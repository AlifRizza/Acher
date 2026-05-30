"""Acher — local-first activity tracker.

Folder map:
- `platform/`  OS-specific implementations (mac, windows) behind a shared interface.
- `db.py`      SQLite schema, connection, queries.
- `config.py`  Load/save `config.json` with defaults + validation.
- `cli.py`     `acher start|stop|status` entrypoint (fleshed out in Phase 9).

Phase 2+ will add: capture.py, upload.py, retention.py, hotkey.py, api/.
"""

__version__ = "0.1.0"
APP_NAME = "Acher"
