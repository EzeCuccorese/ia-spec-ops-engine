#!/usr/bin/env python3
"""
workspace_engine.cli.create_worktree — Creación determinista de Git Worktrees y sincronización de archivos de entorno.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from workspace_engine.utils import find_project_root, log_error, log_info, log_success


def _run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def create_worktree(
    branch: str, from_branch: str | None = None, start_dir: Path | None = None
) -> int:
    """Crea un git worktree para la rama especificada y copia configuraciones locales."""
    repo_root = find_project_root(start_dir)
    sanitized_branch = branch.replace("/", "-")
    worktree_dir = repo_root.parent / f"workspace-{sanitized_branch}"

    if worktree_dir.exists():
        log_error(f"Error: '{worktree_dir}' ya existe")
        return 1

    base_branch = from_branch
    if not base_branch:
        res_branch, current_branch, _ = _run_cmd(
            ["git", "-C", str(repo_root), "branch", "--show-current"]
        )
        current_branch = current_branch.strip()
        base_branch = current_branch if (res_branch == 0 and current_branch) else "main"

    if base_branch in ("main", "master", "develop", "staging"):
        log_info(f"🔄 Actualizando rama base '{base_branch}' con git pull...")
        _run_cmd(["git", "-C", str(repo_root), "pull", "origin", base_branch])

    code_local, _, _ = _run_cmd(
        ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    code_remote, _, _ = _run_cmd(
        [
            "git",
            "-C",
            str(repo_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{branch}",
        ]
    )

    if code_local == 0:
        cmd = ["git", "-C", str(repo_root), "worktree", "add", str(worktree_dir), branch]
    elif code_remote == 0:
        cmd = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--track",
            "-b",
            branch,
            str(worktree_dir),
            f"origin/{branch}",
        ]
    else:
        cmd = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_dir),
            base_branch,
        ]

    res, _, err = _run_cmd(cmd)
    if res != 0:
        log_error(f"Fallo al crear worktree: {err}")
        return res

    log_success(f"Worktree creado en: {worktree_dir}")

    config_files = [
        "config/.env",
        "config/.env.secrets",
        ".specify/settings.local.json",
        ".specify/worktrees",
        "memory",
    ]

    for rel_path in config_files:
        src = repo_root / rel_path
        if src.exists():
            dest = worktree_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            log_info(f"  copiado: {rel_path}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea un Git worktree aislado en ../workspace-<rama>"
    )
    parser.add_argument("branch", help="Nombre de la rama para el worktree")
    args = parser.parse_args()
    sys.exit(create_worktree(args.branch))


if __name__ == "__main__":
    main()
