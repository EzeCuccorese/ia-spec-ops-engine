"""``ai-governance taskflow``: track tasks and run the plan -> validate -> work -> judge flow."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from .._config_core import AGENT_ENV_MARKERS
from ..output import emit_json, emit_kv, emit_rows, emit_status, emit_text
from . import round_cli, tdd
from .approvals import (
    RISKY_ACTIONS,
    STAMP_FREE_ACTIONS,
    ApprovalContext,
    ApprovalError,
    ApprovalRequest,
    build_approval,
    request_tag,
    valid_approval,
)
from .config import REPO_CONFIG, FlowConfig, PendingTrust, load_config, record_trust
from .digest import digest
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
from .guide import GUIDE as GUIDE
from .handoff import findings, handoff, scrub, ticket_draft
from .judge import JudgeError, JudgeScope
from .judge_flow import JudgeJob, judge_flow
from .models import PHASES, READER_ROLES, Task, now_iso
from .policy import _rule_reductions as _rule_reductions
from .policy import policy_reductions as policy_reductions
from .policy import policy_summary
from .refresh import legacy_notice, refresh
from .repos import begin_invocation, first_live, on_live
from .resolver import TaskResolver
from .risk import RiskAssessment
from .rounds import LeaseError, RoundRequest, record_manual, run_round
from .stamp import GitError
from .store import FRICTION_FILE, TaskStore


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
                f"Several tasks are bound here ({', '.join(sorted(several))}): pass the task id, "
                "or `taskflow switch <parent> <subtask>` to pick the active one"
            )
        raise FileNotFoundError("No task matches this directory: pass the task id")
    return found


def _refresh(
    store: TaskStore, task: Task, config: FlowConfig, remote: bool = False
) -> tuple[Task, RiskAssessment]:
    """Recompute the code stamp and the risk of the current changes."""
    return refresh(store, task, config, remote)


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
    if not args.abandon:
        config = _config(task)
        task, risk = _refresh(store, task, config)
        missing = close_unmet(task, config, risk, task.stamp_key)
        if missing:
            raise ValueError(
                f"Cannot close '{task.id}': "
                + "; ".join(missing)
                + " (or --abandon --reason '...')"
                + (f". {legacy_notice(task)}" if legacy_notice(task) else "")
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


def _recovery_pairs(task: Task) -> list[tuple[str, str]]:
    """Status rows about repos gone from disk and the legacy-state notice."""
    gone = [
        ("repo gone (stamp frozen)", str(e["repo"]))
        for e in task.code_stamp.get("repos", [])
        if e.get("missing")
    ]
    return [*gone, *([("legacy", legacy_notice(task))] if legacy_notice(task) else [])]


def _status_pairs(task: Task, risk: RiskAssessment, missing: list[str]) -> list[tuple[str, str]]:
    target = _next_phase(task.phase)
    return [
        ("Phase", f"{task.phase}{' (BLOCKED)' if task.blocked else ''} · next: {target or '-'}"),
        ("Code stamp", task.stamp_key or "no repository bound"),
        (
            "Risk",
            f"{risk.level} · judges: {', '.join(risk.judges)}"
            + (" · restaging required" if risk.restaging else ""),
        ),
        ("Missing", "; ".join(missing) or "nothing"),
        *_recovery_pairs(task),
        ("Stale", ", ".join(_stale_rounds(task)) or "none"),
        ("Expired approvals", ", ".join(_expired_approvals(task)) or "none"),
        ("Next", NEXT_COMMAND.get(task.phase, "-")),
    ]


def cmd_status(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(_resolve(store, args.task_id))
    config = _config(task)
    task, risk = _refresh(store, task, config)
    target = _next_phase(task.phase)
    missing = (
        check_transition(task, target, GateContext(config, risk, task.stamp_key)) if target else []
    )
    pairs = _status_pairs(task, risk, missing)
    waiting = _warn_pending_trust(config) if not args.json else []
    if args.json or waiting:
        pairs.insert(-1, ("Pending trust", "; ".join(waiting) or "none"))
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
        live = first_live(task.repos)
        cwd = live[0] if live else Path.cwd()
        exit_code, output = on_live([cwd], lambda: tdd.run_test(args.cmd, cwd))
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
    if args.action in ("dispatch", "collect", "abort"):
        return round_cli.route(args)
    store = _store()
    task = store.get(args.task_id)
    config = _config(task)
    task, _risk = _refresh(store, task, config)
    if args.action == "record":
        return _record_manual_round(store, task, args)
    _check_round_allowed(task, args.role)
    agent = {"agent": args.agent, "model": args.model} if args.agent else config.role(args.role)
    if refusal := config.agent_error(str(agent.get("agent", ""))):
        raise ValueError(f"{args.role}: {refusal}")
    live = first_live(task.repos)
    repo, others = live if live else (Path.cwd(), ())
    watch = others if args.role in READER_ROLES else ()
    request = RoundRequest(
        task.id,
        args.phase or task.phase,
        args.role,
        _prompt(args),
        repo,
        agent,
        timeout=args.timeout or config.timeout_seconds,
        watch=watch,
    )
    record = on_live([repo, *others], lambda: run_round(store, request, task.stamp_key))
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
        raise ValueError("Judges run through `taskflow judge`")
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
    _warn_pending_trust(config)
    if task.workflow == "manual":
        raise ValueError("Manual tasks have no judges")
    missing = judge_unmet(task, task.stamp_key) + policy_unmet(task, task.stamp_key)
    if missing:
        raise ValueError("Not ready to judge: " + "; ".join(missing))
    job = JudgeJob(store, task, GateContext(config, risk, task.stamp_key), JudgeScope(args.focus))
    waiting: set[str] = set()
    for plan in judge_flow(job, lambda: _refresh(store, store.get(task.id), config)[0].stamp_key):
        print(shlex.join(plan.argv))
        waiting.add(plan.focus)
        print(
            f"Round {plan.n:03d} reserved (judge '{plan.focus}'). Run the line above, end your turn, "
            f"then: taskflow round {task.id} collect --round {plan.n} --dispatch-id <ID from Orca>",
            file=sys.stderr,
        )
    task = store.get(task.id)
    pending = checks_unmet(task, task.stamp_key) + judges_unmet(task, risk, config, task.stamp_key)
    pending = [p for p in pending if not any(p.startswith(f"judge '{f}':") for f in waiting)]
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


def _warn_pending_trust(config: FlowConfig) -> list[str]:
    notes = [
        f"repo config pending trust: {p.repo} is ignored entirely (no adds, replaces or "
        f"disables) until approved. Review and approve with "
        f"`ai-governance taskflow trust --repo {p.repo}`"
        for p in config.pending_trust
    ]
    for note in notes:
        emit_status("warn", note)
    return notes


def _agent_markers() -> list[str]:
    """Agent variables actually present: the AI_GOVERNANCE_AGENT output override is ignored,
    so setting it to 0 cannot turn an agent into a human for an approval."""
    return sorted(
        name
        for name, value in os.environ.items()
        if value and (name in AGENT_ENV_MARKERS or name.startswith(("CODEX_", "CLAUDE_CODE_")))
    )


def _show_pending(repo: Path, pending: PendingTrust) -> None:
    print(f"Control config of {repo / REPO_CONFIG} that you are approving (everything in it):")
    print(json.dumps(pending.config, indent=2, sort_keys=True, ensure_ascii=False))
    if pending.commands:
        print("Commands it would run with your permissions:")
        for command in pending.commands:
            print(f"  $ {command}")


def _user_confirms(repo: Path, assume_yes: bool) -> bool:
    """Approval needs a person at a terminal: --yes only skips the question."""
    if _agent_markers() or not (sys.stdin.isatty() and sys.stdout.isatty()):
        emit_status(
            "error",
            "These commands run with your permissions: approve them yourself in an interactive "
            f"terminal (ai-governance taskflow trust --repo {repo})",
        )
        return False
    if assume_yes:
        return True
    try:
        answer = input("Run these checks for this repository? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print()  # the terminal closed or the user hit Ctrl-C: that is a refusal, not a crash
        answer = ""
    if answer.strip().lower() == "y":
        return True
    emit_status("warn", "Not trusted")
    return False


def cmd_trust(args: argparse.Namespace) -> int:
    """Shows the check commands a repository defines and, after the user confirms, remembers
    that exact set (a changed set is pending again)."""
    repo = Path(args.repo).expanduser().resolve()
    pending = [p for p in load_config([repo]).pending_trust if Path(p.repo).resolve() == repo]
    if not pending:
        emit_status("ok", f"No repo config pending trust in {repo}")
        return 0
    _show_pending(repo, pending[0])
    if not _user_confirms(repo, args.yes):
        return 1
    digest_ = record_trust(repo, pending[0].config or {})
    emit_status("ok", f"Trusted {len(pending[0].commands)} command(s) for {repo} ({digest_})")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config = load_config([TaskResolver._git_root(Path.cwd()) or Path.cwd()])
    _warn_pending_trust(config)
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
            ("allowed agents", ", ".join(sorted(config.allowed.agents)) or "none"),
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


def _parser() -> argparse.ArgumentParser:
    from .parser import build_parser

    return build_parser()


def main(argv: list[str] | None = None) -> int:
    begin_invocation()
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
        subprocess.TimeoutExpired,
    ) as exc:
        emit_status("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
