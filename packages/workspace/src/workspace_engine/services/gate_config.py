"""Gate settings for the shell hooks: what the repo and user config files add.

The hooks keep their own ``QG_*`` / ``git config workspace.*`` handling. Full precedence is
env ``QG_*`` > git config ``workspace.*`` > repo file (``.workspace/config.toml``) > user file
(``~/.config/workspace/config.toml``) > default, so this only has to say what the files
decide: it prints an assignment for a setting unless the environment or the default wins
(git config winners are printed too, so keys the scripts never read themselves work).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from workspace_engine._config_core import Value
from workspace_engine.settings import effective

SHELL_VARIABLES = {
    "gate.skip": "QG_SKIP",
    "gate.protected_branches": "QG_PROTECTED",
    "gate.timeout_seconds": "QG_TIMEOUT",
    "gate.commit_style": "QG_COMMIT_STYLE",
    "gate.scope": "QG_SCOPE",
    "gate.output": "QG_OUTPUT",
}
FILE_ORIGINS = ("user", "repo", "personal", "git")  # everything below the environment


def _text(value: Value) -> str:
    return ",".join(map(str, value.value)) if isinstance(value.value, list) else str(value.value)


def file_decided(root: Path) -> dict[str, Value]:
    """Gate settings whose winning value is not the environment or the built-in default."""
    values = effective(root)
    return {key: values[key] for key in SHELL_VARIABLES if values[key].origin in FILE_ORIGINS}


def shell_assignments(root: Path) -> str:
    """``VAR='value'`` lines for ``eval`` in the hook scripts."""
    lines = []
    for key, value in file_decided(root).items():
        lines.append(f"{SHELL_VARIABLES[key]}={shlex.quote(_text(value))}")
        if key == "gate.skip":
            source = (
                "workspace.skip (repo config)"  # the label the script always used
                if value.origin == "git"
                else f"{value.origin} config file ({value.source})"
            )
            lines.append(f"QG_SKIP_SOURCE={shlex.quote(source)}")
    return "\n".join(lines)


def repo_gate_settings(root: Path) -> list[str]:
    """Gate settings present for this repo (git config or repo file) — used by `ws hooks status`."""
    return [
        f"{key} ({value.source})"
        for key, value in effective(root).items()
        if key.startswith("gate.") and value.origin in ("git", "repo")
    ]
