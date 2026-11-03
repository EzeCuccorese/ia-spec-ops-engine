"""``taskflow.toml``: who plays each role, required judges, checks, risk rules and TDD.

User file: ``~/.config/ai-governance/taskflow.toml``. A repository may add
``.ai-governance/taskflow.toml`` and has priority over the user's controls: it adds, replaces (same judge focus / risk rule name) or
switches off (``[disable]``) controls, but never changes who runs with full permissions.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import config_dir
from ..settings import effective
from .models import WORKFLOWS, JsonDict

CONFIG_NAME = "taskflow.toml"
REPO_CONFIG = Path(".ai-governance") / CONFIG_NAME


ROLE_NAMES = ("planner", "validator", "builder")


def default_roles(found: dict | None = None) -> dict[str, JsonDict]:
    """Planner, validator and builder: the ``taskflow.<role>_agent/_model`` settings."""
    found = found or effective()
    return {
        role: {
            "agent": found[f"taskflow.{role}_agent"].value,
            "model": found[f"taskflow.{role}_model"].value,
        }
        for role in ROLE_NAMES
    }


def default_judges(found: dict | None = None) -> list[JsonDict]:
    found = found or effective()
    return [
        {
            "focus": "correctness",
            "agent": found["taskflow.judge_agent"].value,
            "model": found["taskflow.judge_model"].value,
        }
    ]


DEFAULT_CHECKS: list[str] = ["ws check --changed"]
AGENTS_WITH_BINARY = ("antigravity", "codex", "claude")


def agent_binary(agent: str) -> str | None:
    """CLI that runs ``agent`` (``[agents] <agent>_binary``); None for ``human`` or unknown."""
    if agent not in AGENTS_WITH_BINARY:
        return None
    return str(effective()[f"agents.{agent}_binary"].value)


def check_timeout_seconds() -> int:
    """The single timeout of checks, judges and TDD commands (``taskflow.timeout_seconds``)."""
    return int(effective()["taskflow.timeout_seconds"].value)  # type: ignore[call-overload]


@dataclass(frozen=True)
class RiskRule:
    name: str
    paths: tuple[str, ...]
    judges: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    restaging: bool = False


@dataclass(frozen=True)
class FlowConfig:
    workflow: str = "tri-agent"
    roles: dict[str, JsonDict] = field(default_factory=default_roles)
    judges: tuple[JsonDict, ...] = field(default_factory=lambda: tuple(default_judges()))
    checks: tuple[str, ...] = tuple(DEFAULT_CHECKS)
    risk_rules: tuple[RiskRule, ...] = ()
    timeout_seconds: int = field(default_factory=check_timeout_seconds)

    def role(self, name: str) -> JsonDict:
        if name == "judge":
            return dict(self.judges[0]) if self.judges else {}
        return dict(self.roles.get(name, {}))

    def judge_for(self, focus: str) -> JsonDict:
        found = next((j for j in self.judges if j.get("focus") == focus), None)
        if found is None:
            raise ValueError(f"No judge configured for focus '{focus}'")
        return dict(found)

    @property
    def policy_digest(self) -> str:
        policy = {
            "judges": list(self.judges),
            "checks": list(self.checks),
            "risk": [rule.__dict__ for rule in self.risk_rules],
        }
        return hashlib.sha256(
            json.dumps(policy, sort_keys=True, default=list).encode()
        ).hexdigest()[:12]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.workflow not in WORKFLOWS:
            errors.append(f"workflow must be one of {', '.join(WORKFLOWS)}")
        errors += self._judge_errors()
        errors += self._missing_binaries()
        return errors

    def _judge_errors(self) -> list[str]:
        errors: list[str] = []
        builder = self.roles.get("builder", {}).get("agent", "")
        for judge in self.judges:
            if judge.get("agent") == builder and judge.get("agent") != "human":
                errors.append(
                    f"judge '{judge.get('focus')}' uses the builder's agent ({builder}): "
                    "a judge must be a different provider or 'human'"
                )
        if not self.judges:
            errors.append("at least one judge is required")
        if self.workflow == "single-agent" and any(j.get("agent") != "human" for j in self.judges):
            errors.append("single-agent workflow: every judge must be 'human'")
        return errors

    def _missing_binaries(self) -> list[str]:
        errors: list[str] = []
        for name, role in [
            *self.roles.items(),
            *((f"judge {j.get('focus')}", j) for j in self.judges),
        ]:
            binary = agent_binary(str(role.get("agent", "")))
            if binary and shutil.which(binary) is None:
                errors.append(f"{name}: '{binary}' is not installed or not on PATH")
        return errors


def _read_toml(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _rules(raw: list[JsonDict]) -> list[RiskRule]:
    return [
        RiskRule(
            name=str(item.get("name", "rule")),
            paths=tuple(item.get("paths", [])),
            judges=tuple(item.get("judges", [])),
            checks=tuple(item.get("checks", [])),
            restaging=bool(item.get("restaging", False)),
        )
        for item in raw
    ]


def _judge_entries(raw: JsonDict) -> list[JsonDict]:
    """Judges from ``[[judges]]`` or ``[[roles.judges]]``: both files accept both spellings."""
    return [dict(j) for j in [*raw.get("judges", []), *raw.get("roles", {}).get("judges", [])]]


def _merge_local(
    local: JsonDict,
    judges: list[JsonDict],
    checks: list[str],
    rules: list[RiskRule],
    mark: Callable[[str, object], None] = lambda key, value: None,
) -> None:
    """Applies one repository's ``taskflow.toml`` on top of the user's controls.

    A repository may add a control, replace one with the same id (judge ``focus``, risk rule
    ``name``) and switch one off through ``[disable]`` (``judges`` / ``checks`` / ``risk``
    lists of ids). A judge's ``agent`` and ``model`` stay the user's: they decide who runs
    with full permissions.
    """
    for entry in _judge_entries(local):
        position = next(
            (i for i, j in enumerate(judges) if j.get("focus") == entry.get("focus")), None
        )
        if position is None:
            judges.append(entry)
        else:
            old = judges[position]
            judges[position] = {**entry, "agent": old.get("agent"), "model": old.get("model")}
        mark(f"judge.{entry.get('focus')}", "replaced" if position is not None else "added")
    for command in local.get("checks", {}).get("commands", []):
        if command not in checks:
            checks.append(command)
            mark(f"check.{command}", "added")
    for rule in _rules(local.get("risk", {}).get("rules", [])):
        position = next((i for i, r in enumerate(rules) if r.name == rule.name), None)
        if position is None:
            rules.append(rule)
        else:
            rules[position] = rule
        mark(f"risk.{rule.name}", "replaced" if position is not None else "added")
    off = local.get("disable", {})
    for focus in off.get("judges", []):
        judges[:] = [j for j in judges if j.get("focus") != focus]
        mark(f"judge.{focus}", "disabled")
    for command in off.get("checks", []):
        checks[:] = [c for c in checks if c != command]
        mark(f"check.{command}", "disabled")
    for name in off.get("risk", []):
        rules[:] = [r for r in rules if r.name != name]
        mark(f"risk.{name}", "disabled")


def load_config(
    repos: list[Path] | None = None,
    user_file: Path | None = None,
    origins: dict[str, tuple[str, str]] | None = None,
) -> FlowConfig:
    """User config with every bound repository applied on top (add, replace, disable; TDD is
    not configurable: only the user's ``tdd-skip`` approval replaces it).

    ``origins`` (optional) is filled with ``taskflow.<kind>.<id>`` -> (state, source) for
    ``config show``: ``default`` / ``user`` or what a repository did (added, replaced, disabled)."""
    user_path = user_file or config_dir() / CONFIG_NAME
    user = _read_toml(user_path)
    legacy_roles = {k: dict(v) for k, v in user.get("roles", {}).items() if k != "judges"}
    found = _settings(user_path, repos or [], legacy_roles)
    roles = {**legacy_roles, **default_roles(found)}
    for name, legacy in legacy_roles.items():
        if name in roles:
            roles[name] = {**legacy, **roles[name]}
    judges = [_with_configured_judge(j, found) for j in _judge_entries(user)] or default_judges(
        found
    )
    checks = list(user.get("checks", {}).get("commands", DEFAULT_CHECKS))
    rules = _rules(user.get("risk", {}).get("rules", []))
    if origins is not None:
        owner = "user" if user_path.is_file() else "default"
        for j in judges:
            origins[f"taskflow.judge.{j.get('focus')}"] = (owner, str(user_path))
        for command in checks:
            origins[f"taskflow.check.{command}"] = (owner, str(user_path))
        for rule in rules:
            origins[f"taskflow.risk.{rule.name}"] = (owner, str(user_path))
    for repo in repos or []:
        source = str(repo / REPO_CONFIG)

        def mark(key: str, state: object, source: str = source) -> None:
            if origins is not None:
                origins[f"taskflow.{key}"] = (f"repo ({state})", source)

        _merge_local(_read_toml(repo / REPO_CONFIG), judges, checks, rules, mark)
    return FlowConfig(
        workflow=str(user.get("workflow", "tri-agent")),
        roles=roles,
        judges=tuple(judges),
        checks=tuple(checks),
        risk_rules=tuple(rules),
        timeout_seconds=int(found["taskflow.timeout_seconds"].value),
    )


def _settings(user_path: Path, repos: list[Path], legacy_roles: dict[str, JsonDict]) -> dict:
    """Settings with the legacy taskflow.toml folded into the user layer, below config.toml.

    ``timeout_seconds`` of either taskflow.toml counts as that layer's value. A legacy
    ``[roles.<role>]`` supplies that role's agent and model (model defaults to empty, never
    to another agent's default) so the environment still outranks it. Roles, workflow, judges
    and checks stay user-owned: a repository can add controls, never replace them.
    """
    legacy: dict[str, object] = {}
    for role in ROLE_NAMES:
        if role in legacy_roles:
            legacy[f"taskflow.{role}_agent"] = legacy_roles[role].get("agent", "")
            legacy[f"taskflow.{role}_model"] = legacy_roles[role].get("model", "")
    repo_extra = {repo / REPO_CONFIG: "taskflow" for repo in repos}
    return effective(
        repos[0] if repos else None,
        user_extra={user_path: "taskflow"},
        repo_extra=repo_extra,
        user_values=(user_path, legacy),
    )


def _with_configured_judge(judge: JsonDict, found: dict) -> JsonDict:
    """A legacy judge, with ``taskflow.judge_agent/_model`` applied over it when config.toml or the
    environment set them (default < legacy taskflow.toml < config.toml < env); its focus stays."""
    merged = dict(judge)
    for attribute in ("agent", "model"):
        setting = found[f"taskflow.judge_{attribute}"]
        if setting.origin in ("user", "env"):  # not "default": the legacy file outranks that
            merged[attribute] = setting.value
    return merged
