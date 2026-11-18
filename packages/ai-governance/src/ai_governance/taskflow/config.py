"""``taskflow.toml``: agents, models, efforts and denied models.

User file: ``~/.config/ai-governance/taskflow.toml``. Repositories can narrow
``allowed_agents`` via ``.ai-governance/config.toml`` and add to ``denied_models`` via
``.ai-governance/config.toml`` or ``.ai-governance/taskflow.toml``. Repositories cannot
weaken user restrictions or define executable check commands.
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .._config_core import Value
from ..paths import config_dir
from ..settings import effective
from .agents import (
    DEFAULT_MODELS,
    REPO_FILE,
    Allowed,
    AllowedAgentsError,
    _read_repo_toml,
    fallback_agent,
    read_regular_text,
    resolve_allowed,
    source_problem,
    user_source_problems,
)
from .models import WORKFLOWS, JsonDict

CONFIG_NAME = "taskflow.toml"
REPO_CONFIG = Path(".ai-governance") / CONFIG_NAME

ROLE_NAMES = ("planner", "validator", "builder", "debater")
EFFORT_ROLES = ("planner", "validator", "builder", "judge", "debater")
DEFAULT_TIMEOUT_SECONDS = 1800


def default_roles(found: dict | None = None) -> dict[str, JsonDict]:
    """Role agent and model defaults from ``taskflow.<role>_agent/_model`` settings."""
    found = found or effective()
    return {
        role: {
            "agent": found[f"taskflow.{role}_agent"].value,
            "model": found[f"taskflow.{role}_model"].value,
        }
        for role in ROLE_NAMES
        if f"taskflow.{role}_agent" in found and f"taskflow.{role}_model" in found
    }


def default_efforts(found: dict | None = None) -> dict[str, str]:
    """Reasoning effort per role from ``taskflow.<role>_effort`` settings."""
    found = found or effective()
    return {
        role: str(found[f"taskflow.{role}_effort"].value).strip()
        for role in EFFORT_ROLES
        if f"taskflow.{role}_effort" in found
    }


def normalize_model(model: str) -> str:
    """Normalized model identifier: stripped and lower-cased."""
    return str(model).strip().lower()


def matches_denied_model(model: str, denied: Iterable[str]) -> bool:
    """True when ``model`` matches any entry in ``denied`` (ignoring optional ``provider/``)."""
    norm = normalize_model(model)
    if not norm:
        return False
    entries = {item for raw in denied if (item := normalize_model(raw))}
    if norm in entries:
        return True
    if "/" in norm:
        return norm.split("/", 1)[1] in entries
    return any("/" in entry and entry.split("/", 1)[1] == norm for entry in entries)


def check_timeout_seconds() -> int:
    """Configured timeout (``taskflow.timeout_seconds``) or default."""
    setting = effective().get("taskflow.timeout_seconds")
    return int(setting.value) if setting is not None else DEFAULT_TIMEOUT_SECONDS  # type: ignore[call-overload]


@dataclass(frozen=True)
class FlowConfig:
    workflow: str = "tri-agent"
    roles: dict[str, JsonDict] = field(default_factory=default_roles)
    timeout_seconds: int = field(default_factory=check_timeout_seconds)
    allowed: Allowed = field(default_factory=lambda: _default_allowed())
    efforts: dict[str, str] = field(default_factory=default_efforts)
    denied_models: frozenset[str] = field(default_factory=frozenset)
    denied_model_problems: tuple[str, ...] = ()

    normalize_model = staticmethod(normalize_model)
    matches_denied_model = staticmethod(matches_denied_model)

    def effort(self, role: str) -> str:
        return str(self.efforts.get(role, "")).strip()

    def model_error(self, model: str) -> str | None:
        if self.denied_model_problems:
            return "; ".join(self.denied_model_problems)
        if matches_denied_model(model, self.denied_models):
            return f"model '{model}' is denied by taskflow.denied_models"
        return None

    @property
    def policy_digest(self) -> str:
        return hashlib.sha256(b"{}").hexdigest()[:12]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.workflow not in WORKFLOWS:
            errors.append(f"workflow must be one of {', '.join(WORKFLOWS)}")
        errors += self.allowed.errors()
        for problem in self.denied_model_problems:
            if problem not in errors:
                errors.append(problem)
        errors += self._allowed_errors()
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
        if self.allowed.errors():
            return []
        return [
            f"{name}: {problem}"
            for name, role in self.roles.items()
            if (problem := self.agent_error(str(role.get("agent", "")))) and role.get("agent")
        ]


def _user_sources(user_path: Path) -> list[Path]:
    """Every user file the allowed-agents setting can come from."""
    return [config_dir() / "config.toml", config_dir() / "config.json", user_path]


def _default_allowed() -> Allowed:
    problems = user_source_problems(_user_sources(config_dir() / CONFIG_NAME))
    return resolve_allowed(effective()["taskflow.allowed_agents"].value, [], problems)


def _narrowed(found: dict, allowed: Allowed) -> dict:
    """``found`` with every default role agent moved to an allowed agent."""
    result = dict(found)
    builder = _swap(result, "builder", allowed, "")
    for role in ("planner", "validator", "judge", "debater"):
        _swap(result, role, allowed, builder)
    return result


def _swap(found: dict, role: str, allowed: Allowed, builder: str) -> str:
    key = f"taskflow.{role}_agent"
    current = found.get(key)
    if current is None:
        return ""
    if current.origin != "default":
        return str(current.value)
    agent = fallback_agent(role, str(current.value), allowed, builder)
    if agent != current.value:
        found[key] = Value(agent, "default", "allowed_agents")
        model_key = f"taskflow.{role}_model"
        model = found.get(model_key)
        if model is not None and model.origin == "default":
            found[model_key] = Value(DEFAULT_MODELS.get(agent, ""), "default", "allowed_agents")
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


def load_config(
    repos: list[Path] | None = None,
    user_file: Path | None = None,
    origins: dict[str, tuple[str, str]] | None = None,
) -> FlowConfig:
    """Load user config with repo-level ``allowed_agents`` narrowing and additive ``denied_models``."""
    del origins  # kept for signature compatibility
    return _build(repos or [], user_file)[0]


def describe_config(repos: list[Path], user_file: Path | None = None) -> dict[str, Value]:
    """What ``load_config`` resolved, row by row, with the layer each value came from."""
    return _build(repos, user_file)[1]


def _merged_roles(legacy_roles: dict[str, JsonDict], found: dict) -> dict[str, JsonDict]:
    roles = {**legacy_roles, **default_roles(found)}
    for name, legacy in legacy_roles.items():
        if name in roles:
            roles[name] = {**legacy, **roles[name]}
    return roles


@dataclass(frozen=True)
class _DeniedModels:
    models: frozenset[str]
    problems: tuple[str, ...] = ()
    extended_by: tuple[str, ...] = ()
    from_user_taskflow: bool = False


def _parse_denied_list(raw: object, where: str, *, allow_csv: bool = False) -> frozenset[str]:
    if allow_csv and isinstance(raw, str):
        items: list[object] | tuple[object, ...] = [
            part.strip() for part in raw.split(",") if part.strip()
        ]
    elif isinstance(raw, list | tuple):
        items = raw
    else:
        raise ValueError(f"{where}: denied_models must be a list of model names")
    found: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{where}: denied_models holds a non-string item {item!r}")
        norm = normalize_model(item)
        if not norm:
            raise ValueError(f"{where}: denied_models holds an empty model name")
        found.add(norm)
    return frozenset(found)


def _read_denied_field(raw: object, where: str) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, dict):
        return _parse_denied_list(raw, where)
    if not raw:
        return frozenset()
    key = "models" if "models" in raw else "denied_models"
    if key not in raw:
        raise ValueError(f"{where}: [denied_models] must define 'models'")
    return _parse_denied_list(raw[key], where)


def _read_taskflow_denied(data: JsonDict, where: str) -> frozenset[str]:
    found = set(_read_denied_field(data.get("denied_models"), where))
    table = data.get("taskflow")
    if table is None:
        return frozenset(found)
    if not isinstance(table, dict):
        raise ValueError(f"{where}: [taskflow] must be a table")
    if "denied_models" in table:
        found |= _parse_denied_list(table["denied_models"], where)
    return frozenset(found)


def _read_repo_config_denied(repo: Path) -> frozenset[str]:
    path = repo / REPO_FILE
    where = str(path)
    try:
        os.lstat(path.parent)
    except FileNotFoundError:
        return frozenset()
    except OSError as exc:
        raise ValueError(f"{where}: cannot read it ({exc})") from exc
    data = _read_repo_toml(path)
    if data is None:
        return frozenset()
    table = data.get("taskflow")
    if table is None:
        return frozenset()
    if not isinstance(table, dict):
        raise ValueError(f"{where}: [taskflow] must be a table")
    if "denied_models" not in table:
        return frozenset()
    return _parse_denied_list(table["denied_models"], where)


def _repo_denied_entries(
    repo: Path, local: JsonDict
) -> tuple[list[tuple[str, frozenset[str]]], list[str]]:
    entries: list[tuple[str, frozenset[str]]] = []
    errs: list[str] = []
    try:
        cfg = _read_repo_config_denied(repo)
    except (AllowedAgentsError, ValueError) as exc:
        errs.append(str(exc))
    else:
        if cfg:
            entries.append((str(repo / REPO_FILE), cfg))
    try:
        tf = _read_taskflow_denied(local, str(repo / REPO_CONFIG))
    except ValueError as exc:
        errs.append(str(exc))
    else:
        if tf:
            entries.append((str(repo / REPO_CONFIG), tf))
    return entries, errs


def _setting_denied(found: dict, problems: list[str]) -> set[str]:
    try:
        return set(
            _parse_denied_list(
                found["taskflow.denied_models"].value, "taskflow.denied_models", allow_csv=True
            )
        )
    except ValueError as exc:
        problems.append(str(exc))
        return set()


def _user_taskflow_denied(user: JsonDict, user_path: Path, problems: list[str]) -> frozenset[str]:
    try:
        return _read_taskflow_denied(user, str(user_path))
    except ValueError as exc:
        problems.append(str(exc))
        return frozenset()


def _resolve_denied(
    found: dict,
    user_info: tuple[JsonDict, Path, tuple[str, ...]],
    locals_: dict[Path, JsonDict],
) -> _DeniedModels:
    user, user_path, user_problems = user_info
    problems = list(user_problems)
    denied = _setting_denied(found, problems)
    user_tm = _user_taskflow_denied(user, user_path, problems)
    denied |= user_tm
    extended_by: list[str] = []
    for repo, local in locals_.items():
        entries, errs = _repo_denied_entries(repo, local)
        problems.extend(errs)
        for source, items in entries:
            if not items <= denied:
                denied |= items
                extended_by.append(source)
    return _DeniedModels(frozenset(denied), tuple(problems), tuple(extended_by), bool(user_tm))


def _build(
    repos: list[Path],
    user_file: Path | None,
) -> tuple[FlowConfig, dict[str, Value]]:
    user_path = user_file or config_dir() / CONFIG_NAME
    problems = user_source_problems(_user_sources(user_path))
    user = {} if source_problem(user_path) else _read_toml(user_path)
    legacy_roles = {k: dict(v) for k, v in user.get("roles", {}).items() if k != "judges"}
    locals_ = {repo: _read_toml(repo / REPO_CONFIG) for repo in repos}
    settings = _settings(user_path, legacy_roles)
    allowed = resolve_allowed(settings["taskflow.allowed_agents"].value, repos, problems)
    found = _narrowed(settings, allowed)
    denied = _resolve_denied(found, (user, user_path, problems), locals_)
    timeout_setting = found.get("taskflow.timeout_seconds")
    timeout = int(timeout_setting.value) if timeout_setting is not None else DEFAULT_TIMEOUT_SECONDS
    config = FlowConfig(
        workflow=str(user.get("workflow", "tri-agent")),
        roles=_merged_roles(legacy_roles, found),
        timeout_seconds=timeout,
        allowed=allowed,
        efforts=default_efforts(found),
        denied_models=denied.models,
        denied_model_problems=denied.problems,
    )
    return config, _setting_rows(config, found, (denied, user_path))


def _denied_row(config: FlowConfig, found: dict, denied: _DeniedModels, user_path: Path) -> Value:
    if config.denied_model_problems:
        return Value([], "blocked", "; ".join(config.denied_model_problems))
    if denied.extended_by:
        return Value(sorted(config.denied_models), "repo (extended)", denied.extended_by[0])
    listed = found["taskflow.denied_models"]
    if listed.origin == "default" and denied.from_user_taskflow:
        return Value(sorted(config.denied_models), "user", str(user_path))
    return Value(sorted(config.denied_models), listed.origin, listed.source)


def _setting_rows(
    config: FlowConfig, found: dict, denied_info: tuple[_DeniedModels, Path]
) -> dict[str, Value]:
    rows: dict[str, Value] = {}
    for role in ROLE_NAMES:
        for attribute in ("agent", "model"):
            key = f"taskflow.{role}_{attribute}"
            if key in found and role in config.roles:
                got = found[key]
                rows[key] = Value(config.roles[role][attribute], got.origin, got.source)
    for role in EFFORT_ROLES:
        key = f"taskflow.{role}_effort"
        if key in found:
            got = found[key]
            rows[key] = Value(config.effort(role), got.origin, got.source)
    listed = found["taskflow.allowed_agents"]
    if config.allowed.errors():
        listed = Value([], "blocked", "; ".join(config.allowed.errors()))
    elif config.allowed.narrowed_by:
        listed = Value(
            sorted(config.allowed.agents), "repo (narrowed)", config.allowed.narrowed_by[0]
        )
    rows["taskflow.allowed_agents"] = listed
    denied, user_path = denied_info
    rows["taskflow.denied_models"] = _denied_row(config, found, denied, user_path)
    if "taskflow.timeout_seconds" in found:
        timeout = found["taskflow.timeout_seconds"]
        rows["taskflow.timeout_seconds"] = Value(
            config.timeout_seconds, timeout.origin, timeout.source
        )
    return rows


def _settings(user_path: Path, legacy_roles: dict[str, JsonDict]) -> dict:
    """User settings with legacy ``taskflow.toml`` folded into the user layer."""
    legacy: dict[str, object] = {}
    for role in ROLE_NAMES:
        if role in legacy_roles:
            legacy[f"taskflow.{role}_agent"] = legacy_roles[role].get("agent", "")
            legacy[f"taskflow.{role}_model"] = legacy_roles[role].get("model", "")
            if "effort" in legacy_roles[role]:
                legacy[f"taskflow.{role}_effort"] = legacy_roles[role].get("effort", "")
    return effective(
        None,
        user_extra={user_path: "taskflow"},
        user_values=(user_path, legacy),
    )
