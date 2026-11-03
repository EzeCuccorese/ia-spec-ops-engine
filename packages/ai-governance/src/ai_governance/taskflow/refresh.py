"""Recompute a task's code stamp and risk, tolerating bound repositories gone from disk.

A vanished repo keeps its last stamp entry (flagged ``missing``) and the policy digest is
pinned, so the stamp key does not move and evidence recorded at it stays valid. The risk is
frozen with every stamp (complete obligations, not a path list), so eligibility cannot be
weakened by deleting the checkout, and a task stamped before freezing existed is rebuilt
from its accepted policy with every rule assumed matched.
"""

from __future__ import annotations

from pathlib import Path

from .config import FlowConfig
from .models import JsonDict, Task
from .policy import policy_reductions, policy_summary
from .repos import guard, partition, report
from .risk import RiskAssessment, assess, freeze, legacy_obligations, merge, thaw
from .stamp import changed_paths, code_stamp, merge_base
from .store import TaskStore


def _base_ref(repo: JsonDict) -> str:
    branch = str(repo.get("integration_branch", ""))
    return merge_base(Path(repo["path"]), branch) if branch else ""


def _live_paths(repos: list[JsonDict], present: set[str]) -> tuple[list[str], list[str]]:
    """Changed paths of the repos that are on disk, and those that vanished meanwhile."""
    paths: list[str] = []
    vanished: list[str] = []
    for repo in repos:
        if str(Path(repo["path"])) not in present:
            continue
        base = _base_ref(repo)

        def changed(path: Path, base: str = base) -> list[str]:
            return changed_paths(path, base)

        found = guard(repo, changed)
        if found is None:
            vanished.append(str(repo["path"]))
        else:
            paths += found
    return paths, vanished


def _frozen_risk(
    live: RiskAssessment, previous: JsonDict, key: str, accepted: JsonDict, config: FlowConfig
) -> RiskAssessment:
    """Obligations while some repo is missing."""
    stored = previous.get("obligations")
    if not stored:
        return merge(live, legacy_obligations(accepted, config))
    frozen = thaw(stored)
    # Same code, same key: the evidence was judged against exactly these obligations, so
    # they are used as a unit (a control added to the live config since is not mixed in).
    return frozen if key == previous.get("key") else merge(live, frozen)


def _policy_state(task: Task, config: FlowConfig, pinned: bool) -> tuple[JsonDict, list[str]]:
    current = policy_summary(config)
    # A task starts from the user's own policy, so what a repository switches off before
    # the first stamp is a reduction like any later one.
    accepted = task.policy or config.baseline_policy or current
    if pinned:  # the vanished repo's own policy cannot be re-read: keep what was accepted
        return accepted, list(task.code_stamp.get("policy_reduced", []))
    acknowledged = set(accepted.get("acknowledged_repo_reductions", []))
    lost = {*policy_reductions(accepted, current), *config.repo_reductions} - acknowledged
    return accepted, sorted(lost)


def refresh(
    store: TaskStore, task: Task, config: FlowConfig, remote: bool = False
) -> tuple[Task, RiskAssessment]:
    """Recompute the code stamp and the risk of the current changes."""
    if not task.repos:
        return task, assess(config, [])
    previous = task.code_stamp
    pinned = bool(partition(task.repos).missing) and bool(previous.get("key"))
    digest = str(previous["policy"]) if pinned else config.policy_digest
    stamp = code_stamp(task.repos, digest, check_remote=remote, carried=previous.get("repos", []))
    present = {str(e["repo"]) for e in stamp["repos"] if not e.get("missing")}
    paths, vanished = _live_paths(task.repos, present)
    gone = [str(b["path"]) for b in task.repos if str(Path(b["path"])) not in present]
    report([*gone, *vanished])
    accepted, stamp["policy_reduced"] = _policy_state(task, config, pinned)
    risk = assess(config, paths)
    if gone or vanished:
        risk = _frozen_risk(risk, previous, stamp["key"], accepted, config)
        if not previous.get("obligations") or previous.get("legacy_types"):
            stamp["legacy_types"] = True  # judge types were rebuilt, not recovered
    stamp["obligations"] = freeze(risk, config)

    def save(t: Task) -> None:
        t.code_stamp = stamp
        t.policy = t.policy or accepted

    return store.mutate(task.id, save), risk


def legacy_notice(task: Task) -> str:
    """Operator guidance while judge types are only a conservative reconstruction."""
    if not task.code_stamp.get("legacy_types"):
        return ""
    gone = [str(e["repo"]) for e in task.code_stamp.get("repos", []) if e.get("missing")]
    steps = "; ".join(f"ai-governance taskflow unbind {task.id} --repo {path}" for path in gone)
    return (
        "legacy state: this task was stamped before judge types were recorded, so every judge "
        "focus is treated as needing an engine verdict while a bound repo is missing. To recover, "
        f"restore the missing path, or run: {steps}; bind the replacement repo "
        f"(taskflow bind {task.id} --repo <path>); then taskflow stamp {task.id}, re-run "
        f"`taskflow judge {task.id}` and re-approve whatever the new stamp expired"
    )
