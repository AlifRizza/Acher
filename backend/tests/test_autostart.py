"""Autostart tests (Phase 9).

The macOS launchd path is exercised on this host (plist rendering + a real
install/uninstall against a temp HOME with launchctl stubbed). The Windows
Registry path can't run here, so we test its pure command-quoting helper.
"""

from __future__ import annotations

import plistlib
import sys

import pytest

import acher.platform.mac as mac
import acher.platform.windows as win


# ---- macOS: plist rendering ----


def test_render_plist_is_valid_and_has_command():
    cmd = ["/usr/bin/python3", "-m", "acher.cli", "start"]
    parsed = plistlib.loads(mac._render_plist(cmd).encode())
    assert parsed["Label"] == mac._LAUNCH_AGENT_LABEL
    assert parsed["ProgramArguments"] == cmd
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] is True


def test_render_plist_escapes_xml_specials():
    parsed = plistlib.loads(mac._render_plist(["/path/with & <x>", "start"]).encode())
    assert parsed["ProgramArguments"][0] == "/path/with & <x>"


def test_launch_agent_path_location():
    p = mac._launch_agent_path()
    assert p.parent.name == "LaunchAgents"
    assert p.name == "id.acher.daemon.plist"


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_install_then_uninstall(tmp_path, monkeypatch):
    # Redirect HOME so we write a real plist without touching the user's agents,
    # and stub launchctl so the test never loads anything into the live session.
    monkeypatch.setattr(mac.Path, "home", classmethod(lambda cls: tmp_path))

    calls = []

    class _Proc:
        returncode = 0
        stderr = b""
        stdout = b""

    monkeypatch.setattr(mac.subprocess, "run", lambda *a, **k: calls.append(a[0]) or _Proc())

    plat = mac.MacPlatform()
    written = plat.install_autostart(["/usr/bin/python3", "-m", "acher.cli", "start"])

    assert written.exists()
    assert plistlib.loads(written.read_bytes())["Label"] == mac._LAUNCH_AGENT_LABEL
    assert any("bootstrap" in c for c in calls)

    plat.uninstall_autostart()
    assert not written.exists()


# ---- Windows: command quoting (pure, runs anywhere) ----


def test_quote_command_plain():
    assert win._quote_command(["python", "-m", "acher.cli", "start"]) == "python -m acher.cli start"


def test_quote_command_quotes_spaces():
    out = win._quote_command([r"C:\Program Files\Py\python.exe", "-m", "acher.cli"])
    assert out == r'"C:\Program Files\Py\python.exe" -m acher.cli'


def test_windows_run_key_constants():
    assert win._RUN_KEY.endswith(r"CurrentVersion\Run")
    assert win._RUN_VALUE_NAME == "Acher"
