"""workspace_engine.run_local.tui — Interactive terminal selection and monitor screens for run_local."""

from __future__ import annotations

import termios
from typing import Any

from workspace_engine.run_local.discovery import resolve_repos_dir, scan_repos
from workspace_engine.services.tui_utils import open_tty as _open_tty
from workspace_engine.services.tui_utils import write_tty as _w

from .tui_config import panel_run_config
from .tui_monitor import _multi_tail as _multi_tail
from .tui_monitor import _run_monitor_tui as _run_monitor_tui
from .tui_monitor import panel_monitor as panel_monitor
from .tui_panels import _read_line as _read_line
from .tui_panels import panel_confirm, panel_source_picker
from .tui_panels import panel_profiles as panel_profiles
from .tui_tty import tty


def _run_selection_tui(sources: list, force_repos_dir: Any, db_cfg: dict) -> list | None:
    tty_fd = _open_tty()
    old_attrs = (
        termios.tcgetattr(tty_fd) if (tty is not None and hasattr(termios, "tcgetattr")) else None
    )
    configs: list | None = None
    chosen_src = sources[0] if (force_repos_dir or len(sources) == 1) else None
    try:
        if tty is not None:
            tty.setraw(tty_fd.fileno())
        _w(tty_fd, "\033[?25l\033[?1049h")
        step = "source" if (not force_repos_dir and len(sources) > 1) else "config"
        runnable: list = []
        while True:
            if step == "source":
                chosen_src = panel_source_picker(tty_fd, sources)
                if chosen_src is None:
                    break
                runnable = scan_repos(resolve_repos_dir(chosen_src))
                if not runnable:
                    step = "source"
                    continue
                step = "config"
            elif step == "config":
                if not runnable:
                    runnable = scan_repos(resolve_repos_dir(chosen_src or sources[0]))
                configs = panel_run_config(tty_fd, runnable, db_cfg)
                if configs is None:
                    if not force_repos_dir and len(sources) > 1:
                        step = "source"
                        runnable = []
                        continue
                    break
                step = "confirm"
            elif step == "confirm":
                assert configs is not None  # only reached once "config" has set it
                if panel_confirm(tty_fd, configs):
                    break
                step = "config"
    finally:
        # Terminal restore is best-effort: the tty state must never be left raw
        # even if closing/writing to the descriptor fails for any reason.
        try:
            _w(tty_fd, "\033[?1049l\033[?25h")
            if old_attrs is not None and tty is not None:
                termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
            tty_fd.close()
        except (OSError, termios.error):
            pass
    return configs or None
