"""``ai-governance taskflow``: track tasks and run the plan -> validate -> work -> judge flow."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from ..output import emit_json, emit_kv, emit_rows, emit_status, emit_text
from . import tdd
from .approvals import (
    ACTIONS,
    RISKY_ACTIONS,
    STAMP_FREE_ACTIONS,
    ApprovalContext,
    ApprovalError,
    ApprovalRequest,
    build_approval,
    request_tag,
    valid_approval,
)
from .config import FlowConfig, load_config
from .gates import (
    NEXT_COMMAND,
    GateContext,
    check_transition,
    checks_unmet,
    close_unmet,
    judge_unmet,
    judges_unmet,
    plan_round,
    policy_unmet,
    work_unmet,
)
from .handoff import findings, handoff, scrub, ticket_draft
from .judge import JudgeError, judge_task
from .models import EXIT_PHASES, PHASES, ROLES, VERDICTS, WORKFLOWS, JsonDict, Task, now_iso
from .resolver import TaskResolver
from .risk import RiskAssessment, assess
from .rounds import LeaseError, RoundRequest, record_manual, run_round
from .stamp import GitError, changed_paths, code_stamp, merge_base
from .store import FRICTION_FILE, TaskStore

GUIDE = """\
Flow (one task or subtask at a time):
  plan -> validate -> work -> judge -> [staging] -> review -> done   (exit: findings)

  1. Start:     taskflow new <ID> --title "..."   (ID = Jira key, or a slug until it exists)
                taskflow bind <ID> --repo <worktree> --integration-branch <branch>
  2. plan:      taskflow round <ID> run --role planner --prompt-file brief.md
                taskflow phase <ID> validate
  3. validate:  taskflow round <ID> run --role validator --prompt-file review.md
                show the user the final plan; on their ok in the chat:
                taskflow approve <ID> --action plan --target <ID> --user-reply "<their words>"
                taskflow phase <ID> work
  4. work:      taskflow tdd <ID> red --cmd "<test>"   (before the change; must fail)
                implement, then taskflow tdd <ID> green --cmd "<same test>"; commit
                taskflow phase <ID> judge
  5. judge:     taskflow judge <ID>   (isolated copy of HEAD, checks + every required judge)
                block/concerns -> taskflow phase <ID> work, fix, judge again
  6. staging:   optional unless a risk rule asks for it. The USER deploys and approves.
                taskflow deploy <ID> --env staging --repo <path> --sha <sha> --provenance ci
                taskflow evidence <ID> --kind staging --file results.md --deployed-sha <sha>
  7. review:    clean up/rebase, taskflow judge <ID> again on the final SHA
  8. done:      only after the user confirms production (approve --action prod)

Human gates (the engine never runs them itself): ticket, push, pr, comment, slack,
staging, deploy, prod. Run `taskflow ask <ID> --action A --target T`, put the tag it
prints in your question to the user, wait for the reply, then record it with
`taskflow approve`. Risky actions (deploy, prod, migration, infra, permissions, delete,
policy-downgrade, restaging) need --consequence (what breaks if it goes wrong, plainly)
and a reply that names the action and the target, typed by the user; "ok"/"dale" is
refused. Production actions are refused after 16:00, and on Friday after 13:00.

One worktree per task: tasks sharing a worktree make `here` ambiguous and reviewers mix
contexts. `round run` already prepends the task context (goal, plan path, decisions, facts,
repos), so a prompt only needs the specific question.

Code tasks always run tri-agent (planner, validator and builder are different agents).
Another workflow only when the user asks for it; record it before leaving plan:
  taskflow approve <ID> --action workflow --target <ID> --user-reply "<their words>"
manual is for tracking only (no code, no phases).

TDD is mandatory unless the user asks to skip it:
  taskflow approve <ID> --action tdd-skip --target <ID> --user-reply "<their words>"
  taskflow tdd <ID> skip --reason "..."

In a Claude Code session --user-reply must be one whole message the user typed in this
session (each message approves once); risky actions are approved only there.

Any code change after a verdict or approval makes it stale: `taskflow status <ID>` shows
what is stale, what is missing for the next phase and the exact next command.
Another owner's branch: taskflow findings <ID> --out findings.md, hand it over, close.
Nothing of this tool or of the agents goes into tickets, commits, PRs or Slack.
"""


def _store() -> TaskStore:
    return TaskStore()


def _config(task: Task) -> FlowConfig:
    return load_config([Path(r["path"]) for r in task.repos])


def _resolve(store: TaskStore, task_id: str | None) -> str:
    if task_id:
        return task_id
    found = TaskResolver.resolve_from_context(store.list(), Path.cwd())
    if not found:
        several = TaskResolver.bound_to(store.list(), Path.cwd())
        if len(several) > 1:
            raise FileNotFoundError(
                f"Several tasks are bound here ({', '.join(several)}): pass the task id, "
                "or `taskflow switch <parent> <subtask>` to pick the active one"
            )
        raise FileNotFoundError("No task matches this directory: pass the task id")
    return found


def _refresh(
    store: TaskStore, task: Task, config: FlowConfig, remote: bool = False
) -> tuple[Task, RiskAssessment]:
    """Recompute the code stamp and the risk of the current changes."""
    if task.repos:
        stamp = code_stamp(task.repos, config.policy_digest, check_remote=remote)
        current = policy_summary(config)
        stamp["policy_reduced"] = policy_reductions(task.policy or current, current)

        def save(t: Task) -> None:
            t.code_stamp = stamp
            t.policy = t.policy or current

        task = store.mutate(task.id, save)
    paths: list[str] = []
    for repo in task.repos:
        paths += changed_paths(Path(repo["path"]), _base_ref(repo))
    return task, assess(config, paths)


def policy_summary(config: FlowConfig) -> JsonDict:
    """The controls a task accepted, rule by rule; weakening any of them later is a
    reduction that needs the user's D3 ``policy-downgrade`` approval."""
    return {
        "judges": sorted(str(j.get("focus")) for j in config.judges),
        "checks": sorted(config.checks),
        "rules": {
            r.name: {
                "paths": sorted(r.paths),
                "judges": sorted(r.judges),
                "checks": sorted(r.checks),
                "restaging": r.restaging,
            }
            for r in config.risk_rules
        },
    }


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


def _base_ref(repo: dict[str, str]) -> str:
    branch = repo.get("integration_branch", "")
    return merge_base(Path(repo["path"]), branch) if branch else ""


# -- tracking ------------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    tasks = _store().list(include_closed=args.all)
    if args.json:
        emit_json([t.to_dict() for t in tasks])
        return 0
    emit_rows(
        [(t.id, t.phase, t.status, t.title) for t in tasks],
        headers=("Task", "Phase", "Status", "Title"),
        title="Tasks",
        more_hint="taskflow list --json",
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(_resolve(store, args.task_id))
    if args.json:
        data = task.to_dict()
        if args.full:
            data["log"] = store.read_log(task.id)
        emit_json(data)
        return 0
    emit_kv(_show_pairs(task), title=f"Task: {task.id} — {task.title}", full=args.full)
    if args.full:
        emit_text(store.read_log(task.id), full=True)
    return 0


def _show_pairs(task: Task) -> list[tuple[str, str]]:
    pairs = [
        ("Status", f"{task.status} · phase {task.phase} · workflow {task.workflow}"),
        ("Summary", task.summary or "-"),
    ]
    if task.parent:
        pairs.append(("Parent", task.parent))
    if task.subtasks:
        pairs.append(
            ("Subtasks", ", ".join(task.subtasks) + f" (active: {task.active_subtask or '-'})")
        )
    if task.blocked:
        pairs.append(("Blocked", f"{task.blocked.get('owner')}: {task.blocked.get('needs')}"))
    steps = "; ".join(f"{'✓' if s.get('done') else '□'} {s['text']}" for s in task.steps)
    pairs.append(("Steps", steps or "-"))
    pairs += _show_context_pairs(task)
    pairs.append(("Rounds", f"{len(task.rounds)} (taskflow rounds {task.id})"))
    return pairs


def _show_context_pairs(task: Task) -> list[tuple[str, str]]:
    pairs = []
    if task.facts:
        pairs.append(("Facts", "; ".join(f["text"] for f in task.facts)))
    if task.repos:
        pairs.append(
            ("Repos", "; ".join(f"{r['path']} ({r.get('branch', '?')})" for r in task.repos))
        )
    if task.links or task.references:
        refs = [f"{link['title']}: {link['url']}" for link in task.links] + [
            f"{r['kind']}: {r['value']}" for r in task.references
        ]
        pairs.append(("Links", "; ".join(refs)))
    return pairs


def cmd_new(args: argparse.Namespace) -> int:
    store = _store()
    task = Task(
        id=args.task_id,
        title=args.title,
        summary=args.summary,
        workflow=args.workflow,
        owner_mode=args.owner,
        parent=args.parent or "",
    )
    if args.parent:
        store.get(args.parent)
    store.create(task)
    if args.parent:

        def link(parent: Task) -> None:
            parent.subtasks.append(task.id)
            parent.active_subtask = task.id

        store.mutate(args.parent, link)
    emit_status(
        "ok", f"Created task '{task.id}' (phase plan). Next: taskflow bind {task.id} --repo <path>"
    )
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    store = _store()
    parent = store.get(args.task_id)
    if args.subtask not in parent.subtasks:
        raise ValueError(f"'{args.subtask}' is not a subtask of '{parent.id}'")
    store.mutate(parent.id, lambda t: setattr(t, "active_subtask", args.subtask))
    emit_status("ok", f"Active subtask of {parent.id}: {args.subtask}")
    return 0


def _list_append(
    field: str, build: Callable[[argparse.Namespace], dict[str, object]]
) -> Callable[[argparse.Namespace], int]:
    def command(args: argparse.Namespace) -> int:
        store = _store()
        task_id = _resolve(store, args.task_id)
        value = build(args)
        store.mutate(task_id, lambda t: getattr(t, field).append(value))
        emit_status("ok", f"Recorded {field[:-1]} in '{task_id}'")
        return 0

    return command


def cmd_summary(args: argparse.Namespace) -> int:
    store = _store()
    store.mutate(args.task_id, lambda t: setattr(t, "summary", args.text))
    emit_status("ok", f"Updated summary of '{args.task_id}'")
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    store = _store()

    def change(task: Task) -> None:
        if args.action == "add":
            task.steps.append({"text": args.value, "done": False})
            return
        index = _find_step(task, args.value)
        if args.action == "done":
            task.steps[index]["done"] = True
        else:
            task.steps.pop(index)

    store.mutate(args.task_id, change)
    emit_status("ok", f"Step {args.action}: {args.value}")
    return 0


def _find_step(task: Task, selector: str) -> int:
    if selector.isdigit() and 0 < int(selector) <= len(task.steps):
        return int(selector) - 1
    for index, step in enumerate(task.steps):
        if step["text"] == selector:
            return index
    raise ValueError(f"Step not found: {selector}")


def cmd_note(args: argparse.Namespace) -> int:
    store = _store()
    store.get(args.task_id)
    store.append_log(args.task_id, args.text)
    emit_status("ok", f"Appended note to '{args.task_id}'")
    return 0


def cmd_friction(args: argparse.Namespace) -> int:
    store = _store()
    path = store.task_dir(args.task_id) / FRICTION_FILE
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"- {now_iso()[:10]}: {args.text}\n")
    emit_status("ok", f"Friction recorded in {path}")
    return 0


def _set_status(status: str) -> Callable[[argparse.Namespace], int]:
    def command(args: argparse.Namespace) -> int:
        store = _store()
        reason = f": {args.reason}" if getattr(args, "reason", "") else ""
        store.mutate(
            args.task_id, lambda t: setattr(t, "status", status), log=f"Status {status}{reason}"
        )
        emit_status("ok", f"'{args.task_id}' is {status}")
        return 0

    return command


def cmd_close(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    if task.repos and not args.abandon:
        config = _config(task)
        task, risk = _refresh(store, task, config)
        missing = close_unmet(task, config, risk, task.stamp_key)
        if missing:
            raise ValueError(
                f"Cannot close '{task.id}': "
                + "; ".join(missing)
                + " (or --abandon --reason '...')"
            )
    return _set_status("closed")(args)


def _repo_path(raw: str) -> str:
    """A subdirectory binds its repository's top level, which is what the resolver compares."""
    path = Path(raw).expanduser().resolve()
    return str(TaskResolver._git_root(path) or path)


def cmd_bind(args: argparse.Namespace) -> int:
    store = _store()
    path = _repo_path(args.repo)
    branch = args.branch or TaskResolver._git_branch(Path(path)) or ""

    def change(task: Task) -> None:
        entry = next((r for r in task.repos if r["path"] == path), None)
        if entry is None:
            entry = {"path": path}
            task.repos.append(entry)
        entry.update(
            {
                k: v
                for k, v in (
                    ("branch", branch),
                    ("integration_branch", args.integration_branch),
                    ("pr", args.pr),
                )
                if v
            }
        )

    store.mutate(args.task_id, change, log=f"Bound {path} ({branch})")
    emit_status("ok", f"Bound {path} to '{args.task_id}' (branch {branch or '?'})")
    return 0


def cmd_unbind(args: argparse.Namespace) -> int:
    store = _store()
    path = _repo_path(args.repo)
    store.mutate(
        args.task_id, lambda t: setattr(t, "repos", [r for r in t.repos if r["path"] != path])
    )
    emit_status("ok", f"Unbound {path}")
    return 0


# -- flow ----------------------------------------------------------------------------------
def cmd_stamp(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    task, risk = _refresh(store, task, _config(task), remote=args.remote)
    emit_json({"stamp": task.code_stamp, "risk": risk.level, "judges": list(risk.judges)})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(_resolve(store, args.task_id))
    config = _config(task)
    task, risk = _refresh(store, task, config)
    target = _next_phase(task.phase)
    missing = (
        check_transition(task, target, GateContext(config, risk, task.stamp_key)) if target else []
    )
    pairs = [
        ("Phase", f"{task.phase}{' (BLOCKED)' if task.blocked else ''} · next: {target or '-'}"),
        ("Code stamp", task.stamp_key or "no repository bound"),
        (
            "Risk",
            f"{risk.level} · judges: {', '.join(risk.judges)}"
            + (" · restaging required" if risk.restaging else ""),
        ),
        ("Missing", "; ".join(missing) or "nothing"),
        ("Stale", ", ".join(_stale_rounds(task)) or "none"),
        ("Expired approvals", ", ".join(_expired_approvals(task)) or "none"),
        ("Next", NEXT_COMMAND.get(task.phase, "-")),
    ]
    if args.json:
        emit_json(dict(pairs))
    else:
        emit_kv(pairs, title=f"{task.id} — {task.title}", full=True)
    return 0


def _stale_rounds(task: Task) -> list[str]:
    return [
        f"{r['role']}{'/' + r['focus'] if r.get('focus') else ''} #{int(r['n']):03d}"
        for r in task.rounds
        if r.get("source") == "engine" and r.get("stamp") != task.stamp_key
    ]


def _expired_approvals(task: Task) -> list[str]:
    """Approvals bound to the code expire when it changes; workflow, plan and tdd-skip are
    checked without a stamp by the gates, so they are never listed."""
    return list(
        dict.fromkeys(
            a["action"]
            for a in task.approvals
            if a["action"] not in STAMP_FREE_ACTIONS and a.get("stamp") != task.stamp_key
        )
    )


def _next_phase(phase: str) -> str:
    if phase not in PHASES or phase == "done":
        return ""
    return PHASES[PHASES.index(phase) + 1]


def cmd_phase(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    config = _config(task)
    task, risk = _refresh(store, task, config)
    missing = check_transition(task, args.target, GateContext(config, risk, task.stamp_key))
    if missing:
        raise ValueError(f"Cannot move '{task.id}' to {args.target}: " + "; ".join(missing))
    store.mutate(
        task.id,
        lambda t: setattr(t, "phase", args.target),
        log=f"Phase {task.phase} -> {args.target}",
    )
    emit_status(
        "ok", f"'{task.id}' is in phase {args.target}. Next: {NEXT_COMMAND.get(args.target, '-')}"
    )
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    store = _store()
    blocked = {"owner": args.owner, "needs": args.needs, "since": now_iso()}
    store.mutate(
        args.task_id,
        lambda t: setattr(t, "blocked", blocked),
        log=f"Blocked by {args.owner}: {args.needs}",
    )
    emit_status("ok", f"'{args.task_id}' blocked by {args.owner}")
    return 0


def cmd_unblock(args: argparse.Namespace) -> int:
    store = _store()
    store.mutate(args.task_id, lambda t: setattr(t, "blocked", {}), log="Unblocked")
    emit_status("ok", f"'{args.task_id}' unblocked")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    task, _risk = _refresh(store, task, _config(task))
    if task.workflow == "manual":
        raise ValueError("Manual tasks have no gates to approve")
    request = replace(
        _approval_request(task, args.action, args.target),
        user_reply=args.user_reply,
        consequence=args.consequence,
    )
    record = build_approval(
        request, ApprovalContext(task.stamp_key, datetime.now(), task.approvals)
    )
    if args.action == "plan":
        record["plan_round"] = plan_round(task)
    config = _config(task)

    def save(t: Task) -> None:
        t.approvals.append(record)
        if args.action == "policy-downgrade":
            t.policy = policy_summary(config)  # the reduced policy becomes the accepted one

    store.mutate(task.id, save, log=f"Approved {args.action} on {args.target}")
    emit_status(
        "ok",
        f"Approval '{args.action}' recorded ({record['verified']}); it expires if the code changes",
    )
    return 0


def _approval_request(task: Task, action: str, target: str) -> ApprovalRequest:
    reference = f"plan-r{plan_round(task)}" if action == "plan" else (task.stamp_key or "no-code")
    return ApprovalRequest(action, target, "", task_id=task.id, reference=reference)


def cmd_ask(args: argparse.Namespace) -> int:
    """Print the question to send the user; its tag binds the reply to this request."""
    store = _store()
    task = store.get(args.task_id)
    task, _risk = _refresh(store, task, _config(task))
    tag = request_tag(_approval_request(task, args.action, args.target))
    lines = [f"Include this tag in the question you send the user: {tag}"]
    if args.action in RISKY_ACTIONS:
        lines.append("Risky action: in the same message, say plainly what breaks if it goes wrong.")
    lines.append(
        f"Then: taskflow approve {task.id} --action {args.action} --target {args.target} "
        '--user-reply "<their whole reply>"'
        + (' --consequence "<what you showed>"' if args.action in RISKY_ACTIONS else "")
    )
    emit_text("\n".join(lines), full=True)
    return 0


def cmd_tdd(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    task, _risk = _refresh(store, task, _config(task))
    if args.stage == "skip":
        approval = valid_approval(task.approvals, "tdd-skip", "", task.id)
        if approval is None:
            raise ValueError(
                f"Skipping TDD needs the user's approval: approve {task.id} --action tdd-skip --target {task.id}"
            )
        if not args.reason.strip():
            raise ValueError("--reason is required: why the user decided to skip TDD")
        record: dict[str, object] = {
            "reason": args.reason,
            "approved_by": approval.get("actor"),
            "user_reply": approval.get("user_reply"),
            "at": now_iso(),
        }
    else:
        if not args.cmd:
            raise ValueError("--cmd is required")
        cwd = Path(task.repos[0]["path"]) if task.repos else Path.cwd()
        exit_code, output = tdd.run_test(args.cmd, cwd)
        if args.stage == "red":
            record = tdd.red_record(args.cmd, exit_code, output, task.stamp_key)
        else:
            record = tdd.green_record(task, args.cmd, exit_code, output)
    store.mutate(task.id, lambda t: t.tdd.__setitem__(args.stage, record))
    emit_status("ok", f"TDD {args.stage} recorded for '{task.id}'")
    return 0


def _prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return str(args.prompt)
    raise ValueError("Pass --prompt-file or --prompt")


def cmd_round(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    config = _config(task)
    task, _risk = _refresh(store, task, config)
    if args.action == "record":
        return _record_manual_round(store, task, args)
    _check_round_allowed(task, args.role)
    agent = {"agent": args.agent, "model": args.model} if args.agent else config.role(args.role)
    repo = Path(task.repos[0]["path"]) if task.repos else Path.cwd()
    request = RoundRequest(
        task.id,
        args.phase or task.phase,
        args.role,
        _prompt(args),
        repo,
        agent,
        timeout=args.timeout or config.timeout_seconds,
    )
    record = run_round(store, request, task.stamp_key)
    _report_round(record)
    return 0 if record["state"] == "valid" else 1


def _record_manual_round(store: TaskStore, task: Task, args: argparse.Namespace) -> int:
    info = {
        "phase": args.phase or task.phase,
        "role": args.role,
        "agent": args.agent,
        "model": args.model,
        "verdict": args.verdict,
        "stamp": task.stamp_key,
    }
    body = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    record = record_manual(store, task.id, info, scrub(body))
    emit_status("ok", f"Round {record['n']:03d} recorded as context (it never opens a gate)")
    return 0


def _check_round_allowed(task: Task, role: str) -> None:
    if role == "judge":
        raise ValueError("Judges run through `taskflow judge`, on an isolated copy")
    if task.workflow == "manual":
        raise ValueError("Manual tasks have no agent rounds")
    if role == "builder" and (missing := work_unmet(task)):
        raise ValueError("A builder cannot write yet: " + "; ".join(missing))
    if task.blocked:
        raise ValueError(
            f"'{task.id}' is blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')}"
        )


def _report_round(record: dict[str, object]) -> None:
    level: Literal["ok", "warn"] = "ok" if record["state"] == "valid" else "warn"
    reason = f" — {record['reason']}" if record.get("reason") else ""
    emit_status(
        level,
        f"Round {int(str(record['n'])):03d} {record['role']}: {record['verdict']} "
        f"({record['state']}{reason}). Read it: {record['file']}",
    )


def cmd_rounds(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    if args.show:
        record = next((r for r in task.rounds if int(r["n"]) == args.show), None)
        if record is None:
            raise ValueError(f"No round {args.show}")
        emit_text(Path(record["file"]).read_text(encoding="utf-8"), full=True)
        return 0
    emit_rows(
        [
            (
                f"{int(r['n']):03d}",
                r.get("phase", ""),
                r.get("role", "") + (f"/{r['focus']}" if r.get("focus") else ""),
                r.get("agent", ""),
                r.get("verdict", ""),
                r.get("state", ""),
                str(r.get("stamp", ""))[:12],
            )
            for r in task.rounds
        ],
        headers=("n", "phase", "role", "agent", "verdict", "state", "stamp"),
        title=f"Rounds of {task.id}",
        full=True,
    )
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    config = _config(task)
    errors = config.validate()
    if errors:
        raise ValueError("Invalid taskflow config: " + "; ".join(errors))
    task, risk = _refresh(store, task, config)
    if task.workflow == "manual":
        raise ValueError("Manual tasks have no judges")
    missing = judge_unmet(task, task.stamp_key) + policy_unmet(task, task.stamp_key)
    if missing:
        raise ValueError("Not ready to judge: " + "; ".join(missing))
    records, kept = judge_task(
        store, task, GateContext(config, risk, task.stamp_key), focus=args.focus
    )
    for record in records:
        _report_round(record)
    for path in kept:
        emit_status("warn", f"A judge modified its copy; kept for review: {path}")
    task = store.get(task.id)
    pending = checks_unmet(task, task.stamp_key) + judges_unmet(task, risk, config, task.stamp_key)
    for item in pending:
        emit_status("warn", item)
    return 0 if not pending else 1


def cmd_deploy(args: argparse.Namespace) -> int:
    store = _store()
    record = {
        "env": args.env,
        "repo": str(Path(args.repo).expanduser().resolve()),
        "sha": args.sha,
        "provenance": args.provenance,
        "at": now_iso(),
    }
    store.mutate(
        args.task_id,
        lambda t: t.deployments.append(record),
        log=f"Deployed {args.sha[:12]} to {args.env}",
    )
    emit_status("ok", f"Deployment recorded: {args.env} @ {args.sha[:12]} ({args.provenance})")
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    source = Path(args.file)
    target = (
        store.evidence_dir(task.id)
        / f"{args.kind}@{(args.deployed_sha or task.stamp_key)[:8]}-{source.name}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(scrub(source.read_text(encoding="utf-8")), encoding="utf-8")
    record = {
        "kind": args.kind,
        "path": str(target),
        "stamp": task.stamp_key,
        "deployed_sha": args.deployed_sha,
        "at": now_iso(),
    }
    store.mutate(task.id, lambda t: t.evidence.append(record))
    emit_status("ok", f"Evidence stored: {target}")
    return 0


def _write_or_print(text: str, out: str | None) -> int:
    if out:
        Path(out).write_text(text, encoding="utf-8")
        emit_status("ok", f"Written to {out}")
    else:
        emit_text(text, full=True)
    return 0


def cmd_findings(args: argparse.Namespace) -> int:
    store = _store()
    return _write_or_print(findings(store.get(args.task_id)), args.out)


def cmd_handoff(args: argparse.Namespace) -> int:
    store = _store()
    return _write_or_print(handoff(store.get(args.task_id), args.to), args.out)


def cmd_draft(args: argparse.Namespace) -> int:
    store = _store()
    return _write_or_print(ticket_draft(store.get(args.task_id)), args.out)


def cmd_digest(args: argparse.Namespace) -> int:
    emit_text(digest(_store(), args.task_id, args.max_chars), full=True)
    return 0


def _pick_focus(tasks: list[Task], focus_id: str | None) -> Task | None:
    return next((t for t in tasks if t.id == focus_id), None) or next(iter(tasks), None)


def _focus_lines(focus: Task) -> list[str]:
    lines = [
        f"- {focus.id} [{focus.phase}{', blocked' if focus.blocked else ''}]: {focus.summary or focus.title}"
    ]
    pending = [s["text"] for s in focus.steps if not s.get("done")][:5]
    if pending:
        lines.append("  next: " + "; ".join(pending))
    return lines


def digest(store: TaskStore, focus_id: str | None = None, max_chars: int = 1600) -> str:
    tasks = store.list()
    focus = _pick_focus(tasks, focus_id)
    lines = [f"TASKFLOW ({len(tasks)} open) — `ai-governance taskflow --help` explains the flow"]
    if focus:
        lines += _focus_lines(focus)
    others = [t.id for t in tasks if focus is None or t.id != focus.id]
    if others:
        lines.append("  others: " + ", ".join(others[:8]))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def cmd_config(args: argparse.Namespace) -> int:
    config = load_config([Path.cwd()])
    errors = config.validate()
    emit_kv(
        [
            ("workflow", config.workflow),
            *(
                (f"role {name}", f"{r.get('agent')} {r.get('model', '')}")
                for name, r in config.roles.items()
            ),
            *(
                (f"judge {j.get('focus')}", f"{j.get('agent')} {j.get('model', '')}")
                for j in config.judges
            ),
            ("checks", "; ".join(config.checks)),
            ("tdd", "mandatory (skip only with the user tdd-skip approval)"),
            ("risk rules", ", ".join(r.name for r in config.risk_rules) or "none"),
            ("errors", "; ".join(errors) or "none"),
        ],
        title="taskflow config",
        full=True,
    )
    return 1 if errors else 0


# -- parser --------------------------------------------------------------------------------
Subparsers: TypeAlias = "argparse._SubParsersAction[argparse.ArgumentParser]"


def _adder(sub: Subparsers) -> Callable[..., argparse.ArgumentParser]:
    def add(
        name: str, handler: Callable[[argparse.Namespace], int], text: str, task: str = "required"
    ) -> argparse.ArgumentParser:
        item = sub.add_parser(name, help=text, description=text)
        item.set_defaults(handler=handler)
        if task == "required":
            item.add_argument("task_id")
        elif task == "optional":
            item.add_argument("task_id", nargs="?")
        return item

    return add


def _task_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("list", cmd_list, "List open tasks", task="none")
    item.add_argument("--all", action="store_true", help="Include closed tasks")
    item.add_argument("--json", action="store_true")
    for name, text in (
        ("show", "Show a task (default: the one bound to this directory)"),
        ("here", "Task bound to this branch/repository"),
    ):
        item = add(name, cmd_show, text, task="optional" if name == "show" else "none")
        item.add_argument("--full", action="store_true", help="Include the long log")
        item.add_argument("--json", action="store_true")
        if name == "here":
            item.set_defaults(task_id=None)
    item = add("new", cmd_new, "Create a task (ID = Jira key or slug)")
    item.add_argument("--title", required=True)
    item.add_argument("--summary", default="")
    item.add_argument("--parent", help="Make it a subtask of this task")
    item.add_argument("--workflow", choices=WORKFLOWS, default="tri-agent")
    item.add_argument(
        "--owner",
        choices=("self", "external"),
        default="self",
        help="external: findings go to another owner",
    )


def _content_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("switch", cmd_switch, "Set the active subtask of a task")
    item.add_argument("subtask")
    item = add("summary", cmd_summary, "Replace the summary")
    item.add_argument("text")
    item = add("step", cmd_step, "Add, complete or remove a step")
    item.add_argument("action", choices=("add", "done", "remove"))
    item.add_argument("value", help="Step text, or its 1-based number for done/remove")
    item = add(
        "fact",
        _list_append("facts", lambda a: {"text": a.text, "at": now_iso()}),
        "Record a verified fact",
    )
    item.add_argument("text")
    item = add(
        "decide",
        _list_append("decisions", lambda a: {"text": a.text, "why": a.why, "at": now_iso()}),
        "Record a decision",
    )
    item.add_argument("text")
    item.add_argument("--why", default="")


def _reference_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "link",
        _list_append("links", lambda a: {"title": a.title, "url": a.url}),
        "Add a titled URL",
    )
    item.add_argument("title")
    item.add_argument("url")
    item = add(
        "reference",
        _list_append("references", lambda a: {"kind": a.kind, "value": a.value, "url": a.url}),
        "Add an external reference (jira, pr, slack...)",
    )
    item.add_argument("kind")
    item.add_argument("value")
    item.add_argument("--url", default="")
    item = add("note", cmd_note, "Append to the long log")
    item.add_argument("text")
    item = add("friction", cmd_friction, "Record a friction of the flow itself")
    item.add_argument("text")


def _lifecycle_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    for name, status in (("pause", "paused"), ("reopen", "active"), ("resume", "active")):
        item = add(name, _set_status(status), f"Mark the task {status}")
        item.add_argument("--reason", default="")
    item = add("close", cmd_close, "Close a task (after done/findings, or --abandon)")
    item.add_argument("--reason", default="")
    item.add_argument(
        "--abandon", action="store_true", help="Close a task that left the flow unfinished"
    )
    item = add("bind", cmd_bind, "Bind a repository/worktree to the task")
    item.add_argument("--repo", default=".")
    item.add_argument("--branch", default="")
    item.add_argument(
        "--integration-branch",
        default="",
        help="Branch that is deployed/merged into (e.g. develop)",
    )
    item.add_argument("--pr", default="")
    item = add("unbind", cmd_unbind, "Remove a bound repository")
    item.add_argument("--repo", default=".")
    item = add("stamp", cmd_stamp, "Recompute the code stamp and the risk")
    item.add_argument(
        "--remote", action="store_true", help="Verify the integration branch with git ls-remote"
    )
    item = add(
        "status",
        cmd_status,
        "Phase, missing requirements, stale verdicts and next command",
        task="optional",
    )
    item.add_argument("--json", action="store_true")
    item = add("phase", cmd_phase, "Move the task to a phase (checked against the gates)")
    item.add_argument("target", choices=(*PHASES, *EXIT_PHASES))
    item = add("block", cmd_block, "Mark the task blocked waiting for someone")
    item.add_argument("--owner", required=True)
    item.add_argument("--needs", required=True)
    add("unblock", cmd_unblock, "Clear the block")


def _approval_round_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("ask", cmd_ask, "Print the tag your approval question must carry")
    item.add_argument("--action", required=True, choices=ACTIONS)
    item.add_argument("--target", required=True)
    item = add("approve", cmd_approve, "Record the user's approval given in the chat")
    item.add_argument("--action", required=True, choices=ACTIONS)
    item.add_argument(
        "--target", required=True, help="What it applies to: task, PR, service, environment"
    )
    item.add_argument("--user-reply", required=True, help="The user's words, verbatim")
    item.add_argument(
        "--consequence",
        default="",
        help="Risky actions: what breaks if it goes wrong, as shown to the user",
    )
    item = add("tdd", cmd_tdd, "Record the red/green test runs (or a skip the user approved)")
    item.add_argument("stage", choices=("red", "green", "skip"))
    item.add_argument("--cmd", default="", help="Test command, the same for red and green")
    item.add_argument("--reason", default="")
    item = add(
        "round", cmd_round, "Run a planner/validator/builder round, or record one run elsewhere"
    )
    item.add_argument("action", choices=("run", "record"))
    item.add_argument("--role", required=True, choices=ROLES)
    item.add_argument("--phase", choices=PHASES, help="Default: the task's phase")
    item.add_argument("--prompt-file")
    item.add_argument("--prompt")
    item.add_argument("--agent", default="", help="Override the configured agent")
    item.add_argument("--model", default="")
    item.add_argument("--timeout", type=int, default=0)
    item.add_argument("--verdict", choices=VERDICTS, default="info", help="record only")
    item.add_argument("--file", help="record only: the round's text (default: stdin)")


def _judge_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("rounds", cmd_rounds, "List the rounds, or print one")
    item.add_argument("--show", type=int)
    item = add(
        "judge",
        cmd_judge,
        "Judge the committed code on an isolated copy (checks + every required judge)",
    )
    item.add_argument("--focus", default="", help="Run only this focus (the gate still needs all)")
    item = add("deploy", cmd_deploy, "Record a deployment the user made (never deploys)")
    item.add_argument("--env", required=True)
    item.add_argument("--repo", required=True)
    item.add_argument("--sha", required=True)
    item.add_argument("--provenance", choices=("ci", "health", "k8s", "manual"), required=True)
    item = add("evidence", cmd_evidence, "Store evidence (test results, captures) bound to a SHA")
    item.add_argument("--kind", required=True, choices=("staging", "review", "prod", "other"))
    item.add_argument("--file", required=True)
    item.add_argument("--deployed-sha", default="")
    for name, handler, text in (
        ("findings", cmd_findings, "Findings package for another owner"),
        ("draft", cmd_draft, "Draft comment for the ticket"),
    ):
        item = add(name, handler, text)
        item.add_argument("--out")
    item = add("handoff", cmd_handoff, "Context package for a role, secrets scrubbed")
    item.add_argument("--to", required=True, choices=ROLES)
    item.add_argument("--out")
    item = add("digest", cmd_digest, "Compact context of the open tasks", task="none")
    item.add_argument("--id", dest="task_id")
    item.add_argument("--max-chars", type=int, default=1600)
    add("config", cmd_config, "Show and validate the taskflow config", task="none")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance taskflow",
        description="Track tasks across sessions and run the TriAgentTaskFlow (plan, validate, work, judge).",
        epilog=GUIDE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")
    _task_commands(sub)
    _content_commands(sub)
    _reference_commands(sub)
    _lifecycle_commands(sub)
    _approval_round_commands(sub)
    _judge_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except (
        ValueError,
        OSError,
        GitError,
        LeaseError,
        JudgeError,
        ApprovalError,
        tdd.TddError,
    ) as exc:
        emit_status("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
