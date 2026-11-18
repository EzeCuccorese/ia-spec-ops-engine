"""Recompute a task's code stamp, tolerating bound repositories gone from disk.

A vanished repo keeps its last stamp entry (flagged ``missing``) and the policy digest is
pinned, so the stamp key does not move.
"""

from __future__ import annotations

from pathlib import Path

from .config import FlowConfig
from .models import Task
from .repos import partition, report
from .stamp import code_stamp
from .store import TaskStore


def refresh(store: TaskStore, task: Task, config: FlowConfig, remote: bool = False) -> Task:
    """Recompute the code stamp of the current bound repositories."""
    if not task.repos:
        return task
    previous = task.code_stamp
    pinned = bool(partition(task.repos).missing) and bool(previous.get("key"))
    digest = str(previous.get("policy", "")) if pinned else config.policy_digest
    stamp = code_stamp(task.repos, digest, check_remote=remote, carried=previous.get("repos", []))
    present = {str(e["repo"]) for e in stamp["repos"] if not e.get("missing")}
    gone = [str(b["path"]) for b in task.repos if str(Path(b["path"])) not in present]
    report(gone)
    return store.mutate(task.id, lambda t: setattr(t, "code_stamp", stamp))
