"""``taskflow.toml``: who plays each role, required judges, checks, risk rules and TDD.

User file: ``~/.config/ai-governance/taskflow.toml``. A repository may add
``.ai-governance/taskflow.toml`` and has priority over the user's controls: it adds, replaces (same judge focus / risk rule name) or
switches off (``[disable]``) controls, but never changes who runs with full permissions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from .._config_core import Value
from ..paths import config_dir, state_dir
from ..settings import effective
from .agents import (
    DEFAULT_MODELS,
    HUMAN,
    Allowed,
    fallback_agent,
    provider,
    read_regular_text,
    resolve_allowed,
    user_source_problems,
)
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
    # Controls a trusted repository removed or weakened relative to what was in force before it.
    repo_reductions: tuple[str, ...] = ()
    # Agents allowed for the bound repositories: the user's set narrowed by each repo file.
    allowed: Allowed = field(default_factory=lambda: _default_allowed())

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
        errors += self.allowed.errors()
        errors += self._allowed_errors()
        errors += self._judge_errors()
        errors += self._validator_errors()
        return errors

    def agent_error(self, agent: str) -> str | None:
        """Why ``agent`` may not be used here (an explicit choice is never swapped), else None."""
        if self.allowed.permits(agent):
            return None
        if self.allowed.problems:
            return f"'{agent}' is not allowed here: {'; '.join(self.allowed.problems)}"
        names = ", ".join(sorted(self.allowed.agents)) or "none"
        return f"'{agent}' is not allowed here (allowed agents: {names}, human)"

    def _allowed_errors(self) -> list[str]:
        if self.allowed.errors():  # already reported once: do not repeat it per role
            return []
        named = [
            *((name, role) for name, role in self.roles.items()),
            *((f"judge '{j.get('focus')}'", j) for j in self.judges),
        ]
        return [
            f"{name}: {problem}"
            for name, role in named
            if (problem := self.agent_error(str(role.get("agent", "")))) and role.get("agent")
        ]

    def _validator_errors(self) -> list[str]:
        builder = str(self.roles.get("builder", {}).get("agent", ""))
        validator = str(self.roles.get("validator", {}).get("agent", ""))
        if (
            not validator
            or provider(validator) in (HUMAN, "")
            or provider(validator) != provider(builder)
        ):
            return []
        return [
            f"validator uses the builder's provider ({provider(builder)}): "
            "the validator must be a different provider than the builder"
        ]

    def _judge_errors(self) -> list[str]:
        errors: list[str] = []
        builder = str(self.roles.get("builder", {}).get("agent", ""))
        for judge in self.judges:
            agent = str(judge.get("agent", ""))
            if provider(agent) == provider(builder) and provider(agent) != HUMAN:
                errors.append(
                    f"judge '{judge.get('focus')}' uses the builder's provider ({provider(builder)}): "
                    "a judge must be a different provider or 'human'"
                )
        if not self.judges:
            errors.append("at least one judge is required")
        if self.workflow == "single-agent" and any(j.get("agent") != "human" for j in self.judges):
            errors.append("single-agent workflow: every judge must be 'human'")
        return errors


def _user_sources(user_path: Path) -> list[Path]:
    """Every user file the allowed-agents setting can come from."""
    return [config_dir() / "config.toml", config_dir() / "config.json", user_path]


def _default_allowed() -> Allowed:
    problems = user_source_problems(_user_sources(config_dir() / CONFIG_NAME))
    return resolve_allowed(effective()["taskflow.allowed_agents"].value, [], problems)


def _narrowed(found: dict, allowed: Allowed) -> dict:
    """``found`` with every role whose agent is still the built-in default moved to an allowed
    agent (and that agent's default model). Explicit choices are left alone: ``validate``
    reports them, they are never swapped."""
    result = dict(found)
    builder = _swap(result, "builder", allowed, "")
    for role in ("planner", "validator", "judge"):
        _swap(result, role, allowed, builder)
    return result


def _swap(found: dict, role: str, allowed: Allowed, builder: str) -> str:
    key = f"taskflow.{role}_agent"
    current = found[key]
    if current.origin != "default":
        return str(current.value)
    agent = fallback_agent(role, str(current.value), allowed, builder)
    if agent != current.value:
        found[key] = Value(agent, "default", "allowed_agents")
        model = found[f"taskflow.{role}_model"]
        if model.origin == "default":
            found[f"taskflow.{role}_model"] = Value(
                DEFAULT_MODELS.get(agent, ""), "default", "allowed_agents"
            )
    return agent


def _read_toml(path: Path) -> JsonDict:
    """A missing file is an empty table; one that exists but is not a readable regular file
    (FIFO, directory, dangling link, no permission) is an error, never read as empty."""
    try:
        return tomllib.loads(read_regular_text(path))
    except FileNotFoundError:
        if os.path.lexists(path):
            raise ValueError(f"{path}: dangling link, cannot read it") from None
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{path}: cannot read it ({exc})") from exc


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


def _rule_reductions(name: str, rule: JsonDict, now: JsonDict | None) -> list[str]:
    if now is None:
        return [f"rule:{name}"]
    lost = [
        f"rule:{name}:{kind}:{item}"
        for kind in ("paths", "judges", "checks")
        for item in rule.get(kind, [])
        if item not in now.get(kind, [])
    ]
    if rule.get("restaging") and not now.get("restaging"):
        lost.append(f"rule:{name}:restaging")
    return lost


def policy_reductions(baseline: JsonDict, current: JsonDict) -> list[str]:
    """Every accepted control that is gone or weaker now (adding controls is never one)."""
    lost = [
        f"{kind}:{item}"
        for kind in ("judges", "checks")
        for item in baseline.get(kind, [])
        if item not in current.get(kind, [])
    ]
    for name, rule in baseline.get("rules", {}).items():
        lost += _rule_reductions(name, rule, current.get("rules", {}).get(name))
    return sorted(lost)


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
    commands: tuple[str, ...]  # what this repository introduced
    config: JsonDict | None = None  # the whole repo control config that gets approved


def trust_file() -> Path:
    return state_dir() / "taskflow" / "trust.json"


def repo_digest(local: JsonDict) -> str:
    """Hash of a repository's WHOLE parsed taskflow.toml (keys sorted, list order kept).

    Any edit (a command, a rule's paths, a judge, ``[disable]``, ...) changes it, and it does
    not depend on other repositories or on the user's own config (older schemes never match).
    """
    canonical = json.dumps(local, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "v4:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def is_trusted(repo: Path, local: JsonDict) -> bool:
    try:
        known = json.loads(trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(known, dict) and known.get(str(repo.resolve())) == repo_digest(local)


def record_trust(repo: Path, local: JsonDict) -> str:
    """Remembers that the user approved exactly this control config of ``repo``."""
    path = trust_file()
    try:
        known = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    digest = repo_digest(local)
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


@dataclass
class _Controls:
    """The judges, checks and risk rules in force while the layers are applied in order."""

    judges: list[JsonDict]
    checks: list[str]
    rules: list[RiskRule]

    def summary(self) -> JsonDict:
        return summarize(self.judges, self.checks, self.rules)


@dataclass
class _Overlay:
    """How one repository's file is applied: who runs its judges and how changes are noted."""

    trusted_runner: JsonDict
    where: str
    mark: Callable[[str, object], None] = lambda key, value: None


_Item = TypeVar("_Item")


def _position(items: list[_Item], key: Callable[[_Item], object], wanted: object) -> int | None:
    return next((i for i, item in enumerate(items) if key(item) == wanted), None)


def _apply_judges(local: JsonDict, controls: _Controls, overlay: _Overlay) -> None:
    for entry in _judge_entries(local):
        position = _position(controls.judges, lambda j: j.get("focus"), entry.get("focus"))
        if position is None:
            controls.judges.append(_runner_of(entry, overlay.trusted_runner, overlay.where))
        else:
            old = controls.judges[position]
            keep = {"agent": old.get("agent"), "model": old.get("model")}
            controls.judges[position] = _runner_of(entry, keep, overlay.where)
        overlay.mark(f"judge.{entry.get('focus')}", "replaced" if position is not None else "added")


def _apply_checks(local: JsonDict, controls: _Controls, overlay: _Overlay) -> None:
    for command in local.get("checks", {}).get("commands", []):
        if command not in controls.checks:
            controls.checks.append(command)
            overlay.mark(f"check.{command}", "added")


def _apply_rules(local: JsonDict, controls: _Controls, overlay: _Overlay) -> None:
    for rule in _rules(local.get("risk", {}).get("rules", [])):
        position = _position(controls.rules, lambda r: r.name, rule.name)
        if position is None:
            controls.rules.append(rule)
        else:
            controls.rules[position] = rule
        overlay.mark(f"risk.{rule.name}", "replaced" if position is not None else "added")


def _apply_disables(local: JsonDict, controls: _Controls, overlay: _Overlay) -> None:
    off = local.get("disable", {})
    for focus in off.get("judges", []):
        controls.judges[:] = [j for j in controls.judges if j.get("focus") != focus]
        overlay.mark(f"judge.{focus}", "disabled")
    for command in off.get("checks", []):
        controls.checks[:] = [c for c in controls.checks if c != command]
        overlay.mark(f"check.{command}", "disabled")
    for name in off.get("risk", []):
        controls.rules[:] = [r for r in controls.rules if r.name != name]
        overlay.mark(f"risk.{name}", "disabled")


def _merge_local(local: JsonDict, controls: _Controls, overlay: _Overlay) -> None:
    """Applies one repository's ``taskflow.toml`` on top of the user's controls.

    A repository may add a control, replace one with the same id (judge ``focus``, risk rule
    ``name``) and switch one off through ``[disable]`` (``judges`` / ``checks`` / ``risk``
    lists of ids). Every judge it adds or replaces runs with the user's agent and model.
    """
    _apply_judges(local, controls, overlay)
    _apply_checks(local, controls, overlay)
    _apply_rules(local, controls, overlay)
    _apply_disables(local, controls, overlay)


def _control_ids(local: JsonDict) -> list[str]:
    ids = [f"judge.{j.get('focus')}" for j in _judge_entries(local)]
    ids += [f"check.{c}" for c in local.get("checks", {}).get("commands", [])]
    ids += [f"risk.{r.name}" for r in _rules(local.get("risk", {}).get("rules", []))]
    off = local.get("disable", {})
    ids += [f"judge.{x}" for x in off.get("judges", [])]
    ids += [f"check.{x}" for x in off.get("checks", [])]
    ids += [f"risk.{x}" for x in off.get("risk", [])]
    return ids


def _has_content(node: object) -> bool:
    """True when a parsed taskflow.toml says anything: empty tables and lists do not count."""
    if isinstance(node, dict):
        return any(_has_content(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_content(v) for v in node)
    return node not in (None, "")


def _defined_commands(local: JsonDict) -> tuple[str, ...]:
    """Every command a repository config would run (for the trust prompt)."""
    rules = _rules(local.get("risk", {}).get("rules", []))
    found = [*local.get("checks", {}).get("commands", []), *(c for r in rules for c in r.checks)]
    return tuple(dict.fromkeys(found))


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


def _merged_roles(legacy_roles: dict[str, JsonDict], found: dict) -> dict[str, JsonDict]:
    roles = {**legacy_roles, **default_roles(found)}
    for name, legacy in legacy_roles.items():
        if name in roles:
            roles[name] = {**legacy, **roles[name]}
    return roles


def _user_controls(user: JsonDict, found: dict) -> _Controls:
    judges = [_with_configured_judge(j, found) for j in _judge_entries(user)]
    return _Controls(
        judges or default_judges(found),
        list(user.get("checks", {}).get("commands", DEFAULT_CHECKS)),
        _rules(user.get("risk", {}).get("rules", [])),
    )


def _mark_user_controls(controls: _Controls, marks: dict, owner: tuple[str, str]) -> None:
    for j in controls.judges:
        marks[f"taskflow.judge.{j.get('focus')}"] = owner
    for command in controls.checks:
        marks[f"taskflow.check.{command}"] = owner
    for rule in controls.rules:
        marks[f"taskflow.risk.{rule.name}"] = owner


def _mark_pending(repo: Path, local: JsonDict, marks: dict) -> None:
    source = str(repo / REPO_CONFIG)
    marks[f"taskflow.repo[{repo}]"] = ("repo (pending trust)", source)
    for key in _control_ids(local):
        marks.setdefault(f"taskflow.{key}", ("repo (pending trust)", source))


@dataclass
class _RepoLayers:
    """What applying the repositories produced: pending files and reductions by trusted ones."""

    pending: list[PendingTrust]
    reductions: set[str]


def _apply_repos(
    files: list[tuple[Path, JsonDict, bool]], controls: _Controls, runner: tuple[JsonDict, dict]
) -> _RepoLayers:
    """``files``: each repository with its parsed taskflow.toml and whether it is trusted."""
    trusted_runner, marks = runner
    layers = _RepoLayers([], set())
    for repo, local, trusted in files:
        if not _has_content(local):
            continue
        if not trusted:
            # Pure direnv rule: until the user approves this file it is ignored entirely
            # (no adds, replaces or disables), not just its commands.
            layers.pending.append(
                PendingTrust(str(repo), repo_digest(local), _defined_commands(local), local)
            )
            _mark_pending(repo, local, marks)
            continue
        source = str(repo / REPO_CONFIG)

        def mark(key: str, state: object, source: str = source) -> None:
            marks[f"taskflow.{key}"] = (f"repo ({state})", source)

        before = controls.summary()  # user + earlier trusted repositories
        _merge_local(local, controls, _Overlay(trusted_runner, source, mark))
        layers.reductions.update(policy_reductions(before, controls.summary()))
    return layers


def _trusted_repos(locals_: dict[Path, JsonDict]) -> list[Path]:
    return [r for r, local in locals_.items() if _has_content(local) and is_trusted(r, local)]


def _repo_files(
    locals_: dict[Path, JsonDict], active: list[Path]
) -> list[tuple[Path, JsonDict, bool]]:
    return [(repo, local, repo in active) for repo, local in locals_.items()]


def _owner(user_path: Path) -> tuple[str, str]:
    return ("user" if user_path.is_file() else "default", str(user_path))


def _build(
    repos: list[Path],
    user_file: Path | None,
    origins: dict[str, tuple[str, str]] | None,
) -> tuple[FlowConfig, dict[str, Value]]:
    user_path = user_file or config_dir() / CONFIG_NAME
    problems = user_source_problems(_user_sources(user_path))
    user = {} if problems else _read_toml(user_path)
    legacy_roles = {k: dict(v) for k, v in user.get("roles", {}).items() if k != "judges"}
    locals_ = {repo: _read_toml(repo / REPO_CONFIG) for repo in repos}
    active = _trusted_repos(locals_)
    settings = _settings(user_path, active, legacy_roles)
    allowed = resolve_allowed(settings["taskflow.allowed_agents"].value, repos, problems)
    found = _narrowed(settings, allowed)
    controls = _user_controls(user, found)
    baseline = controls.summary()  # the user's own policy, before any repository
    marks = origins if origins is not None else {}
    owner = _owner(user_path)
    _mark_user_controls(controls, marks, owner)
    trusted_runner = {
        "agent": found["taskflow.judge_agent"].value,
        "model": found["taskflow.judge_model"].value,
    }
    layers = _apply_repos(_repo_files(locals_, active), controls, (trusted_runner, marks))
    config = FlowConfig(
        workflow=str(user.get("workflow", "tri-agent")),
        roles=_merged_roles(legacy_roles, found),
        judges=tuple(controls.judges),
        checks=tuple(controls.checks),
        risk_rules=tuple(controls.rules),
        timeout_seconds=int(found["taskflow.timeout_seconds"].value),
        baseline_policy=baseline,
        pending_trust=tuple(layers.pending),
        repo_reductions=tuple(sorted(layers.reductions)),
        allowed=allowed,
    )
    return config, _rows(config, found, marks)


def _setting_rows(config: FlowConfig, found: dict) -> dict[str, Value]:
    rows: dict[str, Value] = {}
    for role in ROLE_NAMES:
        for attribute in ("agent", "model"):
            got = found[f"taskflow.{role}_{attribute}"]
            rows[f"taskflow.{role}_{attribute}"] = Value(
                config.roles[role][attribute], got.origin, got.source
            )
    listed = found["taskflow.allowed_agents"]
    if config.allowed.errors():
        listed = Value([], "blocked", "; ".join(config.allowed.errors()))
    elif config.allowed.narrowed_by:
        listed = Value(
            sorted(config.allowed.agents), "repo (narrowed)", config.allowed.narrowed_by[0]
        )
    rows["taskflow.allowed_agents"] = listed
    timeout = found["taskflow.timeout_seconds"]
    rows["taskflow.timeout_seconds"] = Value(config.timeout_seconds, timeout.origin, timeout.source)
    return rows


def _control_values(config: FlowConfig) -> dict[str, object]:
    values: dict[str, object] = {}
    for j in config.judges:
        values[f"taskflow.judge.{j.get('focus')}"] = {
            "agent": j.get("agent"),
            "model": j.get("model"),
        }
    for command in config.checks:
        values[f"taskflow.check.{command}"] = command
    for r in config.risk_rules:
        values[f"taskflow.risk.{r.name}"] = {
            "paths": list(r.paths),
            "judges": list(r.judges),
            "checks": list(r.checks),
            "restaging": r.restaging,
        }
    return values


def _row_value(origin: str, in_force: object) -> object:
    """Nothing of an untrusted repository is in force; a disabled control has no value."""
    if "pending" in origin:
        return "ignored until trusted"
    if in_force is None and "disabled" in origin:
        return "disabled"
    return in_force


def _rows(config: FlowConfig, found: dict, marks: dict[str, tuple[str, str]]) -> dict[str, Value]:
    """``config show`` rows, all taken from the resolved ``config`` itself."""
    rows = _setting_rows(config, found)
    values = _control_values(config)
    for key, (origin, source) in marks.items():
        value = _row_value(origin, values.get(key))
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
