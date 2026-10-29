"""``taskflow.toml``: who plays each role, required judges, checks, risk rules and TDD.

User file: ``~/.config/ai-governance/taskflow.toml``. A repository may add
``.ai-governance/taskflow.toml``: its risk rules, judges and checks are appended, never
replacing the user's, so a repository can only add controls.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import config_dir
from .models import WORKFLOWS, JsonDict

CONFIG_NAME = "taskflow.toml"
REPO_CONFIG = Path(".ai-governance") / CONFIG_NAME

DEFAULT_ROLES: dict[str, JsonDict] = {
    "planner": {"agent": "antigravity", "model": "gemini-4-argon-high"},
    "validator": {"agent": "codex", "model": "gpt-6.1-sol"},
    "builder": {"agent": "claude", "model": ""},
}
DEFAULT_JUDGES: list[JsonDict] = [
    {"focus": "correctness", "agent": "codex", "model": "gpt-6.1-sol"},
]
DEFAULT_CHECKS: list[str] = ["ws check --changed"]
DEFAULT_TIMEOUT_SECONDS = 1800
AGENT_BINARIES = {"antigravity": "agy", "codex": "codex", "claude": "claude"}


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
    roles: dict[str, JsonDict] = field(default_factory=lambda: dict(DEFAULT_ROLES))
    judges: tuple[JsonDict, ...] = tuple(DEFAULT_JUDGES)
    checks: tuple[str, ...] = tuple(DEFAULT_CHECKS)
    risk_rules: tuple[RiskRule, ...] = ()
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

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
            binary = AGENT_BINARIES.get(str(role.get("agent", "")))
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
    local: JsonDict, judges: list[JsonDict], checks: list[str], rules: list[RiskRule]
) -> None:
    known = {j.get("focus") for j in judges}
    judges += [j for j in _judge_entries(local) if j.get("focus") not in known]
    checks += [c for c in local.get("checks", {}).get("commands", []) if c not in checks]
    rules += _rules(local.get("risk", {}).get("rules", []))


def load_config(repos: list[Path] | None = None, user_file: Path | None = None) -> FlowConfig:
    """User config plus the additions of every bound repository (TDD is not configurable:
    only the user's ``tdd-skip`` approval replaces it)."""
    user = _read_toml(user_file or config_dir() / CONFIG_NAME)
    roles = dict(DEFAULT_ROLES)
    roles.update({k: dict(v) for k, v in user.get("roles", {}).items() if k != "judges"})
    judges = _judge_entries(user) or [dict(j) for j in DEFAULT_JUDGES]
    checks = list(user.get("checks", {}).get("commands", DEFAULT_CHECKS))
    rules = _rules(user.get("risk", {}).get("rules", []))
    for repo in repos or []:
        _merge_local(_read_toml(repo / REPO_CONFIG), judges, checks, rules)
    return FlowConfig(
        workflow=str(user.get("workflow", "tri-agent")),
        roles=roles,
        judges=tuple(judges),
        checks=tuple(checks),
        risk_rules=tuple(rules),
        timeout_seconds=int(user.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
    )
