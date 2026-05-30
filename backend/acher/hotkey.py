"""Global hotkey → manual capture (Phase 5).

Listens for the configured hotkey (default ⌃⌥⇧S) anywhere on the system. When
it fires, we pop a native dialog for an activity note + tags, then take a
manual capture. The listener runs on its own thread inside the daemon.

The note dialog runs on a worker thread (not the pynput callback thread) so a
slow-typing user never blocks the key listener or risks dropped events.

macOS needs Accessibility permission for the global listener (documented in
docs/permissions-setup.md). Without it, pynput silently receives no keys.
"""

from __future__ import annotations

import logging
import threading

from pynput import keyboard

from .capture import capture_manual
from .config import Config
from .platform import platform

log = logging.getLogger(__name__)

# Map the modifier tokens we accept in config to pynput's hotkey syntax.
_MODIFIER_TOKENS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "option": "<alt>",  # macOS name for Alt
    "opt": "<alt>",
    "shift": "<shift>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "super": "<cmd>",
    "win": "<cmd>",
}


def _to_pynput_hotkey(hotkey: str) -> str:
    """Convert a config hotkey like 'ctrl+alt+shift+s' to pynput '<ctrl>+<alt>+<shift>+s'.

    Raises ValueError on an empty or malformed spec so misconfiguration surfaces
    at startup rather than silently disabling the hotkey.
    """
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty hotkey spec: {hotkey!r}")

    tokens: list[str] = []
    for part in parts:
        if part in _MODIFIER_TOKENS:
            tokens.append(_MODIFIER_TOKENS[part])
        elif len(part) == 1:
            tokens.append(part)  # a normal character key
        else:
            # A named non-modifier key (e.g. 'f5', 'space'). pynput wants <name>.
            tokens.append(f"<{part}>")
    return "+".join(tokens)


class HotkeyListener:
    """Owns the pynput global-hotkey listener for manual capture."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._listener: keyboard.GlobalHotKeys | None = None

    def _on_activate(self) -> None:
        """Hotkey fired: collect note+tags then capture, off the listener thread."""
        threading.Thread(
            target=self._do_manual_capture, name="manual-capture", daemon=True
        ).start()

    def _do_manual_capture(self) -> None:
        try:
            answer = platform.prompt_manual_note()
            if answer is None:
                log.info("manual capture cancelled by user")
                return
            note, tags = answer
            capture_manual(self.cfg, note=note or None, tags=tags or None)
        except Exception:
            # Never let a hotkey handler crash take down the listener thread.
            log.exception("manual capture handler failed")

    def start(self) -> None:
        """Begin listening. Non-blocking — pynput runs its own thread."""
        spec = _to_pynput_hotkey(self.cfg.hotkey)
        self._listener = keyboard.GlobalHotKeys({spec: self._on_activate})
        self._listener.start()
        log.info("hotkey listener active: %s (%s)", self.cfg.hotkey, spec)

    def stop(self) -> None:
        """Stop listening. Safe to call if never started."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
