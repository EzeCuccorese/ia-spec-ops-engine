#!/usr/bin/env python3
"""
workspace_engine.services.select_repos — Interactive TUI selector for choosing development repositories.
"""

from __future__ import annotations

import shutil
import sys
import termios
import tty
from pathlib import Path
from typing import IO, Any

from workspace_engine.common import Color
from workspace_engine.services.tui_utils import _read_key, _resolve_cursor

TOOLKIT_NAME = "ia-spec-ops-engine"
ADD_NEW_LABEL = "[+ Add repository by name]"


def load_repos(repos_root: Path) -> list[str]:
    """Returns the sorted list of directories inside repos_root that contain a .git."""
    if not repos_root.exists():
        return []
    result = []
    for d in sorted(repos_root.iterdir()):
        if d.is_dir() and (d / ".git").exists():
            result.append(d.name)
    return result


def apply_filter(repos: list[str], query: str) -> list[str]:
    """Returns the repositories whose names contain the search query."""
    if not query:
        return list(repos)
    q = query.lower()
    return [r for r in repos if q in r.lower()]


def _open_tty() -> IO[Any]:
    return open("/dev/tty", "rb+", buffering=0)


def _write(tty_fd: Any, s: str) -> None:
    tty_fd.write(s.encode())


def select_repos(
    toolkit_dir: Path,
    repos_root: Path | None,
    show_toolkit: bool = False,
    preselected: list[str] | None = None,
    locked: list[str] | None = None,
) -> list[str] | None:
    """Runs the interactive TUI repository selector and returns the selected ones."""
    available = load_repos(repos_root) if repos_root else []
    repos_warning = (
        ""
        if available
        else ("No repositories found" if repos_root else "AI_REPOSITORIES_DIR not configured")
    )

    selected: list[str] = []
    if preselected:
        for pre in preselected:
            if pre in available:
                selected.append(pre)

    custom_repos: list[str] = []
    toolkit_selected = False

    locked_set: set = set()
    if locked:
        for name in locked:
            if name in available:
                locked_set.add(name)

    try:
        tty_fd = _open_tty()
    except OSError:
        # Fallback for environments without a direct tty
        return selected

    old_attrs = termios.tcgetattr(tty_fd)

    def _restore() -> None:
        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
        tty_fd.close()

    try:
        tty.setraw(tty_fd.fileno())
        _write(tty_fd, "\033[?25l\033[?1049h")

        cursor = 0
        scroll = 0
        filter_str = ""
        filter_cur = 0
        prev_filter = None
        filtered = apply_filter(available, "")
        error_msg = ""

        while True:
            if filter_str != prev_filter:
                filtered = apply_filter(available, filter_str)
                prev_filter = filter_str
                scroll = 0
                total = (1 + len(filtered)) if show_toolkit else len(filtered)
                if cursor >= total and total > 0:
                    cursor = 0

            if toolkit_selected:
                total = 1
            elif show_toolkit:
                total = 1 + len(filtered)
            else:
                total = len(filtered)

            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            cols = max(60, cols)
            fixed_lines = 16 if show_toolkit else 13
            list_height = max(3, rows - fixed_lines)
            sep_w = cols - 2
            sep_d = Color.BOLD + Color.CYAN + "═" * sep_w + Color.RESET
            sep_s = Color.DIM + "─" * sep_w + Color.RESET

            lines = []
            lines.append("\033[H\033[J")
            lines.append(f"{sep_d}\r\n")
            lines.append(f"{Color.BOLD}  Select Repositories{Color.RESET}\r\n")
            lines.append(f"{sep_d}\r\n")
            lines.append(
                f"  {Color.DIM}up/down navigate   SPACE toggle   ENTER confirm   ESC back{Color.RESET}\r\n"
            )
            lines.append("\r\n")

            if toolkit_selected:
                lines.append(
                    f"  {Color.DIM}Filter: (not available when the toolkit is selected){Color.RESET}\r\n"
                )
            else:
                _fb = filter_str[:filter_cur]
                _fa = filter_str[filter_cur:]
                lines.append(
                    f"  {Color.BOLD}Filter:{Color.RESET} {Color.YELLOW}{_fb}\x00{_fa}{Color.RESET}\r\n"
                )
            lines.append("\r\n")

            if show_toolkit:
                lines.append(
                    f"  {Color.BOLD}{Color.YELLOW}── Toolkit ──────────────────────────────────────{Color.RESET}\r\n"
                )
                marker = "▶" if cursor == 0 else " "
                check = "[✔]" if toolkit_selected else "[ ]"
                color = Color.YELLOW if toolkit_selected else Color.DIM
                lines.append(f"  {color}{marker} {check} {TOOLKIT_NAME}{Color.RESET}\r\n")
                lines.append("\r\n")

            if toolkit_selected:
                lines.append(
                    f"  {Color.DIM}-- Repositories (uncheck toolkit to enable) --{Color.RESET}\r\n"
                )
            else:
                lines.append(
                    f"  {Color.BOLD}{Color.CYAN}-- Repositories ---------------------------------{Color.RESET}\r\n"
                )
                if repos_warning:
                    lines.append(f"  {Color.YELLOW}⚠ {repos_warning}{Color.RESET}\r\n")
                else:
                    lines.append(f"{sep_s}\r\n")
                    if not filtered:
                        lines.append(
                            f"  {Color.RED}No repository matches '{filter_str}'.{Color.RESET}\r\n"
                        )
                    else:
                        window = filtered[scroll : scroll + list_height]
                        for j, item in enumerate(window):
                            abs_i = scroll + j
                            rc = (abs_i + 1) if show_toolkit else abs_i
                            sh = (
                                " ↑"
                                if (j == 0 and scroll > 0)
                                else (
                                    " ↓"
                                    if (
                                        j == len(window) - 1
                                        and (scroll + list_height) < len(filtered)
                                    )
                                    else "  "
                                )
                            )
                            if item == ADD_NEW_LABEL:
                                marker = "▶" if rc == cursor else " "
                                lines.append(
                                    f"  {Color.CYAN}{marker} {Color.YELLOW}{item}{Color.RESET}{sh}\r\n"
                                )
                            else:
                                is_locked = item in locked_set
                                if is_locked:
                                    marker = "▶" if rc == cursor else " "
                                    m_color = Color.YELLOW if rc == cursor else Color.DIM
                                    lines.append(
                                        f"  {m_color}{marker}{Color.RESET} {Color.DIM}[✔] {item} (in workspace){Color.RESET}{sh}\r\n"
                                    )
                                else:
                                    in_sel = item in selected or item in custom_repos
                                    check = "[✔]" if in_sel else "[ ]"
                                    color = Color.GREEN if in_sel else Color.DIM
                                    marker = "▶" if rc == cursor else " "
                                    if rc == cursor:
                                        m_color = color if in_sel else Color.CYAN
                                        lines.append(
                                            f"  {m_color}{marker} {check} {item}{Color.RESET}{sh}\r\n"
                                        )
                                    else:
                                        lines.append(
                                            f"  {color}  {check} {item}{Color.RESET}{sh}\r\n"
                                        )
                    lines.append(f"{sep_s}\r\n")

            lines.append("\r\n")
            sel_count = len(selected) + len(custom_repos) + (1 if toolkit_selected else 0)
            if sel_count > 0:
                parts = []
                if toolkit_selected:
                    parts.append(TOOLKIT_NAME)
                parts.extend(selected)
                parts.extend(custom_repos)
                label = "Adding" if locked_set else "Selected"
                lines.append(
                    f"  {Color.BOLD}{label} ({sel_count}):{Color.RESET} {Color.GREEN}{' '.join(parts)}{Color.RESET}\r\n"
                )
            elif locked_set:
                lines.append(f"  {Color.DIM}No new repository selected yet.{Color.RESET}\r\n")
            else:
                lines.append(f"  {Color.DIM}No repository selected yet.{Color.RESET}\r\n")

            if error_msg:
                lines.append("\r\n")
                lines.append(f"  {Color.RED}{error_msg}{Color.RESET}\r\n")
                error_msg = ""

            frame, cur_seq = _resolve_cursor("".join(lines))
            _write(tty_fd, frame + cur_seq)

            key = _read_key(tty_fd)

            if key in (b"\x1b", b"\x03"):
                return None
            elif key == b"\x1b[A":  # Up
                if cursor > 0:
                    cursor -= 1
                    _rc = (cursor - 1) if show_toolkit else cursor
                    if _rc < 0:
                        scroll = 0
                    elif _rc < scroll:
                        scroll = _rc
            elif key == b"\x1b[B":  # Down
                if cursor < total - 1:
                    cursor += 1
                    _, _rows = shutil.get_terminal_size(fallback=(80, 24))
                    _lh = max(3, _rows - (16 if show_toolkit else 13))
                    _rc = (cursor - 1) if show_toolkit else cursor
                    if _rc >= scroll + _lh:
                        scroll = _rc - _lh + 1
            elif key in (b"\r", b"\n", b""):
                total_sel = len(selected) + len(custom_repos) + (1 if toolkit_selected else 0)
                if total_sel == 0:
                    error_msg = "❌ Select at least one repository."
                else:
                    break
            elif key == b" ":
                if show_toolkit and cursor == 0:
                    toolkit_selected = not toolkit_selected
                    if toolkit_selected:
                        selected.clear()
                        custom_repos.clear()
                        cursor = 0
                elif not toolkit_selected:
                    item_idx = (cursor - 1) if show_toolkit else cursor
                    if 0 <= item_idx < len(filtered):
                        item = filtered[item_idx]
                        if item in locked_set:
                            error_msg = "Already in the workspace"
                        elif item == ADD_NEW_LABEL:
                            _restore()
                            tty_fd = _open_tty()
                            old_attrs = termios.tcgetattr(tty_fd)
                            sys.stdout.write("\n  Repository name: ")
                            sys.stdout.flush()
                            new_repo = sys.stdin.readline().strip()
                            if new_repo:
                                custom_repos.append(new_repo)
                            tty.setraw(tty_fd.fileno())
                        elif item in selected:
                            selected.remove(item)
                        elif item in custom_repos:
                            custom_repos.remove(item)
                        else:
                            selected.append(item)
                        filtered = apply_filter(available, filter_str)
            elif key in (b"\x1b[D", b"\x1b[C"):
                if not toolkit_selected:
                    d = -1 if key == b"\x1b[D" else 1
                    filter_cur = max(0, min(len(filter_str), filter_cur + d))
            elif key in (b"\x1b[H", b"\x1b[1~"):
                if not toolkit_selected:
                    filter_cur = 0
            elif key in (b"\x1b[F", b"\x1b[4~"):
                if not toolkit_selected:
                    filter_cur = len(filter_str)
            elif key == b"\x1b[3~":
                if not toolkit_selected and filter_cur < len(filter_str):
                    filter_str = filter_str[:filter_cur] + filter_str[filter_cur + 1 :]
                    filtered = apply_filter(available, filter_str)
            elif key in (b"\x7f", b"\x08"):
                if not toolkit_selected and filter_cur > 0:
                    filter_str = filter_str[: filter_cur - 1] + filter_str[filter_cur:]
                    filter_cur -= 1
                    filtered = apply_filter(available, filter_str)
            else:
                ch = key.decode("utf-8", errors="ignore")
                if ch.isprintable() and not toolkit_selected:
                    filter_str = filter_str[:filter_cur] + ch + filter_str[filter_cur:]
                    filter_cur += 1
                    cursor = 0
                    filtered = apply_filter(available, filter_str)

    finally:
        _write(tty_fd, "\033[?1049l\033[?25h")
        _restore()

    if toolkit_selected:
        return [TOOLKIT_NAME]
    return selected + custom_repos
