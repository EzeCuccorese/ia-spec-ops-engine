#!/usr/bin/env python3
"""
workspace_engine.services.tui_utils — TUI terminal utilities for keypress capture, alignment, and ANSI rendering.
"""

from __future__ import annotations

import os
import re
import select as _select
import sys
import termios
from types import ModuleType
from typing import IO, Any

try:
    import tty as _tty

    tty: ModuleType | None = _tty
except ImportError:
    tty = None

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b[^[]")


def strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences to compute the real visible length."""
    return _ANSI_RE.sub("", text)


def pad_colored(plain_text: str, width: int, colored_text: str) -> str:
    """Pads ANSI-styled text so it fits exactly within the column width."""
    visible_len = len(strip_ansi(plain_text))
    padding = max(0, width - visible_len)
    return colored_text + " " * padding


def draw_separator(cols: int, char: str = "═", bold: bool = True) -> str:
    """Generates a horizontal separator line sized to the terminal width."""
    line = char * max(1, cols)
    if bold:
        return f"\033[1m{line}\033[0m"
    return line


def open_tty() -> IO[Any]:
    """Opens /dev/tty for direct terminal interaction."""
    try:
        return open("/dev/tty", "rb+", buffering=0)
    except OSError:
        return sys.stdin


def write_tty(tty_fd: Any, text: str) -> None:
    """Writes text directly to the TTY descriptor."""
    if hasattr(tty_fd, "write"):
        if isinstance(text, str):
            tty_fd.write(text.encode("utf-8", errors="ignore"))
        else:
            tty_fd.write(text)
        tty_fd.flush()
    else:
        os.write(tty_fd, text.encode("utf-8", errors="ignore"))


def read_key(tty_fd: Any, timeout: float | None = None) -> bytes | None:
    """Reads a keypress, accumulating multi-byte ANSI escape sequences."""
    fd = tty_fd.fileno() if hasattr(tty_fd, "fileno") else tty_fd
    old_settings = termios.tcgetattr(fd)
    try:
        if tty:
            tty.setraw(fd)
        r, _, _ = _select.select([fd], [], [], timeout)
        if r:
            return os.read(fd, 8)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_key(tty_fd: Any) -> bytes:
    """Reads a key from the TTY, waiting for composed sequences."""
    ch = tty_fd.read(1)
    if ch != b"\x1b":
        return ch
    buf = b"\x1b"
    r, _, _ = _select.select([tty_fd], [], [], 0.1)
    while r:
        byte = tty_fd.read(1)
        buf += byte
        if byte.isalpha() or byte == b"~":
            break
        r, _, _ = _select.select([tty_fd], [], [], 0.05)
    return buf


def _resolve_cursor(output: str) -> tuple[str, str]:
    """Locates the \\x00 cursor sentinel and returns (frame, cursor_seq)."""
    idx = output.find("\x00")
    if idx < 0:
        return output, "\033[?25l"
    before = output[:idx]
    after = output[idx + 1 :]
    last_home = before.rfind("\033[H")
    frame = before[last_home + 3 :] if last_home >= 0 else before
    lines = frame.split("\r\n")
    row = len(lines)
    col = len(_ANSI_RE.sub("", lines[-1])) + 1
    return before + after, f"\033[{row};{col}H\033[?25h"
