"""Part of ``tui`` (split out, no behavior change)."""

from __future__ import annotations

import shutil
import sys
from typing import Any

from workspace_engine.run_local.constants import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    get_environments,
)
from workspace_engine.run_local.discovery import (
    _get_kubectl_contexts,
    _kubectl_available,
    resolve_local_env,
)
from workspace_engine.run_local.process_manager import load_state
from workspace_engine.run_local.profiles import load_profiles, save_profiles
from workspace_engine.services.tui_utils import draw_separator as _sep
from workspace_engine.services.tui_utils import read_key as _read_key
from workspace_engine.services.tui_utils import write_tty as _w

from .tui_panels import _read_line, panel_profiles


def panel_run_config(tty_fd: Any, repos: list, db_cfg: dict) -> list | None:
    env_ids = [e["id"] for e in get_environments()]
    kubectl_ok = _kubectl_available() and bool(_get_kubectl_contexts())

    def _cycle_env(idx: int, step: int) -> int:
        for _ in range(len(get_environments())):
            idx = (idx + step) % len(get_environments())
            if get_environments()[idx]["cluster"] is not None and not kubectl_ok:
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
                    "env": get_environments()[s["env_idx"]],
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
