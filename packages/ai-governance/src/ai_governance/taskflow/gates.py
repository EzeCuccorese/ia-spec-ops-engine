"""Phase transitions: what must be true before a task (or subtask) moves forward.

Moving back (e.g. judge -> work after "block") is always allowed. Moving forward goes one
phase at a time, except that ``staging`` is optional unless a risk rule demands it.
Only rounds the engine ran itself count as judgments; ``round record`` adds context,
never a verdict that opens a gate. The same checks guard every exit: ``phase``,
``judge``, builder rounds and ``close``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import tdd
from .approvals import valid_approval
from .config import FlowConfig
from .models import EXIT_PHASES, PHASES, JsonDict, Task
from .risk import RiskAssessment

NEXT_COMMAND: dict[str, str] = {
    "plan": "taskflow round <ID> run --role planner --prompt-file <brief.md>",
    "validate": "taskflow round <ID> run --role validator --prompt-file <review.md>",
    "work": "implement in the bound worktree; taskflow tdd <ID> red/green; commit; taskflow phase <ID> judge",
    "judge": "taskflow judge <ID>",
    "staging": "the user deploys; taskflow deploy <ID> ...; taskflow evidence <ID> --kind staging ...",
    "review": "clean up and rebase; taskflow judge <ID> on the final SHA; then ask for production",
    "done": "taskflow close <ID>",
    "findings": "taskflow findings <ID> --out <file>; hand it to the owner; taskflow close <ID>",
}


def _engine_rounds(task: Task, role: str, *, valid_only: bool = True) -> list[JsonDict]:
    return [
        r
        for r in task.rounds
        if r.get("role") == role
        and r.get("source") == "engine"
        and (r.get("state") == "valid" or not valid_only)
    ]


def _last_n(rounds: list[JsonDict]) -> int:
    return max((int(r["n"]) for r in rounds), default=0)


def _heads(task: Task) -> dict[str, str]:
    return {str(s["repo"]): str(s["head"]) for s in task.code_stamp.get("repos", [])}


def checks_unmet(task: Task, stamp_key: str) -> list[str]:
    """The judge's checks must have passed on the current code in every bound repository."""
    missing = []
    for repo in _heads(task):
        runs = [e for e in task.evidence if e.get("kind") == "checks" and e.get("repo") == repo]
        latest = runs[-1] if runs else None
        if latest is None or latest.get("stamp") != stamp_key:
            missing.append(f"checks: not run on the current code of {repo} (taskflow judge)")
        elif not latest.get("passed"):
            missing.append(f"checks failed on {repo}: {latest.get('path')}")
    return missing


def judges_unmet(task: Task, risk: RiskAssessment, config: FlowConfig, stamp_key: str) -> list[str]:
    """Every required focus needs a ``pass`` on the current code; the latest attempt counts,
    so a later timeout or error blocks again."""
    missing: list[str] = []
    attempts = _engine_rounds(task, "judge", valid_only=False)
    for focus in risk.judges:
        if _is_human(config, focus):
            if not valid_approval(task.approvals, "review", stamp_key, focus):
                missing.append(f"judge '{focus}' (human): approve --action review --target {focus}")
            continue
        latest = max(
            (r for r in attempts if r.get("focus") == focus),
            key=lambda r: int(r["n"]),
            default=None,
        )
        if latest is None:
            missing.append(f"judge '{focus}': no verdict yet")
        elif latest.get("stamp") != stamp_key:
            missing.append(f"judge '{focus}': stale (code changed after round {latest['n']:03d})")
        elif latest.get("state") != "valid":
            missing.append(
                f"judge '{focus}': round {latest['n']:03d} invalid ({latest.get('reason')})"
            )
        elif latest.get("verdict") != "pass":
            missing.append(f"judge '{focus}': {latest.get('verdict')} in round {latest['n']:03d}")
    return missing


def _is_human(config: FlowConfig, focus: str) -> bool:
    return any(j.get("focus") == focus and j.get("agent") == "human" for j in config.judges)


def plan_round(task: Task) -> int:
    """The plan an approval refers to: the latest valid validator round (0 if none)."""
    return _last_n(_engine_rounds(task, "validator"))


def plan_approved(task: Task) -> bool:
    """The user approved this task's current plan; re-planning makes the approval stale."""
    approval = valid_approval(task.approvals, "plan", "", task.id)
    return approval is not None and int(approval.get("plan_round", -1)) == plan_round(task)


def work_unmet(task: Task) -> list[str]:
    """A builder may write only in ``work``, after the user approved this task's current
    plan and after the red test run (or the user's TDD skip)."""
    missing = []
    if task.workflow == "manual":
        missing.append("manual tasks have no agent rounds: change the workflow to run agents")
    if task.blocked:
        missing.append(f"blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')}")
    if task.phase != "work":
        missing.append(f"builders write only in phase 'work' (now '{task.phase}')")
    if not plan_approved(task):
        missing.append(
            "the user has not approved the current plan (approve --action plan --target <ID>)"
        )
    if not task.tdd.get("red") and not task.tdd.get("skip"):
        missing.append("no red test run yet (taskflow tdd <ID> red --cmd ...)")
    return missing


def judge_unmet(task: Task, stamp_key: str) -> list[str]:
    """What must hold before judging: committed code and current TDD evidence."""
    return [*tdd.unmet(task, stamp_key), *_stamp_unmet(task)]


def policy_unmet(task: Task, stamp_key: str) -> list[str]:
    """Controls removed since the policy was accepted need the user's reinforced approval."""
    reduced = task.code_stamp.get("policy_reduced", [])
    if reduced and not valid_approval(task.approvals, "policy-downgrade", stamp_key, task.id):
        return [
            f"policy reduced ({', '.join(reduced)}): approve --action policy-downgrade --target <ID>"
        ]
    return []


@dataclass(frozen=True)
class GateContext:
    config: FlowConfig
    risk: RiskAssessment
    stamp_key: str


def _requirements(task: Task, target: str, ctx: GateContext) -> list[str]:
    if target == "validate":
        return [] if _engine_rounds(task, "planner") else ["no valid planner round"]
    if target == "work":
        return _work_entry_unmet(task)
    if target == "judge":
        return judge_unmet(task, ctx.stamp_key) + policy_unmet(task, ctx.stamp_key)
    if target in ("staging", "review", "done"):
        return _judged_unmet(task, target, ctx)
    if target == "findings":
        return _findings_unmet(task)
    return []


def _work_entry_unmet(task: Task) -> list[str]:
    planner = _engine_rounds(task, "planner")
    validator = [r for r in _engine_rounds(task, "validator") if r["n"] > _last_n(planner)]
    missing = []
    if not any(r.get("verdict") in ("pass", "concerns") for r in validator):
        missing.append("no validator pass/concerns on the latest plan")
    if not plan_approved(task):
        missing.append(
            "the user has not approved the current plan (approve --action plan --target <ID>)"
        )
    return missing


def _findings_unmet(task: Task) -> list[str]:
    verdicts = [r.get("verdict") for r in _engine_rounds(task, "judge")]
    if task.owner_mode != "external" and not {"block", "concerns"} & set(verdicts):
        return ["findings need owner_mode=external or a judge verdict of block/concerns"]
    return []


def _judged_unmet(task: Task, target: str, ctx: GateContext) -> list[str]:
    key = ctx.stamp_key
    missing = judge_unmet(task, key) + policy_unmet(task, key)
    missing += checks_unmet(task, key) + judges_unmet(task, ctx.risk, ctx.config, key)
    if target == "review" and (task.phase == "staging" or ctx.risk.restaging):
        missing += staging_unmet(task, key)
    if target == "done" and not valid_approval(task.approvals, "prod", key, task.id):
        missing.append(
            "production not confirmed by the user on this code (approve --action prod --target <ID>)"
        )
    return missing


def _stamp_unmet(task: Task) -> list[str]:
    if not task.repos:
        return ["no repository bound (taskflow bind <ID> --repo <path>)"]
    if any(s.get("dirty") for s in task.code_stamp.get("repos", [])):
        return ["uncommitted changes: the judge only judges committed code"]
    return []


def staging_unmet(task: Task, stamp_key: str) -> list[str]:
    """Staging is valid only for the code deployed now: every bound repository's current
    HEAD deployed to staging, with evidence bound to that SHA."""
    missing = []
    deployed = {
        (d.get("repo"), d.get("sha")) for d in task.deployments if d.get("env") == "staging"
    }
    evidenced = {e.get("deployed_sha") for e in task.evidence if e.get("kind") == "staging"}
    for repo, head in _heads(task).items():
        if (repo, head) not in deployed:
            missing.append(f"staging: {repo} @ {head[:12]} not recorded as deployed")
        elif head not in evidenced:
            missing.append(f"staging: no evidence bound to {head[:12]}")
    if not valid_approval(task.approvals, "staging", stamp_key, task.id):
        missing.append("the user has not accepted the staging test on this code")
    return missing


def check_transition(task: Task, target: str, ctx: GateContext) -> list[str]:
    """Unmet requirements to move ``task`` to ``target`` (empty list: allowed)."""
    if task.workflow == "manual":
        return ["manual tasks only track steps and facts: they have no phases to move through"]
    if task.blocked:
        return [
            f"blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')} (taskflow unblock)"
        ]
    if target in EXIT_PHASES:
        return _requirements(task, target, ctx)
    if target not in PHASES:
        raise ValueError(f"Unknown phase '{target}'")
    if task.phase in EXIT_PHASES:
        return [f"the task left the flow through '{task.phase}'"]
    return _forward_unmet(task, target, ctx)


def _forward_unmet(task: Task, target: str, ctx: GateContext) -> list[str]:
    current, wanted = PHASES.index(task.phase), PHASES.index(target)
    if wanted <= current:
        return []
    skipping_staging = task.phase == "judge" and target == "review" and not ctx.risk.restaging
    if wanted != current + 1 and not skipping_staging:
        return [f"move one phase at a time: next is '{PHASES[current + 1]}'"]
    return _requirements(task, target, ctx)


def close_unmet(task: Task, config: FlowConfig, risk: RiskAssessment, stamp_key: str) -> list[str]:
    """``done`` must still hold on the current code when the task is closed. Manual tasks
    cannot move through phases or consume approvals, so closing them is free."""
    if task.workflow == "manual" or task.phase in EXIT_PHASES:
        return []
    if task.phase != "done":
        return [f"phase is '{task.phase}': finish the flow (done/findings) or close --abandon"]
    return _judged_unmet(task, "done", GateContext(config, risk, stamp_key))
