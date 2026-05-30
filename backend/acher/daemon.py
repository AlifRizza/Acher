"""Background daemon: drives the capture loop.

Phase 2 scope: just the capture loop. Phase 3 adds the retry-uploader worker;
Phase 4 starts the FastAPI server in the same process. Each concern gets its
own thread; the main thread handles signals and shutdown.

The daemon never daemonizes itself — it runs in the foreground. Phase 9
wires up launchd / Windows-Registry to launch it as a managed background
process, which is the right boundary (the OS owns process lifecycle, we
just own the capture logic).
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from types import FrameType

from .capture import capture_once
from .config import Config, load as load_config
from .db import init_db
from .platform import platform

log = logging.getLogger(__name__)


class Daemon:
    """Owns the capture loop and graceful shutdown."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._uploader = None
        self._uploader_thread: threading.Thread | None = None
        self._api_server = None
        self._api_thread: threading.Thread | None = None
        self._hotkey = None
        self._retention = None
        self._retention_thread: threading.Thread | None = None
        self._activity = None
        self._activity_thread: threading.Thread | None = None

    def request_stop(self) -> None:
        """Signal the loop (and workers) to exit after the current tick. Thread-safe."""
        self._stop.set()
        if self._uploader is not None:
            self._uploader.request_stop()
        if self._api_server is not None:
            self._api_server.should_exit = True
        if self._hotkey is not None:
            self._hotkey.stop()
        if self._retention is not None:
            self._retention.request_stop()
        if self._activity is not None:
            self._activity.request_stop()

    def run(self) -> int:
        """Run until stopped. Returns process exit code."""
        log.info("Acher daemon starting (interval=%d min)", self.cfg.interval_minutes)
        log.info("Screenshots dir: %s", platform.screenshots_dir)
        log.info("Database:        %s", platform.db_path)

        if self.cfg.drive_connected:
            from .uploader import UploaderWorker

            self._uploader = UploaderWorker()
            self._uploader_thread = threading.Thread(
                target=self._uploader.run, name="uploader", daemon=True
            )
            self._uploader_thread.start()
            log.info("Drive sync enabled; uploader thread started")
        else:
            log.info("Drive sync disabled (drive_connected=false); screenshots stay local")

        # Local read API (Phase 4): serves the timeline + images on loopback.
        from .api import HOST, make_server

        self._api_server = make_server(self.cfg)
        self._api_thread = threading.Thread(
            target=self._api_server.run, name="api", daemon=True
        )
        self._api_thread.start()
        log.info("API server listening on http://%s:%d", HOST, self.cfg.port)

        # Global hotkey for manual capture (Phase 5). pynput runs its own thread.
        # A failure here (e.g. missing Accessibility permission) must not stop
        # automatic capture, so we log and carry on.
        try:
            from .hotkey import HotkeyListener

            self._hotkey = HotkeyListener(self.cfg)
            self._hotkey.start()
        except Exception:
            self._hotkey = None
            log.exception("hotkey listener failed to start; manual capture disabled")

        # Retention cleanup (Phase 6): purges screenshots past the configured
        # window on startup then daily. No-op when retention_period is 'never'.
        from .retention import RetentionWorker

        self._retention = RetentionWorker(self.cfg)
        self._retention_thread = threading.Thread(
            target=self._retention.run, name="retention", daemon=True
        )
        self._retention_thread.start()
        log.info("Retention worker started (period=%s)", self.cfg.retention_period)

        interval_sec = self.cfg.interval_minutes * 60

        while not self._stop.is_set():
            capture_once(self.cfg)
            # Event-based sleep so SIGINT wakes us immediately rather than
            # waiting up to `interval_sec` for the next tick.
            self._stop.wait(timeout=interval_sec)

        if self._uploader is not None:
            self._uploader.request_stop()
        if self._uploader_thread is not None:
            self._uploader_thread.join(timeout=15)

        if self._api_server is not None:
            self._api_server.should_exit = True
        if self._api_thread is not None:
            self._api_thread.join(timeout=10)

        if self._hotkey is not None:
            self._hotkey.stop()

        if self._retention is not None:
            self._retention.request_stop()
        if self._retention_thread is not None:
            self._retention_thread.join(timeout=10)

        if self._activity is not None:
            self._activity.request_stop()
        if self._activity_thread is not None:
            self._activity_thread.join(timeout=10)

        log.info("Acher daemon stopped")
        return 0


def _configure_logging() -> None:
    """Logs go to both stderr and the platform log file.

    File logs persist across sessions (useful for debugging launchd-managed
    runs); stderr logs are nice for foreground debugging.
    """
    log_path = platform.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid double-handlers on re-entry (e.g. test reruns).
    if root.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def run_foreground() -> int:
    """Entrypoint for `acher start`. Blocks until SIGINT/SIGTERM."""
    _configure_logging()
    init_db()
    cfg = load_config()
    daemon = Daemon(cfg)

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, stopping", signum)
        daemon.request_stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return daemon.run()


if __name__ == "__main__":
    sys.exit(run_foreground())
