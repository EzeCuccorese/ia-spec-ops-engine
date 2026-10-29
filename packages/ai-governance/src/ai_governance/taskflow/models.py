"""Task state persisted as ``state.json``: one task (or subtask) per directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from typing import Any, Literal

PHASES: tuple[str, ...] = ("plan", "validate", "work", "judge", "staging", "review", "done")
EXIT_PHASES: tuple[str, ...] = ("findings",)
STATUSES: tuple[str, ...] = ("active", "paused", "closed")
ROLES: tuple[str, ...] = ("planner", "validator", "builder", "judge")
READER_ROLES: frozenset[str] = frozenset({"planner", "validator", "judge"})
VERDICTS: tuple[str, ...] = ("pass", "concerns", "block", "info")
WORKFLOWS: tuple[str, ...] = ("tri-agent", "dual-agent", "single-agent", "manual")

Verdict = Literal["pass", "concerns", "block", "info"]
JsonDict = dict[str, Any]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    title: str
    status: str = "active"
    summary: str = ""
    parent: str = ""
    workflow: str = "tri-agent"
    owner_mode: str = "self"  # self | external (findings go to another owner)
    phase: str = "plan"
    blocked: JsonDict = field(default_factory=dict)  # {owner, needs, since}
    active_subtask: str = ""
    subtasks: list[str] = field(default_factory=list)
    steps: list[JsonDict] = field(default_factory=list)  # {text, done}
    facts: list[JsonDict] = field(default_factory=list)  # {text, at}
    decisions: list[JsonDict] = field(default_factory=list)  # {text, why, at}
    links: list[JsonDict] = field(default_factory=list)  # {title, url}
    references: list[JsonDict] = field(default_factory=list)  # {kind, value, url}
    repos: list[JsonDict] = field(default_factory=list)  # {path, branch, integration_branch, pr}
    code_stamp: JsonDict = field(default_factory=dict)
    policy: JsonDict = field(default_factory=dict)  # accepted judges/checks/risk rules
    tdd: JsonDict = field(default_factory=dict)  # {red, green, skip}
    rounds: list[JsonDict] = field(default_factory=list)
    approvals: list[JsonDict] = field(default_factory=list)
    deployments: list[JsonDict] = field(default_factory=list)  # {env, repo, sha, provenance, at}
    evidence: list[JsonDict] = field(default_factory=list)  # {kind, path, stamp, deployed_sha}
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> JsonDict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: JsonDict) -> Task:
        if not isinstance(data, dict) or "id" not in data:
            raise ValueError("task state must be an object with an 'id'")
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    @property
    def stamp_key(self) -> str:
        return str(self.code_stamp.get("key", ""))

    def is_open(self) -> bool:
        return self.status != "closed"
