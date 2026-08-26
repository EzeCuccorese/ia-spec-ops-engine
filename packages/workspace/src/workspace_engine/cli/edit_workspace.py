#!/usr/bin/env python3
"""
workspace_engine.cli.edit_workspace — Edición interactiva de repositorios en un workspace existente (agregar o remover).
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

from workspace_engine.services.add_repos import add_repositories_to_workspace
from workspace_engine.services.render_agents import render_agents_md
from workspace_engine.services.select_repos import select_repos
from workspace_engine.utils import Color, find_project_root, log_error, log_info, log_success, log_warning, parse_dotenv, run_git


def _git(repo_path: Path, *args) -> subprocess.CompletedProcess:
    return run_git(repo_path, *args)


def remove_repositories_from_workspace(workspace_dir: Path):
    manifest_path = workspace_dir / '.ai-toolkit' / 'workspace.json'
    if not manifest_path.exists():
        log_error(f'Manifiesto de workspace no encontrado en {manifest_path}')
        sys.exit(1)

    existing_data = json.loads(manifest_path.read_text(encoding='utf-8'))
    workspace_name: str = existing_data['workspace']
    current_repo_names: List[str] = [r['name'] for r in existing_data.get('repositories', [])]

    if not current_repo_names:
        log_info('No hay repositorios en este workspace.')
        return

    print(f"\n{Color.BOLD}Selecciona los repositorios a remover de '{workspace_name}':{Color.RESET}")
    for idx, name in enumerate(current_repo_names, 1):
        print(f"  {idx}. {name}")

    choice = input(f"\n{Color.BOLD}Ingresa números separados por coma o 'q' para cancelar: {Color.RESET}").strip()
    if not choice or choice.lower() == 'q':
        log_warning("Operación cancelada.")
        return

    selected_indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
    to_remove = [current_repo_names[i - 1] for i in selected_indices if 1 <= i <= len(current_repo_names)]

    if not to_remove:
        log_warning("Ningún repositorio seleccionado.")
        return

    repos_dir = workspace_dir / 'repositories'
    for rname in to_remove:
        target_wt = repos_dir / rname
        if target_wt.exists():
            git_common = _git(target_wt, "rev-parse", "--git-common-dir")
            if git_common.returncode == 0 and git_common.stdout.strip():
                common_path = Path(git_common.stdout.strip())
                if not common_path.is_absolute():
                    common_path = (target_wt / common_path).resolve()
                _git(common_path, "worktree", "remove", "--force", str(target_wt))
                _git(common_path, "worktree", "prune")
            shutil.rmtree(target_wt, ignore_errors=True)
            log_info(f"  Removido worktree: {rname}")

    remaining_repos = [r for r in current_repo_names if r not in to_remove]
    existing_data['repositories'] = [r for r in existing_data.get('repositories', []) if r.get('name') not in to_remove]
    manifest_path.write_text(json.dumps(existing_data, indent=2), encoding='utf-8')

    # Actualizar AGENTS.md si existe
    agents_file = workspace_dir / 'AGENTS.md'
    if agents_file.exists():
        content = f"# Workspace: {workspace_name}\n\nLos repositorios están en `repositories/`.\n\n## Repositorios\n\n"
        content += '\n'.join(f"- {r}" for r in remaining_repos) + '\n'
        agents_file.write_text(content, encoding='utf-8')

    log_success(f"Repositorios removidos con éxito: {', '.join(to_remove)}")


def main():
    workspace_dir = find_project_root()
    if not (workspace_dir / 'repositories').is_dir():
        log_error("edit-workspace debe ejecutarse desde adentro de un workspace.")
        sys.exit(1)

    print(f"\n{Color.BOLD}Editar Workspace:{Color.RESET} {workspace_dir.name}\n")
    print("  1) Agregar repositorios")
    print("  2) Remover repositorios")
    choice = input(f"\n{Color.BOLD}Opción [1/2]: {Color.RESET}").strip()

    env_vars = parse_dotenv(workspace_dir / 'config' / '.env')
    repos_dir_str = env_vars.get('AI_REPOSITORIES_DIR', os.environ.get('AI_REPOSITORIES_DIR', ''))
    repos_root = Path(repos_dir_str).resolve() if repos_dir_str else workspace_dir.parent.parent / "ai-repositories"

    if choice == '1':
        add_repositories_to_workspace(workspace_dir, repos_root)
    elif choice == '2':
        remove_repositories_from_workspace(workspace_dir)
    else:
        log_warning("Operación cancelada.")


if __name__ == '__main__':
    main()
