"""Activity watcher: continuous presence + foreground-app tracking (schema v2).

Unlike the screenshot loop (which samples every few minutes), this watcher
samples every few SECONDS to record what the user is actually doing, second by
second. It writes merged spans to the `activity` table:

- 'active' — user present (input within the idle threshold), with the foreground
  app/tab recorded. Adjacent same-app samples merge into one span.
- 'idle'   — no input for longer than the idle threshold.
- 'locked' — screen locked or display asleep.

Two consumers use this:
1. The timeline UI draws accurate app bars + a Computer Usage row from these spans.
2. The capture loop calls `should_capture()` so it skips screenshots while the
   screen is locked/off or the user is idle.

Merging keeps the table tiny: a 25-minute VS Code session is ONE row whose
`end_ts` is extended on each sample, not 300 rows.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Config
from .db import transaction
from .platform import platform

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Presence:
    """One classified sample: the user's state and (if active) their app/tab."""

    state: str  # 'active' | 'idle' | 'locked'
    app_name: str | None
    tab_title: str | None


def classify(cfg: Config) -> Presence:
    """Read the OS once and classify the current moment.

    Order matters: a locked screen wins over idle (a locked machine is also
    idle, but 'locked' is the more specific truth and means "screen off").
    """
    if platform.is_screen_locked():
        return Presence("locked", None, None)

    idle_seconds = platform.get_idle_seconds()
    if idle_seconds >= cfg.idle_threshold_minutes * 60:
        return Presence("idle", None, None)

    active = platform.get_active_window(cfg.browsers)
    return Presence("active", active.app_name, active.tab_title)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_sample(presence: Presence, now_iso: str, db_path=None) -> None:
    """Extend the current span if unchanged, else close it and open a new one.

    "Unchanged" means same state AND same app/tab as the most recent span. This
    is what merges hundreds of samples into a handful of rows.
    """
    with transaction(db_path) as conn:
        last = conn.execute(
            "SELECT id, state, app_name, tab_title FROM activity "
            "ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        same = (
            last is not None
            and last["state"] == presence.state
            and last["app_name"] == presence.app_name
            and last["tab_title"] == presence.tab_title
        )
        if same:
            conn.execute("UPDATE activity SET end_ts = ? WHERE id = ?;", (now_iso, last["id"]))
        else:
            conn.execute(
                "INSERT INTO activity (start_ts, end_ts, state, app_name, tab_title) "
                "VALUES (?, ?, ?, ?, ?);",
                (now_iso, now_iso, presence.state, presence.app_name, presence.tab_title),
            )


class ActivityWatcher:
    """Background thread sampling presence every `activity_sample_seconds`.

    Exposes `should_capture()` so the capture loop can pause screenshots when the
    screen is locked/off or the user is idle. Thread-safe via an Event + a lock.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last: Presence | None = None

    def request_stop(self) -> None:
        """Signal the watcher to exit after the current sample. Thread-safe."""
        self._stop.set()

    def should_capture(self) -> bool:
        """True only when the latest sample was 'active'.

        Defaults to True before the first sample lands, so capture is never
        blocked waiting on the watcher.
        """
        with self._lock:
            return self._last is None or self._last.state == "active"

    def current_state(self) -> str | None:
        with self._lock:
            return self._last.state if self._last else None

    def run(self) -> None:
        """Loop until stopped. Never raises — a bad sample is logged and retried."""
        log.info(
            "activity watcher starting (sample=%ds, idle threshold=%dm)",
            self.cfg.activity_sample_seconds,
            self.cfg.idle_threshold_minutes,
        )
        while not self._stop.is_set():
            try:
                presence = classify(self.cfg)
                record_sample(presence, _now_iso())
                with self._lock:
                    self._last = presence
            except Exception:
                log.exception("activity sample failed")
            self._stop.wait(timeout=self.cfg.activity_sample_seconds)
        log.info("activity watcher stopped")
