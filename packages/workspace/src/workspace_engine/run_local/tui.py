"""
workspace_engine.run_local.tui — Interactive terminal selection and monitor screens for run_local.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import termios
import threading
import time
from types import ModuleType
from typing import Any

try:
    import tty as _tty

    tty: ModuleType | None = _tty
except ImportError:
    tty = None  # Non-Unix platform fallback


import contextlib

from workspace_engine.run_local.constants import (
    BOLD,
    CYAN,
    DIM,
    ENVIRONMENTS,
    ENVS_DIR,
    GREEN,
    LOGS_DIR,
    PIDS_DIR,
    PROJECT_CONFIG,
    RED,
    RESET,
    YELLOW,
)
from workspace_engine.run_local.discovery import (
    _fmt_bytes,
    _fmt_uptime,
    _get_kubectl_contexts,
    _kubectl_available,
    _service_link,
    resolve_local_env,
    resolve_repos_dir,
    scan_repos,
)
from workspace_engine.run_local.process_manager import (
    _HEALTH,
    _all_group_rss,
    _health_worker,
    _launch_one,
    _log_rotation_worker,
    _pid_alive,
    _status_str,
    _wait_port_free,
    load_state,
    save_state,
)
from workspace_engine.run_local.profiles import (
    load_profiles,
    save_profiles,
)
from workspace_engine.services.tui_utils import (
    draw_separator as _sep,
)
from workspace_engine.services.tui_utils import (
    open_tty as _open_tty,
)
from workspace_engine.services.tui_utils import (
    pad_colored as _pad,
)
from workspace_engine.services.tui_utils import (
    read_key as _read_key,
)
from workspace_engine.services.tui_utils import (
    write_tty as _w,
)

_TAIL_COLORS = [GREEN, CYAN, YELLOW, "\033[0;35m", "\033[0;34m", "\033[0;31m"]
_PROJECT_URL_RE = re.compile(PROJECT_CONFIG["url_pattern"])


def _read_line(tty_fd: Any, prompt: str, max_len: int = 40) -> str | None:
    buf = ""
    while True:
        display = f"\r{prompt}{buf}  \r{prompt}{buf}"
        tty_fd.write(display.encode())
        key = _read_key(tty_fd)
        if key in (b"\r", b"\n", b""):
            return buf if buf else None
        elif key == b"\x1b":
            return None
        elif key == b"\x03":
            sys.exit(130)
        elif key in (b"\x7f", b"\x08"):
            buf = buf[:-1]
        else:
            try:
                ch = key.decode("utf-8") if key else ""
                if ch.isprintable() and len(buf) < max_len:
                    buf += ch
            except (UnicodeDecodeError, ValueError):
                pass


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


def panel_source_picker(tty_fd: Any, sources: list) -> dict | None:
    cursor = 0
    while True:
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(80, cols)

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  ws run-local — Select source{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}up/down navigate   Enter select   ESC exit{RESET}\r\n\r\n")
        out.append(f"  {DIM}{'':2} {'Source':<40} {'Type'}{RESET}\r\n")
        out.append(_sep(cols, "─", bold=False) + "\r\n")

        for i, src in enumerate(sources):
            is_cur = i == cursor
            mark = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
            nc = BOLD if is_cur else ""
            kind_col = CYAN if src["kind"] == "repos" else DIM
            kind_lbl = "repositories" if src["kind"] == "repos" else "workspace"
            label = src["label"]
            if len(label) > 39:
                label = label[:36] + "..."
            out.append(f"  {mark} {nc}{label:<40}{RESET} {kind_col}{kind_lbl}{RESET}\r\n")

        out.append(_sep(cols, "─", bold=False) + "\r\n")
        out.append(f"\r\n  {DIM}{sources[cursor]['path']}{RESET}\r\n")
        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        elif key == b"\x03":
            sys.exit(130)
        elif key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(len(sources) - 1, cursor + 1)
        elif key in (b"\r", b"\n", b""):
            return sources[cursor]


def panel_profiles(tty_fd: Any) -> dict | None:
    cursor = 0
    msg = ""

    while True:
        profiles = load_profiles()
        names = list(profiles.keys())
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(80, cols)
        cursor = min(cursor, max(0, len(names) - 1))

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  Saved profiles{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}up/down navigate   Enter load   x delete   ESC back{RESET}\r\n\r\n")

        if not names:
            out.append(
                f"  {DIM}No profiles. In the selection, use g (with an empty filter) to save one.{RESET}\r\n"
            )
        else:
            for i, name in enumerate(names):
                is_cur = i == cursor
                count = len(profiles[name].get("services", []))
                mark = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
                nc = BOLD if is_cur else ""
                out.append(f"  {mark} {nc}{name:<30}{RESET}  {DIM}{count} service(s){RESET}\r\n")

        out.append(_sep(cols, "─", bold=False) + "\r\n")
        if msg:
            out.append(f"\r\n  {YELLOW}{msg}{RESET}\r\n")
            msg = ""
        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        elif key == b"\x03":
            sys.exit(130)
        elif key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(max(0, len(names) - 1), cursor + 1)
        elif key in (b"\r", b"\n", b"") and names:
            return profiles[names[cursor]]
        elif key in (b"x", b"X") and names:
            name_to_del = names[cursor]
            _w(tty_fd, f'\r\n  {YELLOW}Delete "{name_to_del}"? [y/N] {RESET}')
            confirm = _read_key(tty_fd)
            if confirm in (b"y", b"Y"):
                del profiles[name_to_del]
                save_profiles(profiles)
                cursor = min(cursor, max(0, len(profiles) - 1))
                msg = f'Profile "{name_to_del}" deleted.'


def panel_run_config(tty_fd: Any, repos: list, db_cfg: dict) -> list | None:
    env_ids = [e["id"] for e in ENVIRONMENTS]
    kubectl_ok = _kubectl_available() and bool(_get_kubectl_contexts())

    def _cycle_env(idx: int, step: int) -> int:
        for _ in range(len(ENVIRONMENTS)):
            idx = (idx + step) % len(ENVIRONMENTS)
            if ENVIRONMENTS[idx]["cluster"] is not None and not kubectl_ok:
                continue
            return idx
        return idx

    _rres, _rlcs = load_state()
    running_cfgs = {c["name"]: c for c in _rlcs}

    def _idx(lst: list, val: object, default: int = 0) -> int:
        return lst.index(val) if val in lst else default

    all_state: dict = {}
    for r in repos:
        rc = running_cfgs.get(r["name"])
        all_state[r["name"]] = {
            **r,
            "enabled": rc is not None,
            "env_idx": _idx(env_ids, rc.get("base_env", "local")) if rc else 0,
            "db_local": (rc.get("db_env") == "local") if rc else True,
            "ms_local": (rc.get("up_mode") == "auto") if rc else True,
            "has_set_env": resolve_local_env(r["path"], r["name"]) is not None,
        }

    glob = {"env_idx": 0, "db_local": True, "ms_local": True}

    cursor = 0
    scroll = 0
    error = ""
    filt = ""

    def _apply_global(field: str) -> None:
        for s in all_state.values():
            s[field] = glob[field]

    while True:
        view = [s for s in all_state.values() if not filt or filt.lower() in s["name"].lower()]
        nrows = len(view) + 1

        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(96, cols)
        lh = max(4, rows - 18)

        cursor = max(0, min(cursor, nrows - 1))
        svc_cur = max(0, cursor - 1)
        if svc_cur < scroll:
            scroll = svc_cur
        elif svc_cur >= scroll + lh:
            scroll = svc_cur - lh + 1

        def cell(text: str, width: int, color: str = "") -> str:
            pad = " " * max(0, width - len(text))
            return (f"{color}{text}{RESET}" if color else text) + pad

        def make_row(
            markchar,
            mcolor,
            chktext,
            ccolor,
            name,
            ncolor,
            env,
            ecolor,
            db,
            dcolor,
            ms,
            mscolor,
            port,
            typ,
            warn="",
        ):
            return (
                "  "
                + cell(markchar, 1, mcolor)
                + " "
                + cell(chktext, 3, ccolor)
                + " "
                + cell(name, 28, ncolor)
                + " "
                + cell(env, 14, ecolor)
                + " "
                + cell(db, 10, dcolor)
                + " "
                + cell(ms, 11, mscolor)
                + " "
                + cell(port, 7, DIM)
                + " "
                + f"{DIM}{typ}{RESET}{warn}\r\n"
            )

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  ws run-local — Configure services{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(
            f"  {DIM}up/down navigate   left/right Env   d Local DB   m Local MS   SPACE toggle   Enter   ESC{RESET}\r\n"
        )
        out.append(f"  {DIM}p  profiles   g  save profile  (only with an empty filter){RESET}\r\n")
        out.append(
            f"  {DIM}Env = where all config comes from   ·   Local DB = uses your local mongo{RESET}\r\n"
        )
        out.append(
            f"  {DIM}Local MS = wires to the microservices you started (otherwise, to the environment){RESET}\r\n"
        )
        if not kubectl_ok:
            out.append(f'  {YELLOW}⚠ kubectl not available — "local" environment only{RESET}\r\n')

        filt_display = filt if filt else f"{DIM}type to filter…{RESET}"
        out.append(f"  {DIM}Filtro:{RESET} {filt_display}{'█' if filt else ''}\r\n\r\n")
        out.append(
            "  "
            + cell("", 1)
            + " "
            + cell("", 3)
            + " "
            + cell("Service", 28, DIM)
            + " "
            + cell("Env", 14, DIM)
            + " "
            + cell("Local DB", 10, DIM)
            + " "
            + cell("Local MS", 11, DIM)
            + " "
            + cell("Port", 7, DIM)
            + " "
            + f"{DIM}Type{RESET}\r\n"
        )
        out.append(_sep(cols, "─", bold=False) + "\r\n")

        def chk(b: object) -> str:
            return "[x]" if b else "[ ]"

        gcur = cursor == 0
        out.append(
            make_row(
                "▶" if gcur else " ",
                CYAN if gcur else "",
                "···",
                DIM,
                "(all)",
                BOLD if gcur else DIM,
                env_ids[glob["env_idx"]],
                CYAN,
                chk(glob["db_local"]),
                CYAN,
                chk(glob["ms_local"]),
                CYAN,
                "",
                "",
            )
        )
        out.append(f"  {DIM}{'─' * 30}{RESET}\r\n")

        if not view:
            out.append(f'  {DIM}No results for "{filt}"{RESET}\r\n')
        else:
            for j, s in enumerate(view[scroll : scroll + lh]):
                abs_i = scroll + j
                is_cur = (abs_i + 1) == cursor
                env_id = env_ids[s["env_idx"]]
                missing_sh = env_id == "local" and not s["has_set_env"]
                if s["enabled"]:
                    mc, ccolor, ncolor = "[✔]", GREEN, (GREEN if is_cur else "")
                    ecolor = YELLOW if missing_sh else CYAN
                    dcolor = mscolor = CYAN
                    port_s = f":{s['port']}"
                else:
                    mc, ccolor, ncolor = "[ ]", DIM, DIM
                    ecolor = dcolor = mscolor = DIM
                    port_s = ""
                warn = f" {YELLOW}⚠{RESET}" if missing_sh and s["enabled"] else ""
                out.append(
                    make_row(
                        "▶" if is_cur else " ",
                        CYAN if is_cur else "",
                        mc,
                        ccolor,
                        s["name"][:27],
                        ncolor,
                        env_id,
                        ecolor,
                        chk(s["db_local"]),
                        dcolor,
                        chk(s["ms_local"]),
                        mscolor,
                        port_s,
                        s["type"],
                        warn,
                    )
                )

        out.append(_sep(cols, "─", bold=False) + "\r\n")

        enabled = [s["name"] for s in all_state.values() if s["enabled"]]
        total = len(all_state)
        footer = f"Selected: {len(enabled)}"
        if filt:
            footer += f"  |  Showing {len(view)}/{total}"
        if enabled:
            out.append(
                f"\r\n  {BOLD}{footer}{RESET}  {GREEN}{', '.join(enabled[:5])}{'…' if len(enabled) > 5 else ''}{RESET}\r\n"
            )
        else:
            out.append(f"\r\n  {DIM}{footer}{RESET}\r\n")

        if error:
            out.append(f"\r\n  {RED}{error}{RESET}\r\n")
            error = ""

        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)

        target = None if cursor == 0 else view[cursor - 1]

        if key == b"\x03":
            sys.exit(130)
        elif key == b"\x1b":
            if filt:
                filt = ""
                cursor = 0
                scroll = 0
            else:
                return None
        elif key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(nrows - 1, cursor + 1)
        elif key in (b"\x1b[C", b"\x1b[D"):
            step = 1 if key == b"\x1b[C" else -1
            t = target
            if t is None:
                glob["env_idx"] = _cycle_env(glob["env_idx"], step)
                _apply_global("env_idx")
            else:
                t["env_idx"] = _cycle_env(t["env_idx"], step)
        elif key in (b"d", b"D"):
            t = target
            if t is None:
                glob["db_local"] = not glob["db_local"]
                _apply_global("db_local")
            else:
                t["db_local"] = not t["db_local"]
        elif key in (b"m", b"M"):
            t = target
            if t is None:
                glob["ms_local"] = not glob["ms_local"]
                _apply_global("ms_local")
            else:
                t["ms_local"] = not t["ms_local"]
        elif key == b" ":
            t = target
            if t is None:
                newval = not all(s["enabled"] for s in view) if view else True
                for s in view:
                    s["enabled"] = newval
            else:
                t["enabled"] = not t["enabled"]
        elif key in (b"\x7f", b"\x08"):
            filt = filt[:-1]
            cursor = 0
            scroll = 0
        elif key in (b"p", b"P") and not filt:
            profile = panel_profiles(tty_fd)
            if profile:
                for s in all_state.values():
                    s["enabled"] = False
                skipped = []
                for svc_cfg in profile.get("services", []):
                    s = all_state.get(svc_cfg["name"])
                    if not s:
                        skipped.append(svc_cfg["name"])
                        continue
                    s["enabled"] = True
                    base_env = svc_cfg.get("base_env", "local")
                    s["env_idx"] = env_ids.index(base_env) if base_env in env_ids else 0
                    db_env = svc_cfg.get("db_env", "local")
                    s["db_local"] = db_env == "local"
                    s["ms_local"] = svc_cfg.get("up_mode", "auto") == "auto"
                error = "✔ Profile loaded." + (f" Skipped: {', '.join(skipped)}" if skipped else "")
        elif key in (b"g", b"G") and not filt:
            sel = [s for s in all_state.values() if s["enabled"]]
            if not sel:
                error = "❌ Select at least one service to save."
            else:
                cols2, rows2 = shutil.get_terminal_size(fallback=(80, 24))
                _w(tty_fd, f"\033[{rows2};0H  {DIM}Profile name:{RESET} ")
                pname = _read_line(tty_fd, "")
                if pname:
                    profiles = load_profiles()
                    profiles[pname] = {
                        "services": [
                            {
                                "name": s["name"],
                                "base_env": env_ids[s["env_idx"]],
                                "db_env": "local" if s["db_local"] else env_ids[s["env_idx"]],
                                "up_mode": "auto" if s["ms_local"] else env_ids[s["env_idx"]],
                            }
                            for s in sel
                        ]
                    }
                    save_profiles(profiles)
                    error = f'✔ Profile "{pname}" saved ({len(sel)} services).'
                else:
                    error = "Save cancelled."
        elif key in (b"\r", b"\n", b""):
            sel = [s for s in all_state.values() if s["enabled"]]
            if not sel:
                error = "❌ Select at least one service."
                continue
            problems = []
            for s in sel:
                env_id = env_ids[s["env_idx"]]
                if env_id == "local" and not s["has_set_env"]:
                    problems.append(f"{s['name']}: no set-env (local environment)")
                elif env_id != "local" and not kubectl_ok:
                    problems.append(f"{s['name']}: kubectl not avail. ({env_id})")
            if problems:
                error = "⚠ " + " | ".join(problems[:2]) + (" …" if len(problems) > 2 else "")
                continue
            return [
                {
                    **s,
                    "env": ENVIRONMENTS[s["env_idx"]],
                    "base_env": env_ids[s["env_idx"]],
                    "db_env": "local" if s["db_local"] else env_ids[s["env_idx"]],
                    "up_mode": "auto" if s["ms_local"] else env_ids[s["env_idx"]],
                }
                for s in sel
            ]
        else:
            try:
                ch = key.decode("utf-8") if key else ""
                if ch.isprintable() and len(ch) == 1:
                    filt += ch
                    cursor = 0
                    scroll = 0
            except (UnicodeDecodeError, ValueError):
                pass


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
            for target in (-r["pid"], r["pid"]):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(target, 15)
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
                if key in (b"y", b"Y", b"s", b"S"):
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
