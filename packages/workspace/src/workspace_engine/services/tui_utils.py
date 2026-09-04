#!/usr/bin/env python3
"""
workspace_engine.services.tui_utils — Utilidades de terminal TUI para captura de teclas, alineación y renderizado ANSI.
"""

from __future__ import annotations

import os
import re
import select as _select
import sys
import termios

try:
    import tty
except ImportError:
    tty = None

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b[^[]")


def strip_ansi(text: str) -> str:
    """Elimina secuencias de escape ANSI para calcular la longitud visible real."""
    return _ANSI_RE.sub("", text)


def pad_colored(plain_text: str, width: int, colored_text: str) -> str:
    """Rellena texto con estilos ANSI para encajar exactamente en el ancho de columna."""
    visible_len = len(strip_ansi(plain_text))
    padding = max(0, width - visible_len)
    return colored_text + " " * padding


def draw_separator(cols: int, char: str = "═", bold: bool = True) -> str:
    """Genera una línea divisoria horizontal ajustada al ancho del terminal."""
    line = char * max(1, cols)
    if bold:
        return f"\033[1m{line}\033[0m"
    return line


def open_tty():
    """Abre /dev/tty para interacción directa por terminal."""
    try:
        return open("/dev/tty", "rb+", buffering=0)
    except OSError:
        return sys.stdin


def write_tty(tty_fd, text: str) -> None:
    """Escribe texto directamente al descriptor del TTY."""
    if hasattr(tty_fd, "write"):
        if isinstance(text, str):
            tty_fd.write(text.encode("utf-8", errors="ignore"))
        else:
            tty_fd.write(text)
        tty_fd.flush()
    else:
        os.write(tty_fd, text.encode("utf-8", errors="ignore"))


def read_key(tty_fd, timeout: float | None = None) -> bytes | None:
    """Lee una pulsación de tecla acumulando secuencias de escape ANSI multi-byte."""
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


def _read_key(tty_fd) -> bytes:
    """Lee una tecla desde TTY esperando secuencias compuestas."""
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
    """Ubica el centinela de cursor \\x00 y retorna (frame, cursor_seq)."""
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
