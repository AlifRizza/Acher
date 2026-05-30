"""Load / save / validate `config.json`.

`config.json` lives at the project root in development. In production
(installed daemon) we copy defaults into `platform.app_data_dir / config.json`
so the user can edit it without touching the install. Phase 1 just supports
the project-root location; the app-data location lands in Phase 9 when we
wire up packaging.

The Settings UI (Phase 7) writes through this module — it is the single
source of truth for runtime config.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Project-root config file. Resolved relative to this source file so it works
# whether the package is installed editable (-e) or imported from source.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"

# Capture interval is any integer in this inclusive range, in minutes.
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 120
ALLOWED_RETENTION = ("1_week", "1_month", "3_months", "6_months", "never")
SUPPORTED_BROWSERS = ("Safari", "Chrome", "Firefox", "Arc", "Brave")


@dataclass
class Config:
    interval_minutes: int = 3
    retention_period: str = "1_month"
    hotkey: str = "ctrl+alt+shift+s"
    browsers: list[str] = field(default_factory=lambda: ["Chrome", "Arc", "Brave"])
    drive_connected: bool = False
    port: int = 7823
    # Activity watcher (idle + screen-off detection).
    idle_threshold_minutes: int = 5  # no input for this long → 'idle', capture pauses
    activity_sample_seconds: int = 5  # how often the watcher samples presence/app

    def validate(self) -> None:
        """Raise ValueError on any invalid field. Called on load and on save."""
        if not (MIN_INTERVAL_MINUTES <= self.interval_minutes <= MAX_INTERVAL_MINUTES):
            raise ValueError(
                f"interval_minutes must be in [{MIN_INTERVAL_MINUTES}, "
                f"{MAX_INTERVAL_MINUTES}], got {self.interval_minutes!r}"
            )
        if self.retention_period not in ALLOWED_RETENTION:
            raise ValueError(
                f"retention_period must be one of {ALLOWED_RETENTION}, "
                f"got {self.retention_period!r}"
            )
        unknown = [b for b in self.browsers if b not in SUPPORTED_BROWSERS]
        if unknown:
            raise ValueError(
                f"Unknown browsers in config: {unknown}. "
                f"Supported: {SUPPORTED_BROWSERS}"
            )
        if not (1024 <= self.port <= 65535):
            raise ValueError(f"port must be in [1024, 65535], got {self.port}")
        if not (1 <= self.idle_threshold_minutes <= 120):
            raise ValueError(
                f"idle_threshold_minutes must be in [1, 120], got {self.idle_threshold_minutes}"
            )
        if not (1 <= self.activity_sample_seconds <= 60):
            raise ValueError(
                f"activity_sample_seconds must be in [1, 60], got {self.activity_sample_seconds}"
            )


def load(path: Path | None = None) -> Config:
    """Read config.json from `path` (default: project root). Returns defaults
    if the file is missing. Always validates before returning.
    """
    target = path or DEFAULT_CONFIG_PATH
    if not target.exists():
        cfg = Config()
        cfg.validate()
        return cfg

    raw = json.loads(target.read_text(encoding="utf-8"))
    # Tolerate extra/missing keys: pull only known fields, fall back to defaults.
    defaults = Config()
    cfg = Config(
        interval_minutes=raw.get("interval_minutes", defaults.interval_minutes),
        retention_period=raw.get("retention_period", defaults.retention_period),
        hotkey=raw.get("hotkey", defaults.hotkey),
        browsers=list(raw.get("browsers", defaults.browsers)),
        drive_connected=bool(raw.get("drive_connected", defaults.drive_connected)),
        port=int(raw.get("port", defaults.port)),
        idle_threshold_minutes=int(
            raw.get("idle_threshold_minutes", defaults.idle_threshold_minutes)
        ),
        activity_sample_seconds=int(
            raw.get("activity_sample_seconds", defaults.activity_sample_seconds)
        ),
    )
    cfg.validate()
    return cfg


def save(cfg: Config, path: Path | None = None) -> None:
    """Validate and persist `cfg` to `path` (default: project root).

    Writes atomically via tmp file + rename so a crash mid-write can't corrupt
    config.json.
    """
    cfg.validate()
    target = path or DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


if __name__ == "__main__":
    # Quick sanity check: load + print current config.
    print(json.dumps(asdict(load()), indent=2))
