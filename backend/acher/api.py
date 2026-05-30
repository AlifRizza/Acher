"""Local read API over the screenshot DB (Phase 4).

A small FastAPI app the daemon serves on 127.0.0.1 (loopback only — never
exposed off-host). It reads the WAL database; the daemon remains the sole
writer. The Web UI (Phase 7) is built on these endpoints.

Endpoints:
- GET /api/health                     liveness probe
- GET /api/screenshots                filtered, paged timeline (newest first)
- GET /api/screenshots/{id}           one row
- GET /api/screenshots/{id}/image     the PNG on disk
- GET /api/stats                      timeline roll-up
- GET /api/timesheet                  per-app time roll-up (JSON)
- GET /api/timesheet/export           same, as a CSV / XLSX download
- GET /api/search                     match app/tab/note/tags (timeline search)

`create_app()` builds the app (used directly by tests); `make_server()` wraps it
in a uvicorn Server the daemon runs in a background thread.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

from . import APP_NAME, __version__
from . import config as config_mod
from . import export as export_mod
from . import queries
from .config import Config

# Loopback only. Per the architecture notes, the API is never bound to a public
# interface — it backs a local UI and nothing else.
HOST = "127.0.0.1"


def create_app(db_path: Path | None = None) -> FastAPI:
    """Build the FastAPI app. `db_path` overrides the default DB (used in tests)."""
    app = FastAPI(title=f"{APP_NAME} API", version=__version__)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "app": APP_NAME, "version": __version__}

    @app.get("/api/screenshots")
    def list_screenshots(
        limit: int = Query(queries.DEFAULT_LIMIT, ge=1, le=queries.MAX_LIMIT),
        offset: int = Query(0, ge=0),
        app_name: str | None = Query(None, alias="app"),
        q: str | None = None,
        start: str | None = None,
        end: str | None = None,
        is_manual: bool | None = None,
    ) -> dict:
        return queries.list_screenshots(
            limit=limit,
            offset=offset,
            app=app_name,
            query=q,
            start=start,
            end=end,
            is_manual=is_manual,
            db_path=db_path,
        )

    @app.get("/api/screenshots/{screenshot_id}")
    def get_screenshot(screenshot_id: int) -> dict:
        row = queries.get_screenshot(screenshot_id, db_path=db_path)
        if row is None:
            raise HTTPException(status_code=404, detail="screenshot not found")
        return row

    @app.get("/api/screenshots/{screenshot_id}/image")
    def get_image(screenshot_id: int) -> FileResponse:
        row = queries.get_screenshot(screenshot_id, db_path=db_path)
        if row is None:
            raise HTTPException(status_code=404, detail="screenshot not found")
        path = Path(row["local_path"])
        if not path.is_file():
            # Row exists but the file is gone (manually deleted, retention, etc.).
            raise HTTPException(status_code=404, detail="image file missing on disk")
        return FileResponse(path, media_type="image/png", filename=path.name)

    @app.get("/api/stats")
    def get_stats() -> dict:
        return queries.stats(db_path=db_path)

    @app.get("/api/timesheet")
    def get_timesheet(
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        # The sampling interval comes from config — it's what turns tick counts
        # into minutes (see queries.timesheet).
        interval = config_mod.load().interval_minutes
        return queries.timesheet(interval, start=start, end=end, db_path=db_path)

    @app.get("/api/timesheet/export")
    def export_timesheet(
        fmt: str = Query("csv", pattern="^(csv|xlsx)$"),
        start: str | None = None,
        end: str | None = None,
    ) -> Response:
        interval = config_mod.load().interval_minutes
        ts = queries.timesheet(interval, start=start, end=end, db_path=db_path)
        try:
            data, media_type, ext = export_mod.export_timesheet(ts, fmt)
        except RuntimeError as e:
            # XLSX requested but openpyxl isn't installed.
            raise HTTPException(status_code=501, detail=str(e)) from e
        filename = f"acher-timesheet.{ext}"
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/search")
    def search(
        q: str,
        limit: int = Query(queries.DEFAULT_LIMIT, ge=1, le=queries.MAX_LIMIT),
    ) -> dict:
        # Searches app name, tab title, activity note, and tags. Read-only.
        return queries.search(q, limit=limit, db_path=db_path)

    return app


def make_server(cfg: Config, db_path: Path | None = None):
    """Build a uvicorn Server bound to loopback:cfg.port. Caller runs it.

    Run `server.run()` in a thread and set `server.should_exit = True` to stop.
    uvicorn skips signal-handler installation off the main thread, so this is
    safe to run alongside the capture loop.
    """
    import uvicorn

    config = uvicorn.Config(
        create_app(db_path),
        host=HOST,
        port=cfg.port,
        log_level="warning",
        access_log=False,
    )
    return uvicorn.Server(config)
