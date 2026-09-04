#!/usr/bin/env python3
"""
workspace_engine.services.benchmark_display — Renderizador visual en tiempo real y reporte final para unit-test-benchmark.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

_WORKSPACE_DIR = ""


def _detect_type(repo: str) -> str:
    """Detecta el tipo de tecnología del repositorio desde el directorio."""
    workspace = _WORKSPACE_DIR
    d = os.path.join(workspace, "repositories", repo) if workspace else ""
    if not d or not os.path.isdir(d):
        return ""
    if os.path.exists(os.path.join(d, "gradlew")) or os.path.exists(
        os.path.join(d, "build.gradle")
    ):
        return "gradle"
    if os.path.exists(os.path.join(d, "pom.xml")):
        return "maven"
    if os.path.exists(os.path.join(d, "go.mod")):
        return "go"
    pkg = os.path.join(d, "package.json")
    if os.path.exists(pkg):
        try:
            with open(pkg, encoding="utf-8") as f:
                data = json.load(f)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "next" in deps:
                return "next"
            if "vite" in deps or "vitest" in deps:
                return "vite"
            return "node"
        except Exception:
            return "node"
    return "?"


STATUS_ICON = {
    "pending": "⏸️",
    "running": "🔄",
    "green": "✅",
    "red_code": "❌",
    "red_infra": "⚠️",
    "no_tests": "0️⃣",
}

STATUS_COLOR = {
    "pending": "dim",
    "running": "cyan",
    "green": "green",
    "red_code": "red",
    "red_infra": "yellow",
    "no_tests": "dim",
}

STATUS_FRIENDLY = {
    "pending": "pendiente",
    "running": "ejecutando",
    "green": "pasó",
    "red_code": "fallaron tests",
    "red_infra": "error infra",
    "no_tests": "sin tests",
}


def _friendly_status(status: str) -> str:
    return STATUS_FRIENDLY.get(status, status or "")


def _fmt_elapsed(secs: float) -> str:
    s = int(secs)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _fmt_phase_elapsed(secs: float) -> str:
    s = int(secs)
    m, s = divmod(s, 60)
    if m >= 60:
        return f"{m // 60}h{m % 60:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_secs_py(s) -> str:
    try:
        s = float(s or 0)
    except (ValueError, TypeError):
        return ""
    if s == 0:
        return ""
    total = int(s)
    return f"{total // 60:02d}:{total % 60:02d}"


def _fmt_gross_net(net_display: str, gross_secs) -> str:
    if not net_display:
        return net_display
    parts = net_display.split()
    net_time = parts[-1] if parts else ""
    prefix = " ".join(parts[:-1])
    gross = _fmt_secs_py(gross_secs)
    if not gross or gross == net_time:
        return net_display
    lead = f"{prefix} " if prefix else ""
    return f"{lead}{gross} ({net_time})"


def _sorted_repos(repos: list[str], statuses: dict) -> list[str]:
    orig_idx = {r: i for i, r in enumerate(repos)}

    def key(repo):
        s = statuses.get(repo, {})
        status = s.get("status", "pending")
        if status == "green":
            return (0, s.get("_done_epoch", float("inf")))
        elif status in ("red_code", "red_infra", "no_tests"):
            return (1, s.get("_done_epoch", float("inf")))
        elif status == "running":
            return (2, float(s.get("repo_start_epoch", 0)))
        else:
            return (3, orig_idx.get(repo, 0))

    return sorted(repos, key=key)


def _select_visible(ordered: list[str], statuses: dict, keep: int) -> tuple[list[str], int]:
    if len(ordered) <= keep:
        return ordered, 0

    def _st(r):
        return statuses.get(r, {}).get("status", "pending")

    running = [r for r in ordered if _st(r) == "running"]
    done = [r for r in ordered if _st(r) in ("green", "red_code", "red_infra", "no_tests")]
    pending = [r for r in ordered if _st(r) == "pending"]

    selected: list[str] = []
    for group in (running, list(reversed(done)), pending):
        for r in group:
            if len(selected) >= keep:
                break
            selected.append(r)

    sel = set(selected)
    visible = [r for r in ordered if r in sel]
    return visible, len(ordered) - len(visible)


def build_table(
    repos: list[str], statuses: dict, repeat: bool, max_rows: int | None = None
) -> Table:
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    t.add_column("#", width=2, no_wrap=True)
    t.add_column("", width=2, no_wrap=True)
    t.add_column("REPO", min_width=22, max_width=30, no_wrap=True)
    t.add_column("TIPO", width=6, no_wrap=True)
    t.add_column("TESTS", width=8, no_wrap=True)
    t.add_column("PRE-I", width=8, no_wrap=True)
    t.add_column("INSTALL", width=14, no_wrap=True)
    t.add_column("BUILD", width=6, no_wrap=True)
    t.add_column("PRE-C", width=8, no_wrap=True)
    t.add_column("COLD", width=18, no_wrap=True)
    if repeat:
        t.add_column("PRE-W", width=8, no_wrap=True)
        t.add_column("WARM", width=18, no_wrap=True)
    t.add_column("TOTAL", width=7, no_wrap=True)
    t.add_column("HORA", width=8, no_wrap=True)
    t.add_column("ESTADO", min_width=13, no_wrap=True, overflow="ellipsis")

    ordered = _sorted_repos(repos, statuses)
    hidden = 0
    if max_rows is not None and len(ordered) > max_rows:
        keep = max(1, max_rows - 1)
        ordered, hidden = _select_visible(ordered, statuses, keep)

    for i, repo in enumerate(ordered, 1):
        s = statuses.get(repo, {})
        status = s.get("status", "pending")
        icon = s.get("row_icon") or STATUS_ICON.get(status, "?")
        color = STATUS_COLOR.get(status, "")

        def cell(v, c=color):
            return Text(v or "", style=c)

        num = str(i)
        repo_type = s.get("type") or _detect_type(repo)

        if status == "pending":
            row = [
                num,
                icon,
                repo,
                repo_type,
                "",
                "",
                "",
                "",
                "",
                "",
                *(["", ""] if repeat else []),
                "",
                "",
                _friendly_status(status),
            ]
        elif status == "running":
            repo_start = s.get("repo_start_epoch")
            time_val = _fmt_secs_py(time.time() - float(repo_start)) if repo_start else ""
            phase = s.get("phase", "")
            phase_start = s.get("phase_start_epoch")
            phase_cell = (
                f"🔄 {_fmt_phase_elapsed(time.time() - float(phase_start))}"
                if (phase and phase_start)
                else ""
            )

            pre_install_val = s.get("pre_install", "") or (
                phase_cell if phase == "pre_install" else ""
            )
            install_val = _fmt_gross_net(s.get("install", ""), s.get("install_wall")) or (
                phase_cell if phase == "install" else ""
            )
            build_val = s.get("build", "") or (phase_cell if phase == "build" else "")
            pre_cold_val = s.get("pre_cold", "") or (phase_cell if phase == "pre_cold" else "")
            cold_val = _fmt_gross_net(s.get("cold", ""), s.get("cold_wall")) or (
                phase_cell if phase in ("cold", "cold_tests") else ""
            )
            pre_warm_val = s.get("pre_warm", "") or (phase_cell if phase == "pre_warm" else "")
            warm_val = _fmt_gross_net(s.get("warm", ""), s.get("warm_wall")) or (
                phase_cell if phase == "warm" else ""
            )

            row = [
                num,
                icon,
                repo,
                repo_type,
                s.get("tests", ""),
                pre_install_val,
                install_val,
                build_val,
                pre_cold_val,
                cold_val,
                *([pre_warm_val, warm_val] if repeat else []),
                time_val,
                "",
                _friendly_status(status),
            ]
        else:
            build_val = s.get("build", "")
            install_cell = _fmt_gross_net(s.get("install", ""), s.get("install_wall"))
            cold_cell = _fmt_gross_net(s.get("cold", ""), s.get("cold_wall"))
            warm_cell = _fmt_gross_net(s.get("warm", ""), s.get("warm_wall"))
            row = [
                num,
                icon,
                repo,
                repo_type,
                s.get("tests", ""),
                s.get("pre_install", ""),
                install_cell,
                build_val,
                s.get("pre_cold", ""),
                cold_cell,
                *([s.get("pre_warm", ""), warm_cell] if repeat else []),
                s.get("total", ""),
                s.get("finish_time", ""),
                _friendly_status(status),
            ]

        t.add_row(*[cell(v) for v in row])

    if hidden:
        pending = sum(1 for r in repos if statuses.get(r, {}).get("status", "pending") == "pending")
        ncells = 15 if repeat else 13
        summary = [""] * ncells
        summary[0] = "…"
        summary[2] = f"+{hidden} más" + (f" ({pending} pendientes)" if pending else "")
        t.add_row(*[Text(v, style="dim") for v in summary])

    return t


class LiveDisplay:
    """Componente actualizable para Live de Rich."""

    def __init__(
        self, repos: list[str], statuses: dict, repeat: bool, start_time: float, parallel: int
    ):
        self.repos = repos
        self.statuses = statuses
        self.repeat = repeat
        self.start_time = start_time
        self.parallel = parallel

    def __rich_console__(self, console, options):
        elapsed = _fmt_elapsed(time.monotonic() - self.start_time)
        done_count = sum(
            1
            for r in self.repos
            if self.statuses.get(r, {}).get("status", "pending") not in ("pending", "running")
        )
        mode_label = "repeat" if self.repeat else "single"
        header = Text(
            f"⏱  {elapsed}   {done_count}/{len(self.repos)} repos   paralelo={self.parallel}   modo={mode_label}",
            style="bold cyan",
        )
        max_rows = max(5, console.size.height - 3)
        group = Group(
            header, build_table(self.repos, self.statuses, self.repeat, max_rows=max_rows)
        )
        yield from group.__rich_console__(console, options)


def run_final(summary_path: str, elapsed: str = "") -> None:
    """Renderiza el reporte final a partir del archivo summary.tsv."""
    repos: list[str] = []
    statuses: dict = {}

    try:
        with open(summary_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        Console().print(f"[red]No se encontró el resumen: {summary_path}[/red]")
        sys.exit(1)

    elapsed_from_tsv = ""
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if not parts or parts[0] == "repo":
            continue
        if parts[0] == "#elapsed":
            elapsed_from_tsv = parts[1] if len(parts) > 1 else ""
            continue
        if len(parts) < 13:
            continue
        (
            repo,
            _exit,
            status,
            install_s,
            build_s,
            cold_s,
            warm_s,
            total_s,
            cold_tests,
            warm_tests,
            warm_icon,
            cold_icon,
            row_icon,
        ) = parts[:13]
        note = parts[13] if len(parts) > 13 else ""
        pre_install_s = parts[14] if len(parts) > 14 else "0"
        pre_cold_s = parts[15] if len(parts) > 15 else "0"
        pre_warm_s = parts[16] if len(parts) > 16 else "0"
        install_wall_s = parts[17] if len(parts) > 17 else "0"
        cold_wall_s = parts[18] if len(parts) > 18 else "0"
        warm_wall_s = parts[19] if len(parts) > 19 else "0"

        repos.append(repo)
        statuses[repo] = {
            "status": status,
            "type": _detect_type(repo),
            "row_icon": row_icon,
            "tests": cold_tests,
            "install": _fmt_secs_py(install_s),
            "build": _fmt_secs_py(build_s),
            "cold": f"{cold_icon} {_fmt_secs_py(cold_s)}"
            if cold_icon and _fmt_secs_py(cold_s)
            else "",
            "warm": f"{warm_icon} {_fmt_secs_py(warm_s)}"
            if warm_icon and _fmt_secs_py(warm_s)
            else "",
            "total_secs": float(total_s or 0),
            "total": _fmt_secs_py(total_s),
            "note": note,
            "pre_install": _fmt_secs_py(pre_install_s),
            "pre_cold": _fmt_secs_py(pre_cold_s),
            "pre_warm": _fmt_secs_py(pre_warm_s),
            "install_wall": install_wall_s,
            "cold_wall": cold_wall_s,
            "warm_wall": warm_wall_s,
        }

    repeat = any(s.get("warm") for s in statuses.values())
    green = sum(1 for s in statuses.values() if s["status"] == "green")
    red = sum(1 for s in statuses.values() if s["status"] == "red_code")
    infra = sum(1 for s in statuses.values() if s["status"] == "red_infra")
    no_tests = sum(1 for s in statuses.values() if s["status"] == "no_tests")

    c = Console(width=shutil.get_terminal_size(fallback=(200, 50)).columns)
    c.print(build_table(repos, statuses, repeat))
    summary_line = (
        f"\n[bold]=== RESULTADO ===[/bold]  "
        f"[green]exitosos={green}[/green]  "
        f"[red]fallidos={red}[/red]  "
        f"[yellow]infra={infra}[/yellow]  "
        f"[dim]sin_tests={no_tests}[/dim]  "
        f"(total={len(repos)})"
    )
    elapsed_shown = elapsed or elapsed_from_tsv
    if elapsed_shown:
        summary_line += f"  tiempo={elapsed_shown}"
    c.print(summary_line)


def main():
    global _WORKSPACE_DIR
    os.environ.pop("LINES", None)
    os.environ.pop("COLUMNS", None)

    repeat = False
    parallel = 4
    final_mode = False
    summary_path = None
    elapsed = ""
    repos: list[str] = []

    raw = sys.argv[1:]
    i = 0
    while i < len(raw):
        a = raw[i]
        if a == "--workspace-dir":
            _WORKSPACE_DIR = raw[i + 1] if i + 1 < len(raw) else ""
            i += 2
        elif a == "--repeat":
            repeat = True
            i += 1
        elif a == "--parallel":
            parallel = int(raw[i + 1]) if i + 1 < len(raw) else 4
            i += 2
        elif a == "--final":
            final_mode = True
            if i + 1 < len(raw) and not raw[i + 1].startswith("--"):
                summary_path = raw[i + 1]
                i += 2
            else:
                i += 1
        elif a == "--elapsed":
            elapsed = raw[i + 1] if i + 1 < len(raw) else ""
            i += 2
        else:
            repos.append(a)
            i += 1

    if final_mode:
        if not summary_path:
            print(
                "Uso: benchmark_display.py --workspace-dir DIR --final <summary.tsv> [--elapsed HH:MM:SS]",
                file=sys.stderr,
            )
            sys.exit(1)
        run_final(summary_path, elapsed)
        return

    if not repos:
        sys.exit(0)

    statuses: dict = {}
    start_time = time.monotonic()
    console = Console()
    done_summary = None

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    display = LiveDisplay(repos, statuses, repeat, start_time, parallel)

    with Live(
        display,
        console=console,
        screen=False,
        transient=True,
        refresh_per_second=4,
        vertical_overflow="visible",
    ) as live:
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if msg.get("done"):
                g = msg.get("green", 0)
                r = msg.get("red", 0)
                infra_count = msg.get("infra", 0)
                n = msg.get("no_tests", 0)
                elapsed_secs = msg.get("elapsed_secs", int(time.monotonic() - start_time))
                done_summary = (g, r, infra_count, n, elapsed_secs)
                break

            repo = msg.get("repo")
            if repo and repo in repos:
                if msg.get("status") not in ("running", None):
                    msg["_done_epoch"] = time.time()
                statuses[repo] = msg
                live.refresh()

    c = Console()
    c.print(build_table(repos, statuses, repeat))
    if done_summary:
        dg, dr, di, dn, elapsed_secs = done_summary
    else:
        dg = sum(1 for s in statuses.values() if s.get("status") == "green")
        dr = sum(1 for s in statuses.values() if s.get("status") == "red_code")
        di = sum(1 for s in statuses.values() if s.get("status") == "red_infra")
        dn = sum(1 for s in statuses.values() if s.get("status") == "no_tests")
        elapsed_secs = int(time.monotonic() - start_time)

    c.print(
        f"\n[bold]=== FINALIZADO ===[/bold]  "
        f"[green]exitosos={dg}[/green]  "
        f"[red]fallidos={dr}[/red]  "
        f"[yellow]infra={di}[/yellow]  "
        f"[dim]sin_tests={dn}[/dim]  "
        f"tiempo={_fmt_elapsed(elapsed_secs)}"
    )


if __name__ == "__main__":
    main()
