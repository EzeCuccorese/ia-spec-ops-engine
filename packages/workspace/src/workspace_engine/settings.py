"""Every ws setting in one place: default, environment variable and where it is read.

Layers (lowest to highest): default < ``~/.config/workspace/config.toml`` <
``<repo>/.workspace/config.toml`` < environment variable < CLI flag.

``config.json`` next to those files is the ``run-local`` project file (``ws config init``),
not a settings layer: ``project.*`` keys in ``ws config show`` come from it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ._config_core import Layers, Setting, Value, coerce, load_layers, resolve

APP_NAME = "workspace"

DEFAULT_PROTECTED = r"^(main|master|develop|staging)$"

SETTINGS: tuple[Setting, ...] = (
    Setting(
        "gate.skip", [], "QG_SKIP", "Gate checks to skip: gitleaks,commits,lint,design,tests,all"
    ),
    Setting(
        "gate.protected_branches",
        DEFAULT_PROTECTED,
        "QG_PROTECTED",
        "Regex of branches the gate refuses to push to directly",
        empty_env_is_unset=True,  # the hook script reads ${QG_PROTECTED:-default}
    ),
    Setting("gate.timeout_seconds", 900, "QG_TIMEOUT", "Timeout of each gate step"),
    Setting(
        "gate.commit_style",
        "",
        "QG_COMMIT_STYLE",
        "Set to `conventional` to enforce it",
        empty_env_is_unset=True,  # the hook scripts read ${QG_COMMIT_STYLE:-...}
    ),
    Setting(
        "logs.retention_days",
        7,
        "WORKSPACE_LOG_RETENTION_DAYS",
        "Age after which `ws log` entries are pruned",
    ),
    Setting("logs.max_entries", 200, "WORKSPACE_LOG_MAX_ENTRIES", "Most `ws log` entries kept"),
    Setting(
        "output.max_lines",
        20,
        "WORKSPACE_OUTPUT_MAX_LINES",
        "Agent-mode output: lines before truncating",
    ),
    Setting(
        "output.max_chars",
        1500,
        "WORKSPACE_OUTPUT_MAX_CHARS",
        "Agent-mode output: characters before truncating",
    ),
)

# `git config workspace.<name>` already worked for the first two; it ranks between the repo
# file and the environment (env QG_* > git config > repo file > user file > default).
GIT_CONFIG_KEYS = {
    "gate.skip": "workspace.skip",
    "gate.commit_style": "workspace.commitStyle",
    "gate.protected_branches": "workspace.protected",
    "gate.timeout_seconds": "workspace.timeout",
}


def repo_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor holding ``.git`` or ``.workspace``; None outside a repository."""
    here = (start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        if (folder / ".git").exists() or (folder / ".workspace").is_dir():
            return folder
    return None


def layers(root: Path | None = None) -> Layers:
    return load_layers(APP_NAME, root if root is not None else repo_root(), legacy_json=False)


def _git_config(root: Path, name: str) -> str | None:
    """Value of ``git config workspace.<x>`` in ``root`` (None when unset or not a repo)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "config", "--get", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def effective(root: Path | None = None, flags: dict[str, object] | None = None) -> dict[str, Value]:
    """default < user file < repo file < git config < env < flag."""
    top = root if root is not None else repo_root()
    values = resolve(SETTINGS, layers(top), flags=flags)
    by_key = {s.key: s for s in SETTINGS}
    for key, git_name in GIT_CONFIG_KEYS.items():
        if values[key].origin in ("env", "flag"):
            continue
        found = _git_config(top, git_name) if top is not None else None
        if found is not None:
            values[key] = Value(
                coerce(found, by_key[key].default, key), "git", f"git config {git_name}"
            )
    if "QG_SKIP" in os.environ and values["gate.skip"].origin != "flag":  # defined-but-empty wins
        values["gate.skip"] = Value(
            coerce(os.environ["QG_SKIP"], [], "gate.skip"), "env", "QG_SKIP"
        )
    return values


def get(key: str, root: Path | None = None) -> object:
    """Effective value of one setting (default < user < repo < env)."""
    return effective(root)[key].value
