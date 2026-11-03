"""Part of ``tui`` (split out, no behavior change)."""

from __future__ import annotations

import contextlib
import inspect
import os
import re
import shutil
import subprocess
import termios
import threading
import time
from dataclasses import dataclass
from typing import Any

from workspace_engine.run_local.constants import (
    BOLD,
    CYAN,
    DIM,
    ENVS_DIR,
    GREEN,
    LOGS_DIR,
    PIDS_DIR,
    RESET,
    YELLOW,
)
from workspace_engine.run_local.discovery import _fmt_bytes, _fmt_uptime, _service_link
from workspace_engine.run_local.process_manager import (
    _HEALTH,
    _all_group_rss,
    _health_worker,
    _launch_one,
    _log_rotation_worker,
    _pid_alive,
    _status_str,
    _terminate,
    _wait_port_free,
    save_state,
)
from workspace_engine.services.tui_utils import draw_separator as _sep
from workspace_engine.services.tui_utils import open_tty as _open_tty
from workspace_engine.services.tui_utils import pad_colored as _pad
from workspace_engine.services.tui_utils import read_key as _read_key
from workspace_engine.services.tui_utils import write_tty as _w

from .tui_tty import tty

_TAIL_COLORS = [GREEN, CYAN, YELLOW, "\033[0;35m", "\033[0;34m", "\033[0;31m"]


_ERROR_RE = re.compile(r"ERROR|FATAL|Exception|error:", re.IGNORECASE)
_ALT_OFF = "\033[?1049l\033[?25h"  # leave the alternate screen, show the cursor
_ALT_ON = "\033[?25l\033[?1049h"


def _open_tails(entries: list) -> list[dict]:
    handles = []
    for e in entries:
        try:
            fh = open(e["log"], errors="replace", encoding="utf-8")  # noqa: SIM115
            fh.seek(0, 2)
            handles.append({"fh": fh, "pos": fh.tell(), "log": e["log"]})
        except OSError:
            handles.append({"fh": None, "pos": 0, "log": e["log"]})
    return handles


def _rewind_if_truncated(h: dict) -> None:
    try:
        current_size = os.path.getsize(h["log"])
    except OSError:
        return  # the log vanished (rotation in progress): keep following the open handle
    if current_size < h["pos"]:
        h["fh"].seek(0)
        h["pos"] = 0


def _print_new_lines(e: dict, h: dict, error_re: re.Pattern | None, max_name: int) -> None:
    fh = h["fh"]
    while True:
        line = fh.readline()
        if not line:
            return
        h["pos"] = fh.tell()
        if error_re and not error_re.search(line):
            continue
        prefix = f"{e['color']}{e['name']:<{max_name}}{RESET}"
        print(f"{prefix} {DIM}|{RESET} {line}", end="", flush=True)


def _poll_tail(e: dict, h: dict, error_re: re.Pattern | None, max_name: int) -> None:
    if h["fh"] is None:
        return
    _rewind_if_truncated(h)
    _print_new_lines(e, h, error_re, max_name)


def _follow_tails(entries: list, handles: list[dict], error_re: re.Pattern | None) -> None:
    max_name = max((len(e["name"]) for e in entries), default=10)
    with contextlib.suppress(KeyboardInterrupt):  # Ctrl-C is how the user returns to the monitor
        while True:
            for e, h in zip(entries, handles, strict=False):
                _poll_tail(e, h, error_re, max_name)
            time.sleep(0.2)


def _multi_tail(entries: list, filter_errors: bool, cooked_attrs: Any, tty_fd: Any) -> None:
    _w(tty_fd, _ALT_OFF)
    if cooked_attrs is not None and tty is not None:
        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)

    error_re = _ERROR_RE if filter_errors else None
    suffix = " — errors only" if filter_errors else ""
    print(f"\n  Combined tail{suffix}  |  Ctrl-C to return to the monitor\n")

    handles = _open_tails(entries)
    try:
        _follow_tails(entries, handles, error_re)
    finally:
        for h in handles:
            if h["fh"]:
                h["fh"].close()
        if tty is not None:
            tty.setraw(tty_fd.fileno())
        _w(tty_fd, _ALT_ON)


@dataclass
class MonitorSession:
    """What the monitor shows and acts on."""

    results: list
    launch_configs: list
    db_cfg: dict


@dataclass(frozen=True)
class _Layout:
    cols: int
    lh: int
    show_uptime: bool
    show_ram: bool
    ram_map: dict


# Keys of the monitor and the method that handles them.
_KEYS: dict[bytes, str] = {
    **dict.fromkeys((b"\x03", b"q", b"Q"), "_quit"),
    **dict.fromkeys((b"a", b"A"), "_add"),
    b"\x1b[A": "_up",
    b"\x1b[B": "_down",
    b" ": "_mark",
    **dict.fromkeys((b"s", b"S"), "_stop"),
    **dict.fromkeys((b"r", b"R"), "_restart"),
    **dict.fromkeys((b"o", b"O"), "_browser"),
    **dict.fromkeys((b"t", b"T"), "_tail"),
    **dict.fromkeys((b"\r", b"\n", b""), "_logs"),
    **dict.fromkeys((b"l", b"L"), "_errors"),
    **dict.fromkeys((b"e", b"E"), "_envs"),
}


class _MonitorScreen:
    """State, drawing and key handling of the service monitor."""

    def __init__(self, tty_fd: Any, session: MonitorSession, cooked_attrs: Any) -> None:
        self.tty_fd = tty_fd
        self.results = session.results
        self.launch_configs = session.launch_configs
        self.db_cfg = session.db_cfg
        self.cooked_attrs = cooked_attrs
        self.cursor = 0
        self.marked: set = set()
        self.ask_cascade: list | None = None

    def run(self) -> str:
        stop_health = threading.Event()
        threading.Thread(
            target=_health_worker, args=(self.results, stop_health), daemon=True
        ).start()
        threading.Thread(target=_log_rotation_worker, args=(stop_health,), daemon=True).start()
        try:
            while True:
                outcome = self._step()
                if outcome is not None:
                    return outcome
        finally:
            stop_health.set()

    def _step(self) -> str | None:
        _w(self.tty_fd, self._screen())
        key = _read_key(self.tty_fd) if self.ask_cascade else _read_key(self.tty_fd, timeout=2.0)
        if self.ask_cascade is not None:
            self._answer_cascade(key)
            return None
        if key is None:
            return None
        handler = _KEYS.get(key)
        return getattr(self, handler)(key) if handler else None

    # -- services ----------------------------------------------------------------------
    @staticmethod
    def _is_running(r: dict) -> bool:
        return _pid_alive(r.get("pid"))

    @staticmethod
    def _stop_service(r: dict) -> None:
        if r.get("pid"):
            _terminate(r["pid"])
            (PIDS_DIR / f"{r['name']}.pid").unlink(missing_ok=True)
            r["pid"] = None
            _HEALTH.pop(r["name"], None)

    def _config_of(self, r: dict) -> dict | None:
        return next((c for c in self.launch_configs if c["name"] == r["name"]), None)

    def _restart_service(self, r: dict) -> None:
        self._stop_service(r)
        if not _wait_port_free(r["port"]):
            r["error"] = f"Port {r['port']} was not freed in time"
            return
        cfg = self._config_of(r)
        if not cfg:
            return
        running_ports = {c["name"]: c["port"] for c in self.launch_configs}
        pid, err, started_at, _ = _launch_one(cfg, running_ports, self.db_cfg)
        r["pid"] = pid
        r["error"] = err
        r["started_at"] = started_at

    # -- drawing -----------------------------------------------------------------------
    def _layout(self) -> _Layout:
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(80, cols)
        show_ram = cols >= 110
        running_pids = [r["pid"] for r in self.results if r.get("pid")]
        ram_map = _all_group_rss(running_pids) if show_ram and running_pids else {}
        return _Layout(cols, max(4, rows - 14), cols >= 90, show_ram, ram_map)

    def _screen(self) -> str:
        layout = self._layout()
        out = ["\033[H\033[J", *self._header(layout)]
        rows, wiring_detail = self._rows(layout)
        out.extend(rows)
        out.append(_sep(layout.cols, "─", bold=False) + "\r\n")
        if wiring_detail:
            out.append(f"  {DIM}{wiring_detail}{RESET}\r\n")
        if self.ask_cascade:
            names = ", ".join(self.ask_cascade)
            out.append(f"\r\n  {BOLD}Dependents detected:{RESET} {DIM}{names}{RESET}\r\n")
            out.append(f"  {YELLOW}Restart them too? [y = yes · any other key = no]{RESET} ")
        out.append(f"\r\n  {DIM}Logs: {LOGS_DIR}/{RESET}\r\n")
        return "".join(out)

    @staticmethod
    def _header(layout: _Layout) -> list[str]:
        out = [_sep(layout.cols) + "\r\n", f"{BOLD}  Service monitor{RESET}\r\n"]
        out.append(_sep(layout.cols) + "\r\n")
        out.append(
            f"  {DIM}up/down nav   SPACE mark   t tail   T tail-err   Enter logs   l err   e envs   o browser{RESET}\r\n"
        )
        out.append(
            f"  {DIM}s stop   r restart   a add   q quit  (services keep running on exit){RESET}\r\n\r\n"
        )
        hdr = f"  {' '} {'✓'} {'Service':<28} " + _pad("Status", 13, f"{DIM}Status{RESET}") + " "
        if layout.show_uptime:
            hdr += f"{DIM}{'Uptime':<8}{RESET}"
        if layout.show_ram:
            hdr += f"{DIM}{'RAM':<8}{RESET}"
        out.append(hdr + f"{DIM}{'Envs':<12}{RESET}{DIM}URL{RESET}\r\n")
        out.append(_sep(layout.cols, "─", bold=False) + "\r\n")
        return out

    def _rows(self, layout: _Layout) -> tuple[list[str], str]:
        scroll = max(0, self.cursor - layout.lh + 1)
        rows: list[str] = []
        wiring_detail = ""
        for i, r in enumerate(self.results[scroll : scroll + layout.lh]):
            is_cur = scroll + i == self.cursor
            cfg = self._config_of(r)
            rows.append(self._row(r, cfg, is_cur, layout))
            if is_cur and cfg:
                wiring_detail = self._wiring(cfg)
        return rows, wiring_detail

    @staticmethod
    def _wiring(cfg: dict) -> str:
        wiring = cfg.get("wiring", {})
        up_mode = cfg.get("up_mode", "auto")
        if wiring:
            local_s = ", ".join(f"{n}:{p}" for n, p in wiring.items())
            return f"→ local: {local_s} · rest: {cfg['env']['id']}"
        return f"→ all to: {up_mode}" if up_mode != "auto" else ""

    def _row(self, r: dict, cfg: dict | None, is_cur: bool, layout: _Layout) -> str:
        running = self._is_running(r)
        mark_cur = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
        mark_tail = f"{CYAN}✓{RESET}" if r["name"] in self.marked else " "
        nc = BOLD if is_cur else ""
        plain_st, colored_st = _status_str(r["name"], r.get("pid"))
        status_col = _pad(plain_st, 13, colored_st)
        env_id = cfg["env"]["id"] if cfg else "—"
        link = _service_link(r["type"], r["port"]) if running else ""

        row = f"  {mark_cur} {mark_tail} {nc}{r['name']:<28}{RESET} " + status_col + " "
        if layout.show_uptime:
            row += f"{DIM}{self._uptime(r, running)}{RESET}"
        if layout.show_ram:
            row += f"{DIM}{self._ram(r, running, layout.ram_map)}{RESET}"
        return row + f"{DIM}{env_id:<12}{RESET}{CYAN}{link}{RESET}\r\n"

    @staticmethod
    def _uptime(r: dict, running: bool) -> str:
        if running and r.get("started_at"):
            return f"{_fmt_uptime(time.time() - r['started_at']):<8}"
        return " " * 8

    @staticmethod
    def _ram(r: dict, running: bool, ram_map: dict) -> str:
        if running and r.get("pid") and r["pid"] in ram_map:
            return f"{_fmt_bytes(ram_map[r['pid']]):<8}"
        return " " * 8

    # -- keys --------------------------------------------------------------------------
    def _answer_cascade(self, key: bytes | None) -> None:
        if key in (b"y", b"Y") and self.ask_cascade is not None:
            from workspace_engine.run_local.main import _restart_named

            _restart_named(self.ask_cascade, self.results, self.launch_configs, self.db_cfg)
            save_state(self.results, self.launch_configs)
        self.ask_cascade = None

    def _current(self) -> dict:
        return self.results[self.cursor]

    def _quit(self, key: bytes) -> str:
        return "quit"

    def _add(self, key: bytes) -> str:
        return "add"

    def _up(self, key: bytes) -> None:
        self.cursor = max(0, self.cursor - 1)

    def _down(self, key: bytes) -> None:
        self.cursor = min(len(self.results) - 1, self.cursor + 1)

    def _mark(self, key: bytes) -> None:
        name = self._current()["name"]
        if name in self.marked:
            self.marked.discard(name)
        else:
            self.marked.add(name)

    def _stop(self, key: bytes) -> None:
        self._stop_service(self._current())
        self.marked.discard(self._current()["name"])
        save_state(self.results, self.launch_configs)

    def _restart(self, key: bytes) -> None:
        r_cur = self._current()
        self._restart_service(r_cur)
        save_state(self.results, self.launch_configs)
        from workspace_engine.run_local.main import _dependents_to_rewire

        deps = _dependents_to_rewire(self.results, self.launch_configs, {r_cur["name"]})
        if deps:
            self.ask_cascade = deps

    def _browser(self, key: bytes) -> None:
        r_cur = self._current()
        if self._is_running(r_cur):
            from workspace_engine.run_local.main import _open_browser

            _open_browser(_service_link(r_cur["type"], r_cur["port"]))

    # -- full-screen sub-views (leave the alternate screen, come back after) -----------
    def _to_cooked(self) -> None:
        _w(self.tty_fd, _ALT_OFF)
        if self.cooked_attrs is not None and tty is not None:
            termios.tcsetattr(self.tty_fd.fileno(), termios.TCSADRAIN, self.cooked_attrs)
        else:
            subprocess.run(["stty", "sane"], stdin=self.tty_fd)

    def _to_raw(self) -> None:
        if tty is not None:
            tty.setraw(self.tty_fd.fileno())
        _w(self.tty_fd, _ALT_ON)

    def _tail(self, key: bytes) -> None:
        targets = (
            [r for r in self.results if r["name"] in self.marked]
            if self.marked
            else [r for r in self.results if self._is_running(r)]
        )
        if not targets:
            return
        tail_entries = [
            {
                "name": r["name"],
                "log": LOGS_DIR / f"{r['name']}.log",
                "color": _TAIL_COLORS[i % len(_TAIL_COLORS)],
            }
            for i, r in enumerate(targets)
        ]
        self._to_cooked()
        _multi_tail(tail_entries, key == b"T", self.cooked_attrs, self.tty_fd)
        if tty is not None:
            tty.setraw(self.tty_fd.fileno())
        _w(self.tty_fd, _ALT_ON)

    def _logs(self, key: bytes) -> None:
        log_path = LOGS_DIR / f"{self._current()['name']}.log"
        if not log_path.exists():
            return
        self._to_cooked()
        print("\n  (Ctrl-C to return to the monitor)\n")
        try:
            with contextlib.suppress(KeyboardInterrupt):  # Ctrl-C is how the user returns
                subprocess.run(["tail", "-n", "+1", "-f", str(log_path)])
        finally:
            self._to_raw()

    def _errors(self, key: bytes) -> None:
        log_path = LOGS_DIR / f"{self._current()['name']}.log"
        if not log_path.exists():
            return
        self._to_cooked()
        print("\n  (Ctrl-C to go back — showing errors only)\n")
        try:
            with contextlib.suppress(KeyboardInterrupt):  # Ctrl-C is how the user returns
                self._follow_errors(log_path)
        finally:
            self._to_raw()

    @staticmethod
    def _follow_errors(log_path: Any) -> None:
        with open(log_path, errors="replace", encoding="utf-8") as fh:
            for line in fh:
                if _ERROR_RE.search(line):
                    print(line, end="")
            fh.seek(0, 2)
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                if _ERROR_RE.search(line):
                    print(line, end="", flush=True)

    def _envs(self, key: bytes) -> None:
        dump = ENVS_DIR / f"{self._current()['name']}.env"
        if not dump.exists():
            return
        self._to_cooked()
        try:
            # A missing pager just returns to the monitor.
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(["less", str(dump)])
        finally:
            self._to_raw()


def _monitor_parameters(*names: str) -> inspect.Signature:
    params = [inspect.Parameter("tty_fd", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    for name in names:
        default = None if name == "cooked_attrs" else inspect.Parameter.empty
        params.append(
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default)
        )
    return inspect.Signature(params)


# Both calling conventions are public: the original (results, launch_configs, db_cfg) and
# a ready-made MonitorSession.
_LEGACY_MONITOR = _monitor_parameters("results", "launch_configs", "db_cfg", "cooked_attrs")
_SESSION_MONITOR = _monitor_parameters("session", "cooked_attrs")


def panel_monitor(*args: Any, **kwargs: Any) -> str:
    """``panel_monitor(tty_fd, results, launch_configs, db_cfg, cooked_attrs=None)`` or
    ``panel_monitor(tty_fd, session, cooked_attrs=None)`` with a ``MonitorSession``."""
    uses_session = (len(args) > 1 and isinstance(args[1], MonitorSession)) or "session" in kwargs
    bound = (_SESSION_MONITOR if uses_session else _LEGACY_MONITOR).bind(*args, **kwargs)
    bound.apply_defaults()
    given = bound.arguments
    session = given.get("session") or MonitorSession(
        given["results"], given["launch_configs"], given["db_cfg"]
    )
    return _MonitorScreen(given["tty_fd"], session, given["cooked_attrs"]).run()


def _run_monitor_tui(results: list, launch_configs: list, db_cfg: dict) -> str:
    tty_fd = _open_tty()
    old_attrs = (
        termios.tcgetattr(tty_fd) if (tty is not None and hasattr(termios, "tcgetattr")) else None
    )
    action = "quit"
    try:
        if tty is not None:
            tty.setraw(tty_fd.fileno())
        _w(tty_fd, _ALT_ON)
        session = MonitorSession(results, launch_configs, db_cfg)
        action = panel_monitor(tty_fd, session, cooked_attrs=old_attrs)
    finally:
        # Terminal restore is best-effort: the tty state must never be left raw
        # even if closing/writing to the descriptor fails for any reason.
        with contextlib.suppress(OSError, termios.error):
            _w(tty_fd, _ALT_OFF)
            if old_attrs is not None and tty is not None:
                termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
            tty_fd.close()
    return action or "quit"
