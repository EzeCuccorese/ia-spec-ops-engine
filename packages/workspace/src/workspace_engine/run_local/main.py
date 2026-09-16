"""
workspace_engine.run_local.main — Main entry point for run_local.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

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
                    os.kill(t, 15)
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


def main():
    if not _CONFIG_LOADED and "pytest" not in sys.modules:
        print(
            f"{RED}Error: no configuration found at ~/.config/specops/config.json or config.json in the current directory.{RESET}"
        )
        print(
            f"Run 'ws config init --global' or 'ws config init --local' and review the generated values.{RESET}"
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(
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
    args = parser.parse_args()

    if args.stop:
        stop_all()
        return

    db_cfg = _ensure_config()

    start = Path(args.dir).expanduser().resolve() if args.dir else Path.cwd()
    root = find_project_root(start)

    force_repos_dir: Path | None = None
    if args.dir:
        p = Path(args.dir).expanduser().resolve()
        git_dirs = (
            [d for d in p.iterdir() if d.is_dir() and (d / ".git").exists()] if p.is_dir() else []
        )
        if len(git_dirs) >= 1:
            force_repos_dir = p

    if force_repos_dir:
        sources = [{"label": force_repos_dir.name, "path": force_repos_dir, "kind": "repos"}]
    elif root:
        sources = list_sources(root)
        workspaces_dir = PROJECT_CONFIG["workspaces_dir_name"]
        if not sources:
            print(
                f"{RED}Error: no sources found (repositories/ or {workspaces_dir}/) in {root}.{RESET}"
            )
            sys.exit(1)
    else:
        workspaces_dir = PROJECT_CONFIG["workspaces_dir_name"]
        print(
            f"{RED}Error: no project found with repositories/ or {workspaces_dir}/ from {start}.{RESET}"
        )
        print("Pass --dir <path> pointing to a directory with git repositories.")
        sys.exit(1)

    results, launch_configs = load_state()
    if results:
        names = ", ".join(r["name"] for r in results)
        print(f"{BOLD}Reattaching {len(results)} running service(s):{RESET} {DIM}{names}{RESET}")

    if args.start is not None:
        specific = [r.strip() for r in args.start.split(",") if r.strip()] if args.start else []
        last_cfgs = load_last_configs()
        if not last_cfgs:
            print(f"{RED}No saved config. Run run-local.py without --start first.{RESET}")
            sys.exit(1)
        if specific:
            last_cfgs = [c for c in last_cfgs if c["name"] in specific]
        if not last_cfgs:
            print(f"{RED}No repo found in the last saved config.{RESET}")
            sys.exit(1)
        alive_names = {r["name"] for r in results if _pid_alive(r.get("pid"))}
        to_launch = [c for c in last_cfgs if c["name"] not in alive_names]
        if not to_launch:
            print(f"{DIM}All services are already running.{RESET}")
            return
        new_results, new_lc = _launch_and_report(to_launch, db_cfg)
        results += [r for r in new_results if r["ok"]]
        launch_configs += [
            c for c in new_lc if any(r["name"] == c["name"] for r in new_results if r["ok"])
        ]
        save_state(results, launch_configs)
        print(f"\n{DIM}Logs: {LOGS_DIR}/   Stop: run-local.py --stop{RESET}\n")
        return

    if not results:
        configs = _run_selection_tui(sources, force_repos_dir, db_cfg)
        if not configs:
            return
        results, launch_configs = _launch_and_report(configs, db_cfg)
        results = [r for r in results if r["ok"]]
        launch_configs = [c for c in launch_configs if any(r["name"] == c["name"] for r in results)]
        if not results:
            return
        save_state(results, launch_configs)
        save_last_configs(launch_configs)

    while True:
        print(f"\n{DIM}Logs: {LOGS_DIR}/   Stop: run-local.py --stop{RESET}\n")
        action = _run_monitor_tui(results, launch_configs, db_cfg)
        save_state(results, launch_configs)
        if action != "add":
            break

        more = _run_selection_tui(sources, force_repos_dir, db_cfg)
        if not more:
            continue
        cur_by = {c["name"]: c for c in launch_configs}
        alive = {r["name"] for r in results if _pid_alive(r.get("pid"))}
        to_launch = []
        for c in more:
            rc = cur_by.get(c["name"])
            unchanged = (
                c["name"] in alive
                and rc
                and (rc.get("base_env"), rc.get("db_env"), rc.get("up_mode"))
                == (c["base_env"], c["db_env"], c["up_mode"])
            )
            if not unchanged:
                to_launch.append(c)
        if not to_launch:
            continue
        for c in to_launch:
            r_old = next((r for r in results if r["name"] == c["name"]), None)
            if r_old and _pid_alive(r_old.get("pid")):
                for t in (-r_old["pid"], r_old["pid"]):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(t, 15)
        new_results, new_lc = _launch_and_report(to_launch, db_cfg)
        new_names = {r["name"] for r in new_results if r["ok"]}
        results = [r for r in results if r["name"] not in new_names]
        launch_configs = [c for c in launch_configs if c["name"] not in new_names]
        results += [r for r in new_results if r["ok"]]
        launch_configs += [c for c in new_lc if c["name"] in new_names]
        save_state(results, launch_configs)
        save_last_configs(launch_configs)

        deps = _dependents_to_rewire(results, launch_configs, new_names)
        if deps:
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

    print(
        f"{DIM}Services keep running in the background. Use run-local.py --stop to stop them.{RESET}\n"
    )


if __name__ == "__main__":
    main()
