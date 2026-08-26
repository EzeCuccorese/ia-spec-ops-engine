#!/usr/bin/env python3
"""
workspace_engine.cli.delete_workspaces — Eliminación segura e interactiva de workspaces y sus worktrees asociados.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from workspace_engine.utils import Color, find_project_root, log_error, log_info, log_success, log_warning, run_git


def _git(repo_path: Path, *args) -> subprocess.CompletedProcess:
    return run_git(repo_path, *args)


def delete_single_workspace(workspace_dir: Path, force: bool = False) -> bool:
    if not workspace_dir.is_dir():
        log_error(f"Workspace no encontrado en {workspace_dir}")
        return False

    workspace_name = workspace_dir.name
    print(f"\n{Color.BOLD}Eliminando workspace '{workspace_name}'...{Color.RESET}")

    repos_dir = workspace_dir / "repositories"
    if repos_dir.is_dir():
        for r_dir in repos_dir.iterdir():
            if r_dir.is_dir() and ((r_dir / ".git").exists() or (r_dir / ".git").is_file()):
                git_common = _git(r_dir, "rev-parse", "--git-common-dir")
                if git_common.returncode == 0 and git_common.stdout.strip():
                    common_path = Path(git_common.stdout.strip())
                    if not common_path.is_absolute():
                        common_path = (r_dir / common_path).resolve()
                    _git(common_path, "worktree", "remove", "--force", str(r_dir))
                    _git(common_path, "worktree", "prune")

    shutil.rmtree(workspace_dir, ignore_errors=True)
    log_success(f"Workspace '{workspace_name}' eliminado.")
    return True


def delete_workspaces(workspaces: Optional[List[str]] = None, force: bool = False) -> int:
    root = find_project_root()
    workspaces_root = root / "workspaces" if (root / "workspaces").exists() else root.parent / "workspaces"

    # Si se ejecuta desde adentro de un workspace
    if (root / "repositories").is_dir() and root.name != "workspaces":
        if not force:
            print(f"{Color.RED}{Color.BOLD}⚠ Advertencia: Vas a eliminar el workspace actual: {root.name}{Color.RESET}")
            resp = input(f"{Color.BOLD}¿Eliminar? [y/N]: {Color.RESET}").strip().lower()
            if resp not in ("y", "yes", "s", "si"):
                log_warning("Operación cancelada.")
                return 0
        delete_single_workspace(root, force=True)
        return 0

    if not workspaces:
        if not workspaces_root.exists():
            log_warning("No se encontró directorio de workspaces.")
            return 0
        available = [d.name for d in sorted(workspaces_root.iterdir()) if d.is_dir()]
        if not available:
            log_info("No hay workspaces disponibles para eliminar.")
            return 0
        print(f"\n{Color.BOLD}Workspaces disponibles:{Color.RESET}")
        for idx, w in enumerate(available, 1):
            print(f"  {idx}. {w}")
        choice = input(f"\n{Color.BOLD}Selecciona los números a eliminar (separados por coma) o 'q' para salir: {Color.RESET}").strip()
        if not choice or choice.lower() == 'q':
            log_warning("Operación cancelada.")
            return 0
        selected_indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
        workspaces = [available[i - 1] for i in selected_indices if 1 <= i <= len(available)]

    for ws_name in workspaces:
        ws_path = workspaces_root / ws_name
        delete_single_workspace(ws_path, force=force)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Elimina workspaces y desregistra sus worktrees.")
    parser.add_argument("--force", action="store_true", help="Omitir confirmación")
    parser.add_argument("workspaces", nargs="*", help="Nombres de los workspaces a eliminar")
    args = parser.parse_args()

    sys.exit(delete_workspaces(workspaces=args.workspaces, force=args.force))


if __name__ == "__main__":
    main()
