#!/usr/bin/env python3
"""
workspace_engine.services.render_agents — Renders agent configuration files (AGENTS.md, etc.)
from deterministic templates with workspace-specific substitutions.
"""

from __future__ import annotations

import re
import sys
from importlib.resources import files
from pathlib import Path


def render_agents_md(
    template_path: str | Path | None,
    workspace_name: str,
    repos_dir: str,
    repos: list[str],
) -> str:
    """Returns the rendered content for the workspace instructions."""
    repo_list = "\n".join(f"- {r}" for r in repos)
    template_file = Path(template_path) if template_path else None
    if not (template_file and template_file.exists()):
        content = (
            files("workspace_engine")
            .joinpath("resources", "templates", "workspace-agents.md.template")
            .read_text(encoding="utf-8")
        )
    else:
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


def update_workspace_agents(
    workspace_dir: Path, repos: list[str], template_path: Path | None = None
) -> None:
    """Refresh the repository list without replacing workspace policy or user notes."""
    target = workspace_dir / "AGENTS.md"
    if not target.exists():
        content = render_agents_md(template_path, workspace_dir.name, "repositories", repos)
    else:
        content = target.read_text(encoding="utf-8")
        section = "## Repositories\n\n" + "\n".join(f"- {repo}" for repo in repos) + "\n\n"
        pattern = r"^## Repositories[^\n]*\n.*?(?=^## |\Z)"
        if re.search(pattern, content, flags=re.MULTILINE | re.DOTALL):
            content = re.sub(
                pattern, lambda _: section, content, count=1, flags=re.MULTILINE | re.DOTALL
            )
        else:
            content = content.rstrip() + "\n\n" + section
    target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            f"Usage: {sys.argv[0]} <template> <workspace_name> <repos_dir> [repo ...]",
            file=sys.stderr,
        )
        sys.exit(1)
    t_path, ws_name, r_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    repositories = sys.argv[4:]
    print(render_agents_md(t_path, ws_name, r_dir, repositories), end="")
