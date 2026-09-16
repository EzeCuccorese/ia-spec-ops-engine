#!/usr/bin/env python3
"""
workspace_engine.cli.unit_test_benchmark — Deterministic execution of local unit test benchmarks with metrics and visualization.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from workspace_engine.cli import set_java
from workspace_engine.common import (
    Color,
    detect_project_type,
    find_project_root,
    log_error,
    log_warning,
)
from workspace_engine.services.benchmark_display import run_final


def run_repo_tests(repo_path: Path) -> dict[str, Any]:
    """Runs a repository's unit tests and measures execution times."""
    name = repo_path.name
    detect_project_type(repo_path)

    t0 = time.time()
    cmd = []
    env = os.environ.copy()

    if (repo_path / "gradlew").is_file():
        cmd = ["./gradlew", "test", "--quiet", "--no-daemon"]
        java_env = set_java.setups_java(repo_path)
        if java_env:
            env.update(java_env)
    elif (repo_path / "pom.xml").is_file():
        cmd = ["mvn", "test", "-q"]
        java_env = set_java.setups_java(repo_path)
        if java_env:
            env.update(java_env)
    elif (repo_path / "yarn.lock").is_file():
        cmd = ["yarn", "test", "--passWithNoTests"]
    elif (repo_path / "package.json").is_file():
        cmd = ["npm", "test", "--", "--passWithNoTests"]
    elif (repo_path / "go.mod").is_file():
        cmd = ["go", "test", "./..."]
    elif (repo_path / "pyproject.toml").is_file() or (repo_path / "pytest.ini").is_file():
        cmd = ["pytest", "-q"]
    else:
        return {
            "repo": name,
            "exit_code": 0,
            "status": "no_tests",
            "install_secs": "0",
            "build_secs": "0",
            "cold_secs": "0",
            "warm_secs": "0",
            "total_secs": "0",
            "cold_tests": "0/0",
            "warm_tests": "—",
            "warm_icon": "—",
            "cold_icon": "0️⃣",
            "row_icon": "0️⃣",
            "note": "No test suite",
            "pre_install_secs": "0",
            "pre_cold_secs": "0",
            "pre_warm_secs": "0",
            "install_wall_secs": "0",
            "cold_wall_secs": "0",
            "warm_wall_secs": "0",
        }

    proc = subprocess.run(cmd, cwd=str(repo_path), env=env, capture_output=True, text=True)
    duration = time.time() - t0
    dur_str = f"{duration:.2f}"

    is_ok = proc.returncode == 0
    icon = "✅" if is_ok else "❌"

    return {
        "repo": name,
        "exit_code": proc.returncode,
        "status": "green" if is_ok else "red_infra",
        "install_secs": "0",
        "build_secs": "0",
        "cold_secs": dur_str,
        "warm_secs": "0",
        "total_secs": dur_str,
        "cold_tests": "OK" if is_ok else "FAIL",
        "warm_tests": "—",
        "warm_icon": "—",
        "cold_icon": icon,
        "row_icon": icon,
        "note": "All tests passed" if is_ok else "Test failure",
        "pre_install_secs": "0",
        "pre_cold_secs": "0",
        "pre_warm_secs": "0",
        "install_wall_secs": "0",
        "cold_wall_secs": dur_str,
        "warm_wall_secs": "0",
    }


def run_benchmark(repos_filter: list[str] | None = None, start_dir: Path | None = None) -> int:
    workspace_dir = find_project_root(start_dir)
    repos_dir = workspace_dir / "repositories"

    if not repos_dir.is_dir():
        if (workspace_dir / ".git").exists():
            targets = [workspace_dir]
        else:
            log_error(f"repositories/ folder not found in {workspace_dir}")
            return 1
    else:
        if repos_filter:
            targets = [repos_dir / r for r in repos_filter if (repos_dir / r).is_dir()]
        else:
            targets = [p for p in sorted(repos_dir.iterdir()) if p.is_dir()]

    if not targets:
        log_warning("No repositories to benchmark.")
        return 0

    results_dir = workspace_dir / ".ai-toolkit" / "unit-test-benchmark"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_file = results_dir / "summary.tsv"

    headers = [
        "repo",
        "exit_code",
        "status",
        "install_secs",
        "build_secs",
        "cold_secs",
        "warm_secs",
        "total_secs",
        "cold_tests",
        "warm_tests",
        "warm_icon",
        "cold_icon",
        "row_icon",
        "note",
        "pre_install_secs",
        "pre_cold_secs",
        "pre_warm_secs",
        "install_wall_secs",
        "cold_wall_secs",
        "warm_wall_secs",
    ]
    tsv_lines = ["\t".join(headers)]

    print(f"\n{Color.BOLD}Running test suite for {len(targets)} repository(ies)...{Color.RESET}\n")

    has_failures = False
    for r in targets:
        print(f"  {Color.BOLD}[{r.name}]{Color.RESET} running tests...", end="", flush=True)
        res = run_repo_tests(r)
        if res["exit_code"] != 0:
            has_failures = True
            print(f" {Color.RED}FAIL{Color.RESET} ({res['cold_secs']}s)")
        else:
            print(f" {Color.GREEN}OK{Color.RESET} ({res['cold_secs']}s)")

        row = [str(res.get(h, "")) for h in headers]
        tsv_lines.append("\t".join(row))

    summary_file.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
    print("\n")
    run_final(str(summary_file))
    return 1 if has_failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Runs a unit test benchmark for local repositories."
    )
    parser.add_argument("repos", nargs="*", help="Specific repositories to test")
    args = parser.parse_args()
    sys.exit(run_benchmark(repos_filter=args.repos))


if __name__ == "__main__":
    main()
