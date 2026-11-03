"""Part of ``tui`` (split out, no behavior change)."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
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

_STAY = object()  # the key was handled and the screen keeps running


def _cycle_env(idx: int, step: int, kubectl_ok: bool) -> int:
    for _ in range(len(get_environments())):
        idx = (idx + step) % len(get_environments())
        if get_environments()[idx]["cluster"] is not None and not kubectl_ok:
            continue
        return idx
    return idx


def _idx(lst: list, val: object, default: int = 0) -> int:
    return lst.index(val) if val in lst else default


def _initial_state(repos: list, env_ids: list) -> dict:
    _rres, _rlcs = load_state()
    running_cfgs = {c["name"]: c for c in _rlcs}
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
    return all_state


def _cell(text: str, width: int, color: str = "") -> str:
    pad = " " * max(0, width - len(text))
    return (f"{color}{text}{RESET}" if color else text) + pad


def _chk(b: object) -> str:
    return "[x]" if b else "[ ]"


@dataclass(frozen=True)
class _Row:
    """One table row: each column is a (text, color) pair."""

    mark: tuple[str, str]
    check: tuple[str, str]
    name: tuple[str, str]
    env: tuple[str, str]
    db: tuple[str, str]
    ms: tuple[str, str]
    port: str
    typ: str
    warn: str = ""

    def render(self) -> str:
        return (
            "  "
            + _cell(self.mark[0], 1, self.mark[1])
            + " "
            + _cell(self.check[0], 3, self.check[1])
            + " "
            + _cell(self.name[0], 28, self.name[1])
            + " "
            + _cell(self.env[0], 14, self.env[1])
            + " "
            + _cell(self.db[0], 10, self.db[1])
            + " "
            + _cell(self.ms[0], 11, self.ms[1])
            + " "
            + _cell(self.port, 7, DIM)
            + " "
            + f"{DIM}{self.typ}{RESET}{self.warn}\r\n"
        )


_HELP_LINES = (
    "up/down navigate   left/right Env   d Local DB   m Local MS   SPACE toggle   Enter   ESC",
    "p  profiles   g  save profile  (only with an empty filter)",
    "Env = where all config comes from   ·   Local DB = uses your local mongo",
    "Local MS = wires to the microservices you started (otherwise, to the environment)",
)


class _RunConfigScreen:
    """State and key handling of the "Configure services" screen."""

    def __init__(self, tty_fd: Any, repos: list) -> None:
        self.tty_fd = tty_fd
        self.env_ids = [e["id"] for e in get_environments()]
        self.kubectl_ok = _kubectl_available() and bool(_get_kubectl_contexts())
        self.all_state = _initial_state(repos, self.env_ids)
        self.glob = {"env_idx": 0, "db_local": True, "ms_local": True}
        self.cursor = 0
        self.scroll = 0
        self.error = ""
        self.filt = ""
        self.view: list = []
        self.nrows = 0
        self.cols = 96
        self.lh = 4

    def run(self) -> list | None:
        while True:
            self._layout()
            _w(self.tty_fd, self._screen())
            self.error = ""
            outcome = self._handle(_read_key(self.tty_fd))
            if outcome is not _STAY:
                return outcome  # type: ignore[return-value]

    # -- layout and drawing ------------------------------------------------------------
    def _layout(self) -> None:
        needle = self.filt.lower()
        self.view = [
            s for s in self.all_state.values() if not needle or needle in s["name"].lower()
        ]
        self.nrows = len(self.view) + 1
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        self.cols = max(96, cols)
        self.lh = max(4, rows - 18)
        self.cursor = max(0, min(self.cursor, self.nrows - 1))
        svc_cur = max(0, self.cursor - 1)
        if svc_cur < self.scroll:
            self.scroll = svc_cur
        elif svc_cur >= self.scroll + self.lh:
            self.scroll = svc_cur - self.lh + 1

    def _screen(self) -> str:
        out = ["\033[H\033[J", *self._header(), *self._table(), *self._footer()]
        return "".join(out)

    def _header(self) -> list[str]:
        out = [_sep(self.cols) + "\r\n"]
        out.append(f"{BOLD}  ws run-local — Configure services{RESET}\r\n")
        out.append(_sep(self.cols) + "\r\n")
        out.extend(f"  {DIM}{line}{RESET}\r\n" for line in _HELP_LINES)
        if not self.kubectl_ok:
            out.append(f'  {YELLOW}⚠ kubectl not available — "local" environment only{RESET}\r\n')
        filt_display = self.filt if self.filt else f"{DIM}type to filter…{RESET}"
        out.append(f"  {DIM}Filtro:{RESET} {filt_display}{'█' if self.filt else ''}\r\n\r\n")
        return out

    def _table(self) -> list[str]:
        out = [self._column_titles(), _sep(self.cols, "─", bold=False) + "\r\n"]
        out.append(self._global_row())
        out.append(f"  {DIM}{'─' * 30}{RESET}\r\n")
        if not self.view:
            out.append(f'  {DIM}No results for "{self.filt}"{RESET}\r\n')
        else:
            visible = self.view[self.scroll : self.scroll + self.lh]
            for j, s in enumerate(visible):
                out.append(self._service_row(s, (self.scroll + j + 1) == self.cursor))
        out.append(_sep(self.cols, "─", bold=False) + "\r\n")
        return out

    @staticmethod
    def _column_titles() -> str:
        titles = (("", 1, ""), ("", 3, ""), ("Service", 28, DIM), ("Env", 14, DIM))
        titles += (("Local DB", 10, DIM), ("Local MS", 11, DIM), ("Port", 7, DIM))
        return "  " + " ".join(_cell(*t) for t in titles) + f" {DIM}Type{RESET}\r\n"

    def _global_row(self) -> str:
        gcur = self.cursor == 0
        return _Row(
            ("▶" if gcur else " ", CYAN if gcur else ""),
            ("···", DIM),
            ("(all)", BOLD if gcur else DIM),
            (self.env_ids[self.glob["env_idx"]], CYAN),
            (_chk(self.glob["db_local"]), CYAN),
            (_chk(self.glob["ms_local"]), CYAN),
            "",
            "",
        ).render()

    def _service_row(self, s: dict, is_cur: bool) -> str:
        env_id = self.env_ids[s["env_idx"]]
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
        return _Row(
            ("▶" if is_cur else " ", CYAN if is_cur else ""),
            (mc, ccolor),
            (s["name"][:27], ncolor),
            (env_id, ecolor),
            (_chk(s["db_local"]), dcolor),
            (_chk(s["ms_local"]), mscolor),
            port_s,
            s["type"],
            warn,
        ).render()

    def _footer(self) -> list[str]:
        enabled = [s["name"] for s in self.all_state.values() if s["enabled"]]
        footer = f"Selected: {len(enabled)}"
        if self.filt:
            footer += f"  |  Showing {len(self.view)}/{len(self.all_state)}"
        if enabled:
            names = f"{', '.join(enabled[:5])}{'…' if len(enabled) > 5 else ''}"
            out = [f"\r\n  {BOLD}{footer}{RESET}  {GREEN}{names}{RESET}\r\n"]
        else:
            out = [f"\r\n  {DIM}{footer}{RESET}\r\n"]
        if self.error:
            out.append(f"\r\n  {RED}{self.error}{RESET}\r\n")
        return out

    # -- keys --------------------------------------------------------------------------
    def _target(self) -> dict | None:
        return None if self.cursor == 0 else self.view[self.cursor - 1]

    def _handle(self, key: bytes) -> object:
        if key == b"\x03":
            sys.exit(130)
        if key == b"\x1b":
            return self._escape()
        if key in (b"\r", b"\n", b""):
            return self._submit()
        if not (self._navigate(key) or self._edit(key)):
            self._profile_or_filter(key)
        return _STAY

    def _escape(self) -> object:
        if not self.filt:
            return None
        self.filt = ""
        self.cursor = 0
        self.scroll = 0
        return _STAY

    def _navigate(self, key: bytes) -> bool:
        if key == b"\x1b[A":
            self.cursor = max(0, self.cursor - 1)
        elif key == b"\x1b[B":
            self.cursor = min(self.nrows - 1, self.cursor + 1)
        else:
            return False
        return True

    def _toggle(self, field: str) -> None:
        t = self._target()
        if t is None:
            self.glob[field] = not self.glob[field]
            for s in self.all_state.values():
                s[field] = self.glob[field]
        else:
            t[field] = not t[field]

    def _edit(self, key: bytes) -> bool:
        if key in (b"\x1b[C", b"\x1b[D"):
            self._cycle(1 if key == b"\x1b[C" else -1)
        elif key in (b"d", b"D"):
            self._toggle("db_local")
        elif key in (b"m", b"M"):
            self._toggle("ms_local")
        elif key == b" ":
            self._toggle_enabled()
        else:
            return False
        return True

    def _cycle(self, step: int) -> None:
        t = self._target()
        if t is None:
            self.glob["env_idx"] = _cycle_env(self.glob["env_idx"], step, self.kubectl_ok)
            for s in self.all_state.values():
                s["env_idx"] = self.glob["env_idx"]
        else:
            t["env_idx"] = _cycle_env(t["env_idx"], step, self.kubectl_ok)

    def _toggle_enabled(self) -> None:
        t = self._target()
        if t is not None:
            t["enabled"] = not t["enabled"]
            return
        newval = not all(s["enabled"] for s in self.view) if self.view else True
        for s in self.view:
            s["enabled"] = newval

    def _profile_or_filter(self, key: bytes) -> None:
        if key in (b"p", b"P") and not self.filt:
            self._load_profile()
        elif key in (b"g", b"G") and not self.filt:
            self._save_profile()
        elif key in (b"\x7f", b"\x08"):
            self.filt = self.filt[:-1]
            self.cursor = 0
            self.scroll = 0
        else:
            self._type(key)

    def _type(self, key: bytes) -> None:
        try:
            ch = key.decode("utf-8") if key else ""
        except UnicodeDecodeError:
            return  # not text (a partial escape sequence): ignore the key
        if ch.isprintable() and len(ch) == 1:
            self.filt += ch
            self.cursor = 0
            self.scroll = 0

    def _load_profile(self) -> None:
        profile = panel_profiles(self.tty_fd)
        if not profile:
            return
        for s in self.all_state.values():
            s["enabled"] = False
        skipped = []
        for svc_cfg in profile.get("services", []):
            s = self.all_state.get(svc_cfg["name"])
            if not s:
                skipped.append(svc_cfg["name"])
                continue
            self._apply_service_profile(s, svc_cfg)
        self.error = "✔ Profile loaded." + (f" Skipped: {', '.join(skipped)}" if skipped else "")

    def _apply_service_profile(self, s: dict, svc_cfg: dict) -> None:
        s["enabled"] = True
        base_env = svc_cfg.get("base_env", "local")
        s["env_idx"] = self.env_ids.index(base_env) if base_env in self.env_ids else 0
        s["db_local"] = svc_cfg.get("db_env", "local") == "local"
        s["ms_local"] = svc_cfg.get("up_mode", "auto") == "auto"

    def _selected(self) -> list:
        return [s for s in self.all_state.values() if s["enabled"]]

    def _launch_fields(self, s: dict) -> dict:
        env_id = self.env_ids[s["env_idx"]]
        return {
            "base_env": env_id,
            "db_env": "local" if s["db_local"] else env_id,
            "up_mode": "auto" if s["ms_local"] else env_id,
        }

    def _save_profile(self) -> None:
        sel = self._selected()
        if not sel:
            self.error = "❌ Select at least one service to save."
            return
        _cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        _w(self.tty_fd, f"\033[{rows};0H  {DIM}Profile name:{RESET} ")
        pname = _read_line(self.tty_fd, "")
        if not pname:
            self.error = "Save cancelled."
            return
        profiles = load_profiles()
        profiles[pname] = {"services": [{"name": s["name"], **self._launch_fields(s)} for s in sel]}
        save_profiles(profiles)
        self.error = f'✔ Profile "{pname}" saved ({len(sel)} services).'

    def _problems(self, sel: list) -> list[str]:
        problems = []
        for s in sel:
            env_id = self.env_ids[s["env_idx"]]
            if env_id == "local" and not s["has_set_env"]:
                problems.append(f"{s['name']}: no set-env (local environment)")
            elif env_id != "local" and not self.kubectl_ok:
                problems.append(f"{s['name']}: kubectl not avail. ({env_id})")
        return problems

    def _submit(self) -> object:
        sel = self._selected()
        if not sel:
            self.error = "❌ Select at least one service."
            return _STAY
        problems = self._problems(sel)
        if problems:
            self.error = "⚠ " + " | ".join(problems[:2]) + (" …" if len(problems) > 2 else "")
            return _STAY
        return [
            {**s, "env": get_environments()[s["env_idx"]], **self._launch_fields(s)} for s in sel
        ]


def panel_run_config(tty_fd: Any, repos: list, db_cfg: dict) -> list | None:
    return _RunConfigScreen(tty_fd, repos).run()
