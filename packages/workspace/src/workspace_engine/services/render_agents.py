#!/usr/bin/env python3
"""
workspace_engine.services.render_agents — Renderiza archivos de configuración de agentes (AGENTS.md, etc.)
a partir de plantillas deterministas con sustituciones específicas del workspace.
"""

from __future__ import annotations

import sys
from pathlib import Path


def render_agents_md(
    template_path: str | Path,
    workspace_name: str,
    repos_dir: str,
    repos: list[str],
) -> str:
    """Retorna el contenido renderizado para las instrucciones del workspace."""
    repo_list = "\n".join(f"- {r}" for r in repos)
    template_file = Path(template_path)
    if not template_file.exists():
        return (
            f"# Workspace: {workspace_name}\n\n"
            f"Los repositorios de este workspace se ubican en `{repos_dir}/`.\n\n"
            f"## Repositorios\n\n{repo_list}\n"
        )
    content = template_file.read_text(encoding="utf-8")
    replacements = {
        "{workspace_name}": workspace_name,
        "{{WORKSPACE_NAME}}": workspace_name,
        "{repos_dir}": repos_dir,
        "{{REPOS_DIR}}": repos_dir,
        "{repo_list}": repo_list,
        "{{REPOSITORIES_LIST}}": repo_list,
    }
    for k, v in replacements.items():
        content = content.replace(k, v)
    return content


# Alias para retrocompatibilidad
render_claude_md = render_agents_md


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            f"Uso: {sys.argv[0]} <template> <workspace_name> <repos_dir> [repo ...]",
            file=sys.stderr,
        )
        sys.exit(1)
    t_path, ws_name, r_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    repositories = sys.argv[4:]
    print(render_agents_md(t_path, ws_name, r_dir, repositories), end="")
