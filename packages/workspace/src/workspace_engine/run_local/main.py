"""
workspace_engine.run_local.main — Main entry point for run_local.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from workspace_engine.run_local import constants
from workspace_engine.run_local.constants import (
    _CONFIG_LOADED,
    BOLD,
    CYAN,
    DIM,
    GREEN,
    LOGS_DIR,
    PROJECT_CONFIG,
    RED,
    RESET,
)
from workspace_engine.run_local.discovery import (
    _ensure_config,
    _service_link,
    find_project_root,
    list_sources,
)
from workspace_engine.run_local.process_manager import (
    _launch_one,
    _pid_alive,
    _wait_port_free,
    fetch_env_for,
    launch_services,
    load_state,
    save_state,
    stop_all,
)
from workspace_engine.run_local.profiles import (
    load_last_configs,
    save_last_configs,
)
from workspace_engine.run_local.service_wiring import (
    service_name_from_subdomain as _service_name_from_subdomain,
)
from workspace_engine.run_local.tui import (
    _run_monitor_tui,
    _run_selection_tui,
)

_PROJECT_URL_RE = re.compile(PROJECT_CONFIG["url_pattern"])


def _open_browser(url: str) -> None:
    for cmd in ("xdg-open", "open", "wslview"):
        if shutil.which(cmd):
            subprocess.Popen([cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def _dependents_to_rewire(results: list, launch_configs: list, new_names: set[str]) -> list:
    cands = []
    by_name = {c["name"]: c for c in launch_configs}
    for r in results:
        if r["name"] in new_names or not _pid_alive(r.get("pid")):
            continue
        cfg = by_name.get(r["name"])
        if not cfg or cfg.get("up_mode", "auto") != "auto":
            continue
        env = fetch_env_for(cfg, cfg.get("base_env", "local"))
        for v in env.values():
            sv = str(v)
            if PROJECT_CONFIG["domain"] not in sv:
                continue
            hit = any(
                any(n in _service_name_from_subdomain(m.group(1)) for n in new_names)
                for m in _PROJECT_URL_RE.finditer(sv)
            )
            if hit:
                cands.append(r["name"])
                break
    return cands


def _restart_named(names: list, results: list, launch_configs: list, db_cfg: dict) -> None:
    running_ports = {c["name"]: c["port"] for c in launch_configs}
    by_name = {c["name"]: c for c in launch_configs}
    for nm in names:
        cfg = by_name.get(nm)
        r = next((rr for rr in results if rr["name"] == nm), None)
        if not cfg or not r:
            continue
        if r.get("pid"):
            for t in (-r["pid"], r["pid"]):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(t, signal.SIGTERM)
        _wait_port_free(cfg["port"])
        pid, err, started_at, wired_map = _launch_one(cfg, running_ports, db_cfg)
        r["pid"], r["error"], r["started_at"] = pid, err, started_at
        cfg["wiring"] = wired_map
        print(
            f"  {('✔ ' + nm + ' restarted (PID ' + str(pid) + ')') if pid else ('✖ ' + nm + ': ' + str(err))}"
        )


def _launch_and_report(configs: list, db_cfg: dict) -> tuple:
    print(f"\n{BOLD}Starting {len(configs)} service(s)...{RESET}\n")
    results, launch_configs = launch_services(configs, db_cfg)
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    if ok:
        print(f"\n{BOLD}Running:{RESET}")
        for r in ok:
            link = _service_link(r["type"], r["port"])
            print(f"  {GREEN}●{RESET} {BOLD}{r['name']:<32}{RESET}  {CYAN}{link}{RESET}")
    if fail:
        print(f"\n{BOLD}{RED}Failed:{RESET}")
        for r in fail:
            print(f"  {RED}✖{RESET} {BOLD}{r['name']}{RESET}  {r['error']}")
    return results, launch_configs


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ws run-local",
        description="Generic service launcher for local development.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dir", metavar="PATH", help="Repos directory (auto-detected if not specified)"
    )
    parser.add_argument("--stop", action="store_true", help="Stop all running services")
    parser.add_argument(
        "--start",
        nargs="?",
        const="",
        metavar="REPOS",
        help="Relaunch the last config without the TUI. REPOS: comma-separated list.",
    )
    return parser.parse_args(argv)


def _forced_repos_dir(dir_arg: str | None) -> Path | None:
    """`--dir` when it directly contains at least one git repository."""
    if not dir_arg:
        return None
    p = Path(dir_arg).expanduser().resolve()
    if p.is_dir() and any(d.is_dir() and (d / ".git").exists() for d in p.iterdir()):
        return p
    return None


def _resolve_sources(dir_arg: str | None) -> tuple[list, Path | None]:
    force_repos_dir = _forced_repos_dir(dir_arg)
    if force_repos_dir:
        sources = [{"label": force_repos_dir.name, "path": force_repos_dir, "kind": "repos"}]
        return sources, force_repos_dir
    start = Path(dir_arg).expanduser().resolve() if dir_arg else Path.cwd()
    root = find_project_root(start)
    workspaces_dir = PROJECT_CONFIG["workspaces_dir_name"]
    if root is None:
        print(
            f"{RED}Error: no project found with repositories/ or {workspaces_dir}/ from {start}.{RESET}"
        )
        print("Pass --dir <path> pointing to a directory with git repositories.")
        sys.exit(1)
    sources = list_sources(root)
    if not sources:
        print(
            f"{RED}Error: no sources found (repositories/ or {workspaces_dir}/) in {root}.{RESET}"
        )
        sys.exit(1)
    return sources, None


def _last_configs_to_start(spec: str) -> list:
    specific = [r.strip() for r in spec.split(",") if r.strip()]
    last_cfgs = load_last_configs()
    if not last_cfgs:
        print(f"{RED}No saved config. Run `ws run-local` without --start first.{RESET}")
        sys.exit(1)
    if specific:
        last_cfgs = [c for c in last_cfgs if c["name"] in specific]
    if not last_cfgs:
        print(f"{RED}No repo found in the last saved config.{RESET}")
        sys.exit(1)
    return last_cfgs


def _alive_names(results: list) -> set[str]:
    return {r["name"] for r in results if _pid_alive(r.get("pid"))}


def _started_names(new_results: list) -> set[str]:
    return {r["name"] for r in new_results if r["ok"]}


def _start_headless(spec: str, results: list, launch_configs: list, db_cfg: dict) -> None:
    """`--start`: relaunches the last saved configs that are not already running."""
    alive_names = _alive_names(results)
    to_launch = [c for c in _last_configs_to_start(spec) if c["name"] not in alive_names]
    if not to_launch:
        print(f"{DIM}All services are already running.{RESET}")
        return
    new_results, new_lc = _launch_and_report(to_launch, db_cfg)
    started = _started_names(new_results)
    results += [r for r in new_results if r["ok"]]
    launch_configs += [c for c in new_lc if c["name"] in started]
    save_state(results, launch_configs)
    print(f"\n{DIM}Logs: {LOGS_DIR}/   Stop: ws run-local --stop{RESET}\n")


def _launch_selection(sources: list, force_repos_dir: Path | None, db_cfg: dict) -> tuple:
    """First launch through the selection TUI; returns only the services that started."""
    configs = _run_selection_tui(sources, force_repos_dir, db_cfg)
    if not configs:
        return [], []
    results, launch_configs = _launch_and_report(configs, db_cfg)
    results = [r for r in results if r["ok"]]
    launch_configs = [c for c in launch_configs if any(r["name"] == c["name"] for r in results)]
    if results:
        save_state(results, launch_configs)
        save_last_configs(launch_configs)
    return results, launch_configs


def _needs_launch(cfg: dict, current: dict | None, alive: set[str]) -> bool:
    """False when the service already runs with the same env, db and upstream mode."""
    if cfg["name"] not in alive or not current:
        return True
    keys = ("base_env", "db_env", "up_mode")
    return tuple(current.get(k) for k in keys) != tuple(cfg.get(k) for k in keys)


def _terminate(pid: int) -> None:
    """SIGTERM to the process group, then to the process itself."""
    if pid <= 0:
        return  # 0 or less would signal our own process group
    for t in (-pid, pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(t, signal.SIGTERM)


def _stop_running(to_launch: list, results: list) -> None:
    for c in to_launch:
        r_old = next((r for r in results if r["name"] == c["name"]), None)
        if r_old and _pid_alive(r_old.get("pid")):
            _terminate(r_old["pid"])


def _offer_rewire(results: list, launch_configs: list, new_names: set[str], db_cfg: dict) -> None:
    deps = _dependents_to_rewire(results, launch_configs, new_names)
    if not deps:
        return
    print(f"\n{BOLD}Started:{RESET} {', '.join(sorted(new_names))}")
    print(
        f"{DIM}These services (upstream=auto) can re-point to the new local instance:{RESET} {', '.join(deps)}"
    )
    try:
        ans = input("Restart them to point to local? [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("y", "yes"):
        _restart_named(deps, results, launch_configs, db_cfg)
        save_state(results, launch_configs)


def _replace_by_name(current: list, stopped: set[str], fresh: list, started: set[str]) -> list:
    """``current`` without the ``stopped`` entries, plus the ``started`` ones from ``fresh``."""
    kept = [e for e in current if e["name"] not in stopped]
    return kept + [e for e in fresh if e["name"] in started]


def _add_services(
    more: list, results: list, launch_configs: list, db_cfg: dict
) -> tuple[list, list]:
    """Launches the newly selected or reconfigured services next to the running ones."""
    cur_by = {c["name"]: c for c in launch_configs}
    alive = _alive_names(results)
    to_launch = [c for c in more if _needs_launch(c, cur_by.get(c["name"]), alive)]
    if not to_launch:
        return results, launch_configs
    _stop_running(to_launch, results)
    new_results, new_lc = _launch_and_report(to_launch, db_cfg)
    new_names = _started_names(new_results)
    stopped = {c["name"] for c in to_launch}
    results = _replace_by_name(results, stopped, new_results, new_names)
    launch_configs = _replace_by_name(launch_configs, stopped, new_lc, new_names)
    save_state(results, launch_configs)
    save_last_configs(launch_configs)
    _offer_rewire(results, launch_configs, new_names, db_cfg)
    return results, launch_configs


def _monitor(
    results: list, launch_configs: list, select: Callable[[], list | None], db_cfg: dict
) -> None:
    """Monitor TUI loop; "add" opens ``select`` and launches what it returns."""
    while True:
        print(f"\n{DIM}Logs: {LOGS_DIR}/   Stop: ws run-local --stop{RESET}\n")
        action = _run_monitor_tui(results, launch_configs, db_cfg)
        save_state(results, launch_configs)
        if action != "add":
            break
        more = select()
        if more:
            results, launch_configs = _add_services(more, results, launch_configs, db_cfg)


def _exit_without_config() -> None:
    print(f"{RED}Error: no configuration found. Searched, in order:{RESET}")
    for path in constants.config_candidates(constants.find_project_root()):
        print(f"  {path}")
    print(
        "Run 'ws config init --global' or 'ws config init --local' and review the generated values."
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.stop:  # stopping reads only the PID files, no configuration needed
        stop_all()
        return
    if not _CONFIG_LOADED and "pytest" not in sys.modules:
        _exit_without_config()

    db_cfg = _ensure_config()
    sources, force_repos_dir = _resolve_sources(args.dir)

    results, launch_configs = load_state()
    if results:
        names = ", ".join(r["name"] for r in results)
        print(f"{BOLD}Reattaching {len(results)} running service(s):{RESET} {DIM}{names}{RESET}")

    if args.start is not None:
        _start_headless(args.start, results, launch_configs, db_cfg)
        return

    if not results:
        results, launch_configs = _launch_selection(sources, force_repos_dir, db_cfg)
        if not results:
            return

    _monitor(
        results,
        launch_configs,
        lambda: _run_selection_tui(sources, force_repos_dir, db_cfg),
        db_cfg,
    )
    print(
        f"{DIM}Services keep running in the background. Use `ws run-local --stop` to stop them.{RESET}\n"
    )


if __name__ == "__main__":
    main()
