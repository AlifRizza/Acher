"""Platform selector.

Every OS-specific call goes through this module. Business logic elsewhere in
the codebase should import `from acher.platform import platform` and call
methods on the returned `Platform` instance — never check `sys.platform`
directly.

We pick the implementation once at import time based on `sys.platform`.
"""

from __future__ import annotations

import sys

from .base import Platform


def _select_platform() -> Platform:
    """Pick the right Platform subclass for the current OS."""
    if sys.platform == "darwin":
        from .mac import MacPlatform
        return MacPlatform()
    if sys.platform in ("win32", "cygwin"):
        from .windows import WindowsPlatform
        return WindowsPlatform()
    raise RuntimeError(
        f"Acher does not support platform {sys.platform!r}. "
        "Supported: darwin (macOS), win32 (Windows)."
    )


# Singleton — created once on first import.
platform: Platform = _select_platform()

__all__ = ["Platform", "platform"]
