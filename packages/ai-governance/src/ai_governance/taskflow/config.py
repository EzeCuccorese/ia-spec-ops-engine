"""``taskflow.toml``: who plays each role, required judges, checks, risk rules and TDD.

User file: ``~/.config/ai-governance/taskflow.toml``. A repository may add
``.ai-governance/taskflow.toml`` and has priority over the user's controls: it adds, replaces (same judge focus / risk rule name) or
switches off (``[disable]``) controls, but never changes who runs with full permissions.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .._config_core import Value
from ..paths import config_dir, state_dir
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
    # The user's own policy (no repository applied): where a task's first approval starts from.
    baseline_policy: JsonDict | None = None
    pending_trust: tuple[PendingTrust, ...] = ()

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


UNTRUSTED_RUNNER_FIELDS = ("agent", "model", "binary", "command")


def summarize(
    judges: Iterable[JsonDict], checks: Iterable[str], rules: Iterable[RiskRule]
) -> JsonDict:
    """The controls of a policy, rule by rule (what ``policy_summary`` records)."""
    return {
        "judges": sorted(str(j.get("focus")) for j in judges),
        "checks": sorted(checks),
        "rules": {
            r.name: {
                "paths": sorted(r.paths),
                "judges": sorted(r.judges),
                "checks": sorted(r.checks),
                "restaging": r.restaging,
            }
            for r in rules
        },
    }


@dataclass(frozen=True)
class PendingTrust:
    """Check commands a repository defines that the user has not approved yet."""

    repo: str
    digest: str
    commands: tuple[str, ...]


def trust_file() -> Path:
    return state_dir() / "taskflow" / "trust.json"


def command_digest(commands: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(commands))).encode()).hexdigest()[:16]


def is_trusted(repo: Path, commands: Iterable[str]) -> bool:
    try:
        known = json.loads(trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(known, dict) and known.get(str(repo.resolve())) == command_digest(commands)


def record_trust(repo: Path, commands: Iterable[str]) -> str:
    """Remembers that the user approved exactly this command set for ``repo``."""
    path = trust_file()
    try:
        known = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    digest = command_digest(commands)
    known[str(repo.resolve())] = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digest


def _runner_of(entry: JsonDict, trusted: JsonDict, where: str) -> JsonDict:
    """A repository judge runs with the user's agent and model, whatever the file says."""
    ignored = [f for f in UNTRUSTED_RUNNER_FIELDS if f in entry]
    if ignored:
        print(
            f"warning: ignoring {', '.join(ignored)} of judge '{entry.get('focus')}' in {where}: "
            "who runs a judge is a user-level setting",
            file=sys.stderr,
        )
    kept = {k: v for k, v in entry.items() if k not in UNTRUSTED_RUNNER_FIELDS}
    return {**kept, "agent": trusted["agent"], "model": trusted["model"]}


def _merge_local(
    local: JsonDict,
    judges: list[JsonDict],
    checks: list[str],
    rules: list[RiskRule],
    mark: Callable[[str, object], None] = lambda key, value: None,
    trusted_runner: JsonDict | None = None,
    where: str = "",
) -> None:
    """Applies one repository's ``taskflow.toml`` on top of the user's controls.

    A repository may add a control, replace one with the same id (judge ``focus``, risk rule
    ``name``) and switch one off through ``[disable]`` (``judges`` / ``checks`` / ``risk``
    lists of ids). Every judge it adds or replaces runs with the user's agent and model.
    """
    runner = trusted_runner or {"agent": "", "model": ""}
    for entry in _judge_entries(local):
        position = next(
            (i for i, j in enumerate(judges) if j.get("focus") == entry.get("focus")), None
        )
        if position is None:
            judges.append(_runner_of(entry, runner, where))
        else:
            old = judges[position]
            judges[position] = _runner_of(
                entry, {"agent": old.get("agent"), "model": old.get("model")}, where
            )
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


def _untrusted(
    repo: Path,
    user_commands: set[str],
    checks: list[str],
    rules: list[RiskRule],
    before: tuple[list[str], list[RiskRule]],
) -> tuple[PendingTrust | None, list[str], list[RiskRule]]:
    """Strips the commands this repository introduced unless the user approved that set.

    A command the user already defines (user checks or user rules) needs no approval.
    """
    old_checks, old_rules = before
    introduced = {c for c in checks if c not in old_checks}
    introduced |= {c for r in rules for c in r.checks if c not in user_commands}
    introduced -= user_commands
    if not introduced or is_trusted(repo, introduced):
        return None, checks, rules
    pending = PendingTrust(str(repo), command_digest(introduced), tuple(sorted(introduced)))
    kept_checks = [c for c in checks if c not in introduced]
    kept_rules = [
        RiskRule(
            r.name,
            r.paths,
            r.judges,
            tuple(c for c in r.checks if c not in introduced),
            r.restaging,
        )
        for r in rules
    ]
    return pending, kept_checks, kept_rules


def load_config(
    repos: list[Path] | None = None,
    user_file: Path | None = None,
    origins: dict[str, tuple[str, str]] | None = None,
) -> FlowConfig:
    """User config with every bound repository applied on top (add, replace, disable; TDD is
    not configurable: only the user's ``tdd-skip`` approval replaces it).

    Repository check commands run only after ``taskflow trust`` approved that exact set.
    ``origins`` (optional) is filled with ``taskflow.<kind>.<id>`` -> (state, source) for
    ``config show``: ``default`` / ``user`` or what a repository did (added, replaced, disabled)."""
    return _build(repos or [], user_file, origins)[0]


def describe_config(repos: list[Path], user_file: Path | None = None) -> dict[str, Value]:
    """What ``load_config`` resolved, row by row, with the layer each value came from."""
    return _build(repos, user_file, None)[1]


def _build(
    repos: list[Path],
    user_file: Path | None,
    origins: dict[str, tuple[str, str]] | None,
) -> tuple[FlowConfig, dict[str, Value]]:
    user_path = user_file or config_dir() / CONFIG_NAME
    user = _read_toml(user_path)
    legacy_roles = {k: dict(v) for k, v in user.get("roles", {}).items() if k != "judges"}
    found = _settings(user_path, repos, legacy_roles)
    roles = {**legacy_roles, **default_roles(found)}
    for name, legacy in legacy_roles.items():
        if name in roles:
            roles[name] = {**legacy, **roles[name]}
    judges = [_with_configured_judge(j, found) for j in _judge_entries(user)] or default_judges(
        found
    )
    checks = list(user.get("checks", {}).get("commands", DEFAULT_CHECKS))
    rules = _rules(user.get("risk", {}).get("rules", []))
    baseline = summarize(judges, checks, rules)  # the user's own policy, before any repository
    user_commands = set(checks) | {c for r in rules for c in r.checks}
    owner = "user" if user_path.is_file() else "default"
    marks = origins if origins is not None else {}
    for j in judges:
        marks[f"taskflow.judge.{j.get('focus')}"] = (owner, str(user_path))
    for command in checks:
        marks[f"taskflow.check.{command}"] = (owner, str(user_path))
    for rule in rules:
        marks[f"taskflow.risk.{rule.name}"] = (owner, str(user_path))
    trusted_runner = {
        "agent": found["taskflow.judge_agent"].value,
        "model": found["taskflow.judge_model"].value,
    }
    pending: list[PendingTrust] = []
    for repo in repos:
        source = str(repo / REPO_CONFIG)

        def mark(key: str, state: object, source: str = source) -> None:
            marks[f"taskflow.{key}"] = (f"repo ({state})", source)

        before = (list(checks), list(rules))
        _merge_local(
            _read_toml(repo / REPO_CONFIG), judges, checks, rules, mark, trusted_runner, source
        )
        waiting, checks, rules = _untrusted(repo, user_commands, checks, rules, before)
        if waiting is not None:
            pending.append(waiting)
            for command in waiting.commands:
                marks[f"taskflow.check.{command}"] = ("repo (pending trust)", source)
    config = FlowConfig(
        workflow=str(user.get("workflow", "tri-agent")),
        roles=roles,
        judges=tuple(judges),
        checks=tuple(checks),
        risk_rules=tuple(rules),
        timeout_seconds=int(found["taskflow.timeout_seconds"].value),
        baseline_policy=baseline,
        pending_trust=tuple(pending),
    )
    return config, _rows(config, found, marks, pending)


def _rows(
    config: FlowConfig,
    found: dict,
    marks: dict[str, tuple[str, str]],
    pending: list[PendingTrust],
) -> dict[str, Value]:
    """``config show`` rows, all taken from the resolved ``config`` itself."""
    rows: dict[str, Value] = {}
    for role in ROLE_NAMES:
        for attribute in ("agent", "model"):
            got = found[f"taskflow.{role}_{attribute}"]
            rows[f"taskflow.{role}_{attribute}"] = Value(
                config.roles[role][attribute], got.origin, got.source
            )
    rows["taskflow.timeout_seconds"] = Value(
        config.timeout_seconds,
        found["taskflow.timeout_seconds"].origin,
        found["taskflow.timeout_seconds"].source,
    )
    waiting = {c for p in pending for c in p.commands}
    values: dict[str, object] = {}
    for j in config.judges:
        values[f"taskflow.judge.{j.get('focus')}"] = {
            "agent": j.get("agent"),
            "model": j.get("model"),
        }
    for command in (*config.checks, *waiting):
        values[f"taskflow.check.{command}"] = command
    for r in config.risk_rules:
        values[f"taskflow.risk.{r.name}"] = {
            "paths": list(r.paths),
            "judges": list(r.judges),
            "checks": list(r.checks),
            "restaging": r.restaging,
        }
    for key, (origin, source) in marks.items():
        value = values.get(key, "disabled" if "disabled" in origin else None)
        if value is not None:
            rows[key] = Value(value, origin, source)
    return rows


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
