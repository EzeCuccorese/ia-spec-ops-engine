"""``tty`` module handle shared by the run-local screens (None on non-Unix platforms)."""

from __future__ import annotations

from types import ModuleType

try:
    import tty as _tty

    tty: ModuleType | None = _tty
except ImportError:
    tty = None  # Non-Unix platform fallback
