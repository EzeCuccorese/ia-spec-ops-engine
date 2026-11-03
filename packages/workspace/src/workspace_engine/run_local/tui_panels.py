"""Part of ``tui`` (split out, no behavior change)."""

from __future__ import annotations

import shutil
import sys
from typing import Any

from workspace_engine.run_local.constants import BOLD, CYAN, DIM, GREEN, RESET, YELLOW
from workspace_engine.run_local.profiles import load_profiles, save_profiles
from workspace_engine.services.tui_utils import draw_separator as _sep
from workspace_engine.services.tui_utils import read_key as _read_key
from workspace_engine.services.tui_utils import write_tty as _w


def _append_printable(buf: str, key: bytes | None, max_len: int) -> str:
    try:
        ch = key.decode("utf-8") if key else ""
    except UnicodeDecodeError:
        return buf  # not text (a partial escape sequence): the key is ignored
    return buf + ch if ch.isprintable() and len(buf) < max_len else buf


def _read_line(tty_fd: Any, prompt: str, max_len: int = 40) -> str | None:
    buf = ""
    while True:
        display = f"\r{prompt}{buf}  \r{prompt}{buf}"
        tty_fd.write(display.encode())
        key = _read_key(tty_fd)
        if key in (b"\r", b"\n", b""):
            return buf if buf else None
        if key == b"\x1b":
            return None
        if key == b"\x03":
            sys.exit(130)
        buf = buf[:-1] if key in (b"\x7f", b"\x08") else _append_printable(buf, key, max_len)


def _source_line(src: dict, is_cur: bool) -> str:
    mark = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
    nc = BOLD if is_cur else ""
    kind_col = CYAN if src["kind"] == "repos" else DIM
    kind_lbl = "repositories" if src["kind"] == "repos" else "workspace"
    label = src["label"]
    if len(label) > 39:
        label = label[:36] + "..."
    return f"  {mark} {nc}{label:<40}{RESET} {kind_col}{kind_lbl}{RESET}\r\n"


def _source_screen(sources: list, cursor: int, cols: int) -> str:
    out = ["\033[H\033[J"]
    out.append(_sep(cols) + "\r\n")
    out.append(f"{BOLD}  ws run-local — Select source{RESET}\r\n")
    out.append(_sep(cols) + "\r\n")
    out.append(f"  {DIM}up/down navigate   Enter select   ESC exit{RESET}\r\n\r\n")
    out.append(f"  {DIM}{'':2} {'Source':<40} {'Type'}{RESET}\r\n")
    out.append(_sep(cols, "─", bold=False) + "\r\n")
    out.extend(_source_line(src, i == cursor) for i, src in enumerate(sources))
    out.append(_sep(cols, "─", bold=False) + "\r\n")
    out.append(f"\r\n  {DIM}{sources[cursor]['path']}{RESET}\r\n")
    return "".join(out)


def panel_source_picker(tty_fd: Any, sources: list) -> dict | None:
    cursor = 0
    while True:
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        _w(tty_fd, _source_screen(sources, cursor, max(80, cols)))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        if key == b"\x03":
            sys.exit(130)
        if key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(len(sources) - 1, cursor + 1)
        elif key in (b"\r", b"\n", b""):
            return sources[cursor]


def _profile_line(name: str, profiles: dict, is_cur: bool) -> str:
    count = len(profiles[name].get("services", []))
    mark = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
    nc = BOLD if is_cur else ""
    return f"  {mark} {nc}{name:<30}{RESET}  {DIM}{count} service(s){RESET}\r\n"


def _profiles_screen(profiles: dict, cursor: int, msg: str, cols: int) -> str:
    names = list(profiles.keys())
    out = ["\033[H\033[J"]
    out.append(_sep(cols) + "\r\n")
    out.append(f"{BOLD}  Saved profiles{RESET}\r\n")
    out.append(_sep(cols) + "\r\n")
    out.append(f"  {DIM}up/down navigate   Enter load   x delete   ESC back{RESET}\r\n\r\n")
    if not names:
        out.append(
            f"  {DIM}No profiles. In the selection, use g (with an empty filter) to save one.{RESET}\r\n"
        )
    out.extend(_profile_line(name, profiles, i == cursor) for i, name in enumerate(names))
    out.append(_sep(cols, "─", bold=False) + "\r\n")
    if msg:
        out.append(f"\r\n  {YELLOW}{msg}{RESET}\r\n")
    return "".join(out)


def _delete_profile(tty_fd: Any, profiles: dict, name: str, cursor: int) -> tuple[int, str]:
    """Asks for confirmation; returns the new cursor and the message to show."""
    _w(tty_fd, f'\r\n  {YELLOW}Delete "{name}"? [y/N] {RESET}')
    if _read_key(tty_fd) not in (b"y", b"Y"):
        return cursor, ""
    del profiles[name]
    save_profiles(profiles)
    return min(cursor, max(0, len(profiles) - 1)), f'Profile "{name}" deleted.'


def panel_profiles(tty_fd: Any) -> dict | None:
    cursor = 0
    msg = ""

    while True:
        profiles = load_profiles()
        names = list(profiles.keys())
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cursor = min(cursor, max(0, len(names) - 1))
        _w(tty_fd, _profiles_screen(profiles, cursor, msg, max(80, cols)))
        msg = ""

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        if key == b"\x03":
            sys.exit(130)
        if key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(max(0, len(names) - 1), cursor + 1)
        elif key in (b"\r", b"\n", b"") and names:
            return profiles[names[cursor]]
        elif key in (b"x", b"X") and names:
            cursor, msg = _delete_profile(tty_fd, profiles, names[cursor], cursor)


def panel_confirm(tty_fd: Any, configs: list) -> bool:
    while True:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(80, cols)

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  Confirm startup{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}Enter start   ESC back{RESET}\r\n\r\n")
        out.append(
            f"  {DIM}{'Service':<28} {'Env':<14} {'Local DB':<10} {'Local MS':<11} {'Port':<7} {'Command'}{RESET}\r\n"
        )
        out.append(_sep(cols, "─", bold=False) + "\r\n")

        for c in configs:
            cmd_str = " ".join(c["service"]["cmd"])
            base_id = c.get("base_env", c["env"]["id"])
            db_loc = "[x]" if c.get("db_env") == "local" else "[ ]"
            ms_loc = "[x]" if c.get("up_mode", "auto") == "auto" else "[ ]"
            out.append(
                f"  {BOLD}{c['name']:<28}{RESET} "
                f"{CYAN}{base_id:<14}{RESET} "
                f"{CYAN}{db_loc:<10}{RESET} "
                f"{CYAN}{ms_loc:<11}{RESET} "
                f":{c['port']:<6} {DIM}{cmd_str}{RESET}\r\n"
            )

        out.append(_sep(cols, "─", bold=False) + "\r\n")
        out.append(f"\r\n  {BOLD}{GREEN}▶ [ Enter to start ]{RESET}\r\n")
        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return False
        elif key == b"\x03":
            sys.exit(130)
        elif key in (b"\r", b"\n", b""):
            return True
