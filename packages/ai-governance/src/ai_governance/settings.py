"""Every ai-governance setting in one place: default, environment variable and where it is read.

Layers (lowest to highest): default < ``~/.config/ai-governance/config.toml`` <
``<repo>/.ai-governance/config.toml`` < environment variable < CLI flag.
"""

from __future__ import annotations

from pathlib import Path

from ._config_core import Layers, Setting, Value, flatten, load_layers, read_table, resolve
from .paths import APP_NAME, config_dir

SETTINGS: tuple[Setting, ...] = (
    Setting(
        "frugality.threshold_chars",
        4000,
        "AI_GOVERNANCE_FRUGAL_THRESHOLD_CHARS",
        "Shell output longer than this is condensed",
    ),
    Setting(
        "frugality.budget_chars",
        2500,
        "AI_GOVERNANCE_FRUGAL_BUDGET_CHARS",
        "Size the condensed output is cut down to",
    ),
    Setting(
        "taskflow.timeout_seconds",
        1800,
        "AI_GOVERNANCE_CHECK_TIMEOUT_SECONDS",
        "Timeout of each check, judge and TDD command",
    ),
    Setting(
        "atlassian.timeout_seconds",
        30.0,
        "ATLASSIAN_TIMEOUT",
        "HTTP timeout of Jira and Confluence calls",
    ),
    Setting(
        "schedule.label",
        "com.ai-governance.prices-update",
        "AI_GOVERNANCE_SCHEDULE_LABEL",
        "launchd label of the price-refresh agent",
    ),
)


def repo_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor holding ``.git`` or ``.ai-governance``; None outside a repository."""
    here = (start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        if (folder / ".git").exists() or (folder / f".{APP_NAME}").is_dir():
            return folder
    return None


# Pre-config.toml files, read at the lowest priority of their layer: name -> table prefix.
LEGACY_USER_FILES = {"frugal.json": "frugality"}


def _inject(target: dict[str, object], sources: dict[str, Path], path: Path, prefix: str) -> None:
    """Adds a legacy file's keys under ``prefix`` where config.toml did not already set them."""
    for key, value in flatten(read_table(path, APP_NAME)).items():
        name = f"{prefix}.{key}"
        if name not in target:
            target[name] = value
            sources[name] = path


def layers(
    root: Path | None = None,
    *,
    user_extra: dict[Path, str] | None = None,
    repo_extra: dict[Path, str] | None = None,
) -> Layers:
    """File layers. ``user_extra`` / ``repo_extra`` map a legacy file to its table prefix."""
    base = load_layers(APP_NAME, root if root is not None else repo_root())
    legacy = {config_dir() / name: prefix for name, prefix in LEGACY_USER_FILES.items()}
    for path, prefix in {**legacy, **(user_extra or {})}.items():
        _inject(base.user, base.user_files, path, prefix)
    for path, prefix in (repo_extra or {}).items():
        _inject(base.repo, base.repo_files, path, prefix)
    return base


def effective(
    root: Path | None = None,
    flags: dict[str, object] | None = None,
    **extra: dict[Path, str],
) -> dict[str, Value]:
    return resolve(SETTINGS, layers(root, **extra), flags=flags)


def get(key: str, root: Path | None = None, **extra: dict[Path, str]) -> object:
    """Effective value of one setting (default < user < repo < env)."""
    return effective(root, **extra)[key].value
