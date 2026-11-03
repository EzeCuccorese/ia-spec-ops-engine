"""Control-plane integrity of a dispatched reader round.

A reader runs with the user's permissions, and the taskflow store is writable by it. The
repository fingerprints cover the code; this module covers the files that make a round
authoritative: ``state.json`` (rounds, the whole code stamp the gates read, approvals, evidence), earlier round
markdown, check evidence and the round's own ``dispatch.json``.

At dispatch the coordinator records a baseline of those files inside ``dispatch.json`` and
keeps a seal of that file (its sha256) outside the task directory, under ``<store>/seals``.
At collect, anything in the baseline that changed is reported. Legitimate concurrent engine
writes (new rounds, approvals, evidence, facts, other fields of ``state.json``) are not in the
baseline's scope, and the worker's two designated files (``answer.txt`` and ``receipt.txt``)
are not control files.

Limit: a malicious worker running as the same user can rewrite the baseline, the seal and
the files together, so this cannot make the store tamper-proof. It detects accidental
writes, the case of a reader that follows a taskflow instruction it should have ignored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import JsonDict, Task
from .store import TaskStore


class DispatchError(ValueError):
    """A dispatch, collect or abort that is refused; nothing was changed."""


class UsageRefusal(DispatchError):
    """A request that can never work as written (exit code 2), not a state to wait out."""


@dataclass(frozen=True)
class CheckedBaseline:
    """What the engine's checks ran against: the code stamp and, for every real checkout, its
    path, HEAD and tree fingerprint. A judge round is dispatched only against this exact state."""

    stamp: str
    repos: tuple[JsonDict, ...]


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_json(value: object) -> str:
    return digest_text(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def digest_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "missing"


VOLATILE_STAMP_KEYS = frozenset({"at"})  # when the stamp was computed
VOLATILE_REPO_KEYS = frozenset({"integration_sha", "remote_status"})  # network-only, not hashed


def stamp_projection(stamp: JsonDict) -> JsonDict:
    """The code stamp the gates read (key, repos, policy, obligations, reductions), without
    the fields a harmless refresh changes: when it was computed and the network-only SHA."""
    kept = {k: v for k, v in stamp.items() if k not in VOLATILE_STAMP_KEYS}
    repos = stamp.get("repos")
    if isinstance(repos, list):
        kept["repos"] = [
            {k: v for k, v in r.items() if k not in VOLATILE_REPO_KEYS}
            if isinstance(r, dict)
            else r
            for r in repos
        ]
    return kept


def baseline(task: Task) -> JsonDict:
    """What a reader must not change, as seen now by the coordinator."""
    return {
        "stamp_key": task.stamp_key,
        "stamp": digest_json(stamp_projection(task.code_stamp)),
        "rounds": {str(r.get("n")): digest_json(r) for r in task.rounds},
        "round_files": {
            str(r["file"]): digest_file(r["file"]) for r in task.rounds if r.get("file")
        },
        "approvals": [digest_json(a) for a in task.approvals],
        "evidence": [
            {"entry": digest_json(e), "file": digest_file(e["path"]) if e.get("path") else ""}
            for e in task.evidence
        ],
    }


def _prefix_changes(label: str, old: list[str], new: list[str]) -> list[str]:
    if len(new) < len(old):
        return [f"{label}: {len(old) - len(new)} entries removed"]
    return [f"{label} #{i + 1}" for i, digest in enumerate(old) if new[i] != digest]


def _stamp_changed(now: JsonDict, base: JsonDict) -> bool:
    """Whole projection when the baseline has one (older dispatch records: the key only)."""
    name = "stamp" if "stamp" in base else "stamp_key"
    return bool(now[name] != base.get(name))


def drift(task: Task, base: JsonDict) -> list[str]:
    """Items of ``base`` that differ now; appended rounds, approvals and evidence do not count."""
    now = baseline(task)
    changed: list[str] = []
    if _stamp_changed(now, base):
        changed.append("task.code_stamp")
    for number, value in dict(base.get("rounds", {})).items():
        if now["rounds"].get(number) != value:
            changed.append(f"round record {number}")
    for name, value in dict(base.get("round_files", {})).items():
        if now["round_files"].get(name, digest_file(name)) != value:
            changed.append(f"round file {Path(name).name}")
    changed += _prefix_changes("task.approvals", base.get("approvals", []), now["approvals"])
    old_ev, new_ev = list(base.get("evidence", [])), now["evidence"]
    if len(new_ev) < len(old_ev):
        changed.append("task.evidence: entries removed")
    changed += [
        f"evidence #{i + 1}" for i, item in enumerate(old_ev) if new_ev[i : i + 1] != [item]
    ]
    return changed


def seal_path(store: TaskStore, task_id: str, number: int) -> Path:
    return store.root / "seals" / f"{task_id}.{number:03d}.sha256"
