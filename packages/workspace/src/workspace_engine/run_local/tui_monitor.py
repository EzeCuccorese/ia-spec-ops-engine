"""Part of ``tui`` (split out, no behavior change)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import termios
import threading
import time
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


def _multi_tail(entries: list, filter_errors: bool, cooked_attrs: Any, tty_fd: Any) -> None:
    _w(tty_fd, "\033[?1049l\033[?25h")
    if cooked_attrs is not None and tty is not None:
        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)

    error_re = re.compile(r"ERROR|FATAL|Exception|error:", re.IGNORECASE) if filter_errors else None
    suffix = " — errors only" if filter_errors else ""
    print(f"\n  Combined tail{suffix}  |  Ctrl-C to return to the monitor\n")

    max_name = max((len(e["name"]) for e in entries), default=10)

    handles = []
    for e in entries:
        try:
            fh = open(e["log"], errors="replace", encoding="utf-8")  # noqa: SIM115
            fh.seek(0, 2)
            handles.append({"fh": fh, "pos": fh.tell(), "log": e["log"]})
        except OSError:
            handles.append({"fh": None, "pos": 0, "log": e["log"]})

    try:
        while True:
            for _i, (e, h) in enumerate(zip(entries, handles, strict=False)):
                fh = h["fh"]
                if fh is None:
                    continue
                try:
                    current_size = os.path.getsize(h["log"])
                    if current_size < h["pos"]:
                        fh.seek(0)
                        h["pos"] = 0
                except OSError:
                    pass
                while True:
                    line = fh.readline()
                    if not line:
                        break
                    h["pos"] = fh.tell()
                    if error_re and not error_re.search(line):
                        continue
                    prefix = f"{e['color']}{e['name']:<{max_name}}{RESET}"
                    print(f"{prefix} {DIM}|{RESET} {line}", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for h in handles:
            if h["fh"]:
                h["fh"].close()
        if tty is not None:
            tty.setraw(tty_fd.fileno())
        _w(tty_fd, "\033[?25l\033[?1049h")


def panel_monitor(
    tty_fd: Any, results: list, launch_configs: list, db_cfg: dict, cooked_attrs: Any = None
) -> str:
    cursor = 0
    marked: set = set()
    ask_cascade: list | None = None

    def _is_running(r: dict) -> bool:
        return _pid_alive(r.get("pid"))

    def _stop_service(r: dict) -> None:
        if r.get("pid"):
            _terminate(r["pid"])
            (PIDS_DIR / f"{r['name']}.pid").unlink(missing_ok=True)
            r["pid"] = None
            _HEALTH.pop(r["name"], None)

    def _restart_service(r: dict) -> None:
        _stop_service(r)
        if not _wait_port_free(r["port"]):
            r["error"] = f"Port {r['port']} was not freed in time"
            return
        cfg = next((c for c in launch_configs if c["name"] == r["name"]), None)
        if not cfg:
            return
        running_ports = {c["name"]: c["port"] for c in launch_configs}
        pid, err, started_at, _ = _launch_one(cfg, running_ports, db_cfg)
        r["pid"] = pid
        r["error"] = err
        r["started_at"] = started_at

    stop_health = threading.Event()
    health_thread = threading.Thread(
        target=_health_worker, args=(results, stop_health), daemon=True
    )
    health_thread.start()
    log_rotation_thread = threading.Thread(
        target=_log_rotation_worker, args=(stop_health,), daemon=True
    )
    log_rotation_thread.start()

    try:
        while True:
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            cols = max(80, cols)
            lh = max(4, rows - 14)

            show_uptime = cols >= 90
            show_ram = cols >= 110

            running_pids = [r["pid"] for r in results if r.get("pid")]
            ram_map = _all_group_rss(running_pids) if show_ram and running_pids else {}

            out = ["\033[H\033[J"]
            out.append(_sep(cols) + "\r\n")
            out.append(f"{BOLD}  Service monitor{RESET}\r\n")
            out.append(_sep(cols) + "\r\n")
            out.append(
                f"  {DIM}up/down nav   SPACE mark   t tail   T tail-err   Enter logs   l err   e envs   o browser{RESET}\r\n"
            )
            out.append(
                f"  {DIM}s stop   r restart   a add   q quit  (services keep running on exit){RESET}\r\n\r\n"
            )

            hdr = (
                f"  {' '} {'✓'} {'Service':<28} " + _pad("Status", 13, f"{DIM}Status{RESET}") + " "
            )
            if show_uptime:
                hdr += f"{DIM}{'Uptime':<8}{RESET}"
            if show_ram:
                hdr += f"{DIM}{'RAM':<8}{RESET}"
            hdr += f"{DIM}{'Envs':<12}{RESET}{DIM}URL{RESET}\r\n"
            out.append(hdr)
            out.append(_sep(cols, "─", bold=False) + "\r\n")

            scroll = 0
            if cursor < scroll:
                scroll = cursor
            elif cursor >= scroll + lh:
                scroll = cursor - lh + 1

            wiring_detail = ""
            for i, r in enumerate(results[scroll : scroll + lh]):
                abs_i = scroll + i
                is_cur = abs_i == cursor
                running = _is_running(r)
                is_marked = r["name"] in marked

                mark_cur = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
                mark_tail = f"{CYAN}✓{RESET}" if is_marked else " "
                nc = BOLD if is_cur else ""

                plain_st, colored_st = _status_str(r["name"], r.get("pid"))
                status_col = _pad(plain_st, 13, colored_st)

                cfg = next((c for c in launch_configs if c["name"] == r["name"]), None)
                env_id = cfg["env"]["id"] if cfg else "—"
                link = _service_link(r["type"], r["port"]) if running else ""

                uptime_s = " " * 8
                if running and r.get("started_at"):
                    uptime_s = f"{_fmt_uptime(time.time() - r['started_at']):<8}"

                ram_s = " " * 8
                if running and r.get("pid") and r["pid"] in ram_map:
                    ram_s = f"{_fmt_bytes(ram_map[r['pid']]):<8}"

                row = f"  {mark_cur} {mark_tail} {nc}{r['name']:<28}{RESET} " + status_col + " "
                if show_uptime:
                    row += f"{DIM}{uptime_s}{RESET}"
                if show_ram:
                    row += f"{DIM}{ram_s}{RESET}"
                row += f"{DIM}{env_id:<12}{RESET}{CYAN}{link}{RESET}\r\n"
                out.append(row)

                if is_cur and cfg:
                    wiring = cfg.get("wiring", {})
                    up_mode = cfg.get("up_mode", "auto")
                    if wiring:
                        local_s = ", ".join(f"{n}:{p}" for n, p in wiring.items())
                        wiring_detail = f"→ local: {local_s} · rest: {env_id}"
                    elif up_mode != "auto":
                        wiring_detail = f"→ all to: {up_mode}"
                    else:
                        wiring_detail = ""

            out.append(_sep(cols, "─", bold=False) + "\r\n")

            if wiring_detail:
                out.append(f"  {DIM}{wiring_detail}{RESET}\r\n")

            if ask_cascade:
                out.append(
                    f"\r\n  {BOLD}Dependents detected:{RESET} {DIM}{', '.join(ask_cascade)}{RESET}\r\n"
                )
                out.append(f"  {YELLOW}Restart them too? [y = yes · any other key = no]{RESET} ")

            out.append(f"\r\n  {DIM}Logs: {LOGS_DIR}/{RESET}\r\n")
            _w(tty_fd, "".join(out))

            key = _read_key(tty_fd) if ask_cascade else _read_key(tty_fd, timeout=2.0)

            if ask_cascade is not None:
                if key in (b"y", b"Y"):
                    from workspace_engine.run_local.main import _restart_named

                    _restart_named(ask_cascade, results, launch_configs, db_cfg)
                    save_state(results, launch_configs)
                ask_cascade = None
                continue

            if key is None:
                continue

            if key == b"\x03" or key in (b"q", b"Q"):
                return "quit"
            elif key in (b"a", b"A"):
                return "add"
            elif key == b"\x1b[A":
                cursor = max(0, cursor - 1)
            elif key == b"\x1b[B":
                cursor = min(len(results) - 1, cursor + 1)
            elif key == b" ":
                name = results[cursor]["name"]
                if name in marked:
                    marked.discard(name)
                else:
                    marked.add(name)
            elif key in (b"s", b"S"):
                _stop_service(results[cursor])
                marked.discard(results[cursor]["name"])
                save_state(results, launch_configs)
            elif key in (b"r", b"R"):
                r_cur = results[cursor]
                _restart_service(r_cur)
                save_state(results, launch_configs)
                from workspace_engine.run_local.main import _dependents_to_rewire

                deps = _dependents_to_rewire(results, launch_configs, {r_cur["name"]})
                if deps:
                    ask_cascade = deps
            elif key in (b"o", b"O"):
                r_cur = results[cursor]
                if _is_running(r_cur):
                    from workspace_engine.run_local.main import _open_browser

                    _open_browser(_service_link(r_cur["type"], r_cur["port"]))
            elif key in (b"t", b"T"):
                filter_errors = key == b"T"
                targets = (
                    [r for r in results if r["name"] in marked]
                    if marked
                    else [r for r in results if _is_running(r)]
                )
                if targets:
                    tail_entries = [
                        {
                            "name": r["name"],
                            "log": LOGS_DIR / f"{r['name']}.log",
                            "color": _TAIL_COLORS[i % len(_TAIL_COLORS)],
                        }
                        for i, r in enumerate(targets)
                    ]
                    _w(tty_fd, "\033[?1049l\033[?25h")
                    if cooked_attrs is not None and tty is not None:
                        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)
                    else:
                        subprocess.run(["stty", "sane"], stdin=tty_fd)
                    _multi_tail(tail_entries, filter_errors, cooked_attrs, tty_fd)
                    if tty is not None:
                        tty.setraw(tty_fd.fileno())
                    _w(tty_fd, "\033[?25l\033[?1049h")
            elif key in (b"\r", b"\n", b""):
                r = results[cursor]
                log_path = LOGS_DIR / f"{r['name']}.log"
                if log_path.exists():
                    _w(tty_fd, "\033[?1049l\033[?25h")
                    if cooked_attrs is not None and tty is not None:
                        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)
                    else:
                        subprocess.run(["stty", "sane"], stdin=tty_fd)
                    print("\n  (Ctrl-C to return to the monitor)\n")
                    try:
                        subprocess.run(["tail", "-n", "+1", "-f", str(log_path)])
                    except KeyboardInterrupt:
                        pass
                    finally:
                        if tty is not None:
                            tty.setraw(tty_fd.fileno())
                        _w(tty_fd, "\033[?25l\033[?1049h")
            elif key in (b"l", b"L"):
                r = results[cursor]
                log_path = LOGS_DIR / f"{r['name']}.log"
                if log_path.exists():
                    _w(tty_fd, "\033[?1049l\033[?25h")
                    if cooked_attrs is not None and tty is not None:
                        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)
                    else:
                        subprocess.run(["stty", "sane"], stdin=tty_fd)
                    print("\n  (Ctrl-C to go back — showing errors only)\n")
                    try:
                        error_re = re.compile(r"ERROR|FATAL|Exception|error:", re.IGNORECASE)
                        with open(log_path, errors="replace", encoding="utf-8") as fh:
                            fh.seek(0, 2)
                            fh.tell()
                            fh.seek(0)
                            for line in fh:
                                if error_re.search(line):
                                    print(line, end="")
                            fh.seek(0, 2)
                            fh.tell()
                            while True:
                                line = fh.readline()
                                if not line:
                                    time.sleep(0.2)
                                    continue
                                if error_re.search(line):
                                    print(line, end="", flush=True)
                    except KeyboardInterrupt:
                        pass
                    finally:
                        if tty is not None:
                            tty.setraw(tty_fd.fileno())
                        _w(tty_fd, "\033[?25l\033[?1049h")
            elif key in (b"e", b"E"):
                r = results[cursor]
                dump = ENVS_DIR / f"{r['name']}.env"
                if dump.exists():
                    _w(tty_fd, "\033[?1049l\033[?25h")
                    if cooked_attrs is not None and tty is not None:
                        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, cooked_attrs)
                    else:
                        subprocess.run(["stty", "sane"], stdin=tty_fd)
                    try:
                        subprocess.run(["less", str(dump)])
                    except (OSError, subprocess.SubprocessError):
                        pass
                    finally:
                        if tty is not None:
                            tty.setraw(tty_fd.fileno())
                        _w(tty_fd, "\033[?25l\033[?1049h")
    finally:
        stop_health.set()


def _run_monitor_tui(results: list, launch_configs: list, db_cfg: dict) -> str:
    tty_fd = _open_tty()
    old_attrs = (
        termios.tcgetattr(tty_fd) if (tty is not None and hasattr(termios, "tcgetattr")) else None
    )
    action = "quit"
    try:
        if tty is not None:
            tty.setraw(tty_fd.fileno())
        _w(tty_fd, "\033[?25l\033[?1049h")
        action = panel_monitor(tty_fd, results, launch_configs, db_cfg, cooked_attrs=old_attrs)
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
    return action or "quit"
