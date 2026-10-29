#!/usr/bin/env python3
"""
workspace_engine.cli.install_deps — Deterministic installation of local dependencies (Node, Gradle, Maven, Go, Python).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from workspace_engine.common import (
    detect_project_type,
    find_project_root,
    log_error,
    log_info,
    log_success,
    log_warning,
)

_MANIFEST_COMMANDS: tuple[tuple[str, list[str]], ...] = (
    ("yarn.lock", ["yarn", "install"]),
    ("package-lock.json", ["npm", "install"]),
    ("package.json", ["npm", "install"]),
    ("gradlew", ["./gradlew", "dependencies", "--quiet"]),
    ("pom.xml", ["mvn", "dependency:resolve", "-q"]),
    ("go.mod", ["go", "mod", "download"]),
    ("requirements.txt", ["pip", "install", "-r", "requirements.txt"]),
    ("pyproject.toml", ["pip", "install", "-e", "."]),
)


def _detect_install_command(repo_path: Path) -> list[str] | None:
    for filename, cmd in _MANIFEST_COMMANDS:
        if (repo_path / filename).is_file():
            return cmd
    return None


def install_repo_deps(repo_path: Path) -> bool:
    """Installs dependencies for a specific repository based on its technology."""
    name = repo_path.name
    ptype = detect_project_type(repo_path)

    log_info(f"[{name}] Installing dependencies ({ptype})...")
    cmd = _detect_install_command(repo_path)
    if not cmd:
        log_warning(f"[{name}] No recognized dependency manifest detected.")
        return True

    res = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True)
    if res.returncode == 0:
        log_success(f"[{name}] Dependencies installed successfully.")
        return True
    log_error(f"[{name}] Error installing dependencies:\n{res.stderr.strip()[:300]}")
    return False


def install_all_deps(repos_filter: list[str] | None = None, start_dir: Path | None = None) -> int:
    workspace_dir = find_project_root(start_dir)
    repos_dir = workspace_dir / "repositories"

    if not repos_dir.is_dir():
        # If run directly inside a single repository
        if (workspace_dir / ".git").exists():
            success = install_repo_deps(workspace_dir)
            return 0 if success else 1
        log_error(f"Repositories directory not found in {workspace_dir}")
        return 1

    targets: list[Path] = []
    if repos_filter:
        for rname in repos_filter:
            p = repos_dir / rname
            if p.is_dir():
                targets.append(p)
            else:
                log_error(f"Repository not found: {rname}")
    else:
        targets = [p for p in sorted(repos_dir.iterdir()) if p.is_dir()]

    if not targets:
        log_warning("No repositories to process.")
        return 0

    all_ok = True
    for rpath in targets:
        ok = install_repo_deps(rpath)
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ws deps", description="Installs local project dependencies."
    )
    parser.add_argument("repos", nargs="*", help="Specific repository names (optional)")
    args = parser.parse_args(argv)
    sys.exit(install_all_deps(repos_filter=args.repos))


if __name__ == "__main__":
    main()
