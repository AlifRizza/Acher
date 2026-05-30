"""Hotkey tests (Phase 5): config→pynput parsing and the manual-capture handler.

The pynput listener itself isn't started (it needs a real input backend); we
test the pieces around it — string parsing and the on-activate flow — with the
platform dialog and capture call stubbed.
"""

from __future__ import annotations

import pytest

from acher import hotkey
from acher.config import Config


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("ctrl+alt+shift+s", "<ctrl>+<alt>+<shift>+s"),
        ("control+option+shift+s", "<ctrl>+<alt>+<shift>+s"),
        ("cmd+shift+4", "<cmd>+<shift>+4"),
        ("ctrl+f5", "<ctrl>+<f5>"),
        ("  Ctrl + Alt + S  ", "<ctrl>+<alt>+s"),
    ],
)
def test_parse_hotkey(spec, expected):
    assert hotkey._to_pynput_hotkey(spec) == expected


@pytest.mark.parametrize("bad", ["", "   ", "+", "++"])
def test_parse_hotkey_rejects_empty(bad):
    with pytest.raises(ValueError):
        hotkey._to_pynput_hotkey(bad)


def test_handler_captures_with_note_and_tags(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        hotkey.platform, "prompt_manual_note", lambda: ("wrote tests", "work,acher")
    )
    monkeypatch.setattr(
        hotkey, "capture_manual",
        lambda cfg, note=None, tags=None: calls.update(note=note, tags=tags) or 42,
    )

    hotkey.HotkeyListener(Config())._do_manual_capture()
    assert calls == {"note": "wrote tests", "tags": "work,acher"}


def test_handler_aborts_on_cancel(monkeypatch):
    called = False

    def _capture(*a, **k):
        nonlocal called
        called = True

    monkeypatch.setattr(hotkey.platform, "prompt_manual_note", lambda: None)  # cancelled
    monkeypatch.setattr(hotkey, "capture_manual", _capture)

    hotkey.HotkeyListener(Config())._do_manual_capture()
    assert called is False


def test_handler_empty_note_passes_none(monkeypatch):
    # Empty strings from the dialog become None so the DB stores NULL, not "".
    calls = {}
    monkeypatch.setattr(hotkey.platform, "prompt_manual_note", lambda: ("", ""))
    monkeypatch.setattr(
        hotkey, "capture_manual",
        lambda cfg, note=None, tags=None: calls.update(note=note, tags=tags),
    )
    hotkey.HotkeyListener(Config())._do_manual_capture()
    assert calls == {"note": None, "tags": None}


def test_handler_swallows_capture_errors(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("capture exploded")

    monkeypatch.setattr(hotkey.platform, "prompt_manual_note", lambda: ("n", "t"))
    monkeypatch.setattr(hotkey, "capture_manual", _boom)

    # Must not propagate — a crashing handler would kill the listener thread.
    hotkey.HotkeyListener(Config())._do_manual_capture()
