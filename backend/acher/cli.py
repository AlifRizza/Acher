"""Acher CLI entrypoint — placeholder for Phase 1.

The real cross-platform `start | stop | status` flow lands in Phase 9, where
we wire up launchd (macOS) and the Windows Registry. For now this is just
enough for `acher --help` and `python -m acher` to do something sensible.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import APP_NAME, __version__
from . import config as cfg_mod
from . import db as db_mod
from .platform import platform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acher",
        description=f"{APP_NAME} — activity tracker with screenshots and Drive sync.",
    )
    parser.add_argument("--version", action="version", version=f"acher {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("init", help="Initialize database + app-data dir.")
    subparsers.add_parser("config", help="Print the active config to stdout.")
    subparsers.add_parser("paths", help="Print resolved platform paths.")
    subparsers.add_parser("auth", help="Authorize Google Drive sync (OAuth).")
    cap = subparsers.add_parser("capture", help="Take one manual capture now (note/tags optional).")
    cap.add_argument("--note", default=None, help="Activity note for this capture.")
    cap.add_argument("--tags", default=None, help="Comma-separated tags.")
    subparsers.add_parser("purge", help="Delete screenshots past the retention window now.")
    subparsers.add_parser("start", help="Start the capture daemon in the foreground.")
    subparsers.add_parser("install", help="Register Acher to launch at login.")
    subparsers.add_parser("uninstall", help="Remove the launch-at-login entry.")
    # Phase 9 stubs — listed so `--help` advertises what's coming.
    subparsers.add_parser("stop",  help="(Phase 9) Stop the background daemon.")
    subparsers.add_parser("status", help="(Phase 9) Show daemon status.")

    args = parser.parse_args(argv)
    command = args.command or "paths"

    if command == "init":
        db_mod.init_db()
        print(f"Initialized {APP_NAME} at {platform.app_data_dir}")
        return 0

    if command == "config":
        print(json.dumps(asdict(cfg_mod.load()), indent=2))
        return 0

    if command == "paths":
        info = {
            "app_data_dir":     str(platform.app_data_dir),
            "screenshots_dir":  str(platform.screenshots_dir),
            "db_path":          str(platform.db_path),
            "log_path":         str(platform.log_path),
        }
        print(json.dumps(info, indent=2))
        return 0

    if command == "auth":
        # Phase 3: run the OAuth desktop flow, cache the token, and flip
        # drive_connected on so the daemon starts uploading on next start.
        from .drive import DriveClient

        try:
            token_path = DriveClient.authorize()
        except RuntimeError as e:
            print(f"Drive auth failed: {e}", file=sys.stderr)
            return 1
        cfg = cfg_mod.load()
        cfg.drive_connected = True
        cfg_mod.save(cfg)
        print(f"Drive authorized. Token cached at {token_path}.")
        print("Restart the daemon (`acher start`) to begin uploading.")
        return 0

    if command == "capture":
        # Phase 5: one-off manual capture. Same path the hotkey triggers, minus
        # the dialog — note/tags come from flags here. Needs the DB to exist.
        from .capture import capture_manual
        db_mod.init_db()
        row_id = capture_manual(cfg_mod.load(), note=args.note, tags=args.tags)
        if row_id is None:
            print("Manual capture failed; see logs.", file=sys.stderr)
            return 1
        print(f"Manual capture saved as screenshot #{row_id}.")
        return 0

    if command == "purge":
        # Phase 6: run one retention pass now. Honours config.retention_period;
        # a no-op when that's 'never'.
        from .retention import purge_once
        db_mod.init_db()
        cfg = cfg_mod.load()
        result = purge_once(cfg)
        if cfg.retention_period == "never":
            print("Retention is 'never'; nothing purged.")
        else:
            print(
                f"Purged {result['rows_deleted']} screenshots "
                f"({result['files_deleted']} files removed)."
            )
        return 0

    if command == "start":
        # Foreground capture loop. `install` registers the OS to run this at
        # login; the work is identical either way — the OS just owns lifecycle.
        from .daemon import run_foreground
        return run_foreground()

    if command == "install":
        # Phase 9: register autostart. The command the OS will run at login is
        # this same interpreter invoking `acher.cli start` (no PATH dependency).
        daemon_command = [sys.executable, "-m", "acher.cli", "start"]
        try:
            target = platform.install_autostart(daemon_command)
        except Exception as e:
            print(f"Install failed: {e}", file=sys.stderr)
            return 1
        print(f"Acher will start at login. Installed: {target}")
        return 0

    if command == "uninstall":
        try:
            platform.uninstall_autostart()
        except Exception as e:
            print(f"Uninstall failed: {e}", file=sys.stderr)
            return 1
        print("Removed launch-at-login entry.")
        return 0

    if command in ("stop", "status"):
        print(f"`acher {command}` is implemented in Phase 9.", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
