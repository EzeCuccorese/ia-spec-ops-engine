"""Every ai-governance setting in one place: default, environment variable and where it is read.

Layers (lowest to highest): default < ``~/.config/ai-governance/config.toml`` <
``<repo>/.ai-governance/config.toml`` < environment variable < CLI flag.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict, Unpack

from ._config_core import (
    ConfigError,
    Layers,
    Setting,
    Value,
    flatten,
    load_layers,
    read_table,
    resolve,
)
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
        "frugality.condense_timeout_seconds",
        30,
        "AI_GOVERNANCE_FRUGAL_TIMEOUT_SECONDS",
        "Timeout of the `ws condense` call",
    ),
    Setting("output.max_lines", 20, "AI_GOVERNANCE_OUTPUT_MAX_LINES", "Lines before output is cut"),
    Setting(
        "output.max_chars",
        1500,
        "AI_GOVERNANCE_OUTPUT_MAX_CHARS",
        "Characters before output is cut",
    ),
    Setting(
        "hooks.gate_command",
        "ws check --changed --cache --json",
        "AI_GOVERNANCE_GATE_COMMAND",
        "Command of the turn-end quality gate (`--budget N` is appended)",
    ),
    Setting(
        "hooks.gate_budget_chars",
        1500,
        "AI_GOVERNANCE_GATE_BUDGET_CHARS",
        "Size of the failure summary the gate reports",
    ),
    Setting(
        "hooks.gate_timeout_seconds",
        900,
        "AI_GOVERNANCE_GATE_TIMEOUT_SECONDS",
        "Timeout of the turn-end quality gate",
    ),
    Setting(
        "taskflow.timeout_seconds",
        1800,
        "AI_GOVERNANCE_CHECK_TIMEOUT_SECONDS",
        "Timeout of each check, judge and TDD command",
    ),
    Setting(
        "taskflow.allowed_agents",
        ["antigravity", "codex", "claude"],
        "AI_GOVERNANCE_ALLOWED_AGENTS",
        "Agents taskflow may use, comma separated (user level; a repo file can only narrow it)",
    ),
    *(
        Setting(
            f"taskflow.{role}_{field}",
            default,
            f"AI_GOVERNANCE_{role.upper()}_{field.upper()}",
            f"{field.capitalize()} of the {role} role (user level only: a repo cannot change it)",
        )
        for role, agent, model in (
            ("planner", "antigravity", "gemini-4-argon-high"),
            ("validator", "codex", "gpt-6.1-sol"),
            ("builder", "claude", ""),
            ("judge", "codex", "gpt-6.1-sol"),
        )
        for field, default in (("agent", agent), ("model", model))
    ),
    Setting(
        "agents.codex_scout_model",
        "gpt-6-luna",
        "AI_GOVERNANCE_CODEX_SCOUT_MODEL",
        "Model of the Codex scout subagent written at install",
    ),
    Setting(
        "corporate.packs",
        [],
        "AI_GOVERNANCE_CORPORATE",
        "Company packs to install, comma separated (empty: every pack present)",
        empty_env_is_value=True,  # AI_GOVERNANCE_CORPORATE= means "install no pack"
    ),
    Setting(
        "atlassian.timeout_seconds",
        30.0,
        "ATLASSIAN_TIMEOUT",
        "HTTP timeout of Jira and Confluence calls",
    ),
    Setting(
        "pricing.timeout_seconds",
        10.0,
        "AI_GOVERNANCE_PRICING_TIMEOUT_SECONDS",
        "Timeout of the price feed download",
    ),
    Setting(
        "schedule.label",
        "com.ai-governance.prices-update",
        "AI_GOVERNANCE_SCHEDULE_LABEL",
        "launchd label of the price-refresh agent",
    ),
    Setting(
        "risk_window.cutoff_hour",
        16,
        "AI_GOVERNANCE_RISK_WINDOW_CUTOFF_HOUR",
        "Cutoff hour (0-23) of the production risk window (Monday to Thursday)",
    ),
    Setting(
        "risk_window.friday_cutoff_hour",
        13,
        "AI_GOVERNANCE_RISK_WINDOW_FRIDAY_CUTOFF_HOUR",
        "Cutoff hour (0-23) of the production risk window on Friday",
    ),
)

# Role and judge settings decide who runs with full permissions: only the user's own
# files may change them (a repository can add controls, never swap the agents).
USER_ONLY_PREFIXES = (
    "taskflow.planner_",
    "taskflow.validator_",
    "taskflow.builder_",
    "taskflow.judge_",
    "taskflow.allowed_agents",  # a repository narrows it through its own strict reader
    "agents.",
    "hooks.",  # hooks.gate_command picks the program the automatic stop hook runs
    "corporate.",  # which company packs get installed
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
    user_values: tuple[Path, dict[str, object]] | None = None,
) -> Layers:
    """File layers. ``user_extra`` / ``repo_extra`` map a legacy file to its table prefix."""
    base = load_layers(APP_NAME, root if root is not None else repo_root())
    legacy = {config_dir() / name: prefix for name, prefix in LEGACY_USER_FILES.items()}
    for path, prefix in {**legacy, **(user_extra or {})}.items():
        _inject(base.user, base.user_files, path, prefix)
    if user_values is not None:  # already-flat legacy values, below config.toml
        path, values = user_values
        for name, value in values.items():
            if name not in base.user:
                base.user[name] = value
                base.user_files[name] = path
    for path, prefix in (repo_extra or {}).items():
        _inject(base.repo, base.repo_files, path, prefix)
    return base


class LayerOptions(TypedDict, total=False):
    user_extra: dict[Path, str]
    repo_extra: dict[Path, str]
    user_values: tuple[Path, dict[str, object]]


def _validate_settings(values: dict[str, Value]) -> None:
    for key in ("risk_window.cutoff_hour", "risk_window.friday_cutoff_hour"):
        if key in values:
            raw = values[key].value
            if not isinstance(raw, int) or isinstance(raw, bool) or not (0 <= raw <= 23):
                raise ConfigError(
                    f"Invalid value for {key}: {raw!r} (must be an hour between 0 and 23)"
                )


def effective(
    root: Path | None = None,
    flags: dict[str, object] | None = None,
    **extra: Unpack[LayerOptions],
) -> dict[str, Value]:
    found = layers(root, **extra)
    values = resolve(SETTINGS, found, flags=flags)
    # Re-resolve user-only settings without the repo layer.
    user_only = [s for s in SETTINGS if s.key.startswith(USER_ONLY_PREFIXES)]
    no_repo = Layers(found.user, {}, found.user_files, {})
    values.update(resolve(user_only, no_repo, flags=flags))
    _validate_settings(values)
    return values


def get(
    key: str,
    root: Path | None = None,
    flags: dict[str, object] | None = None,
    **extra: Unpack[LayerOptions],
) -> object:
    """Effective value of one setting (default < user < repo < env < flag)."""
    return effective(root, flags, **extra)[key].value
