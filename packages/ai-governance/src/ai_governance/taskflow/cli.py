"""``ai-governance taskflow``: durable task notebook, human approvals and design debates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..output import emit_json, emit_kv, emit_rows, emit_status, emit_text
from . import orca, round_cli
from .approvals import (
    RISKY_ACTIONS,
    STAMP_FREE_ACTIONS,
    ApprovalContext,
    ApprovalError,
    ApprovalRequest,
    build_approval,
    request_tag,
)
from .config import FlowConfig, load_config
from .debate import debate_status, dropped_focuses, load_debate
from .digest import digest
from .guide import GUIDE as GUIDE
from .handoff import findings, handoff, scrub, ticket_draft
from .models import Task, now_iso
from .refresh import refresh
from .repos import begin_invocation
from .resolver import TaskResolver
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


def _refresh(store: TaskStore, task: Task, config: FlowConfig, remote: bool = False) -> Task:
    """Recompute the code stamp of the current changes."""
    return refresh(store, task, config, remote)


# -- tracking ------------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    tasks = _store().list(include_closed=args.all)
    if args.json:
        emit_json([t.to_dict() for t in tasks])
        return 0
    emit_rows(
        [(t.id, t.status, t.title) for t in tasks],
        headers=("Task", "Status", "Title"),
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
        ("Status", f"{task.status} · workflow {task.workflow}"),
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
    emit_status("ok", f"Created task '{task.id}'. Next: taskflow bind {task.id} --repo <path>")
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


def _unsettled_dispatch_rounds(runs_dir: Path, settled: set[int]) -> set[int]:
    if not runs_dir.is_dir():
        return set()
    pending: set[int] = set()
    for path in sorted(runs_dir.glob("*/dispatch.json")):
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
            number = int(found["n"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if found.get("role") == "debater" and number not in settled:
            pending.add(number)
    return pending


def _unsettled_seat_rounds(store: TaskStore, task_id: str, settled: set[int]) -> set[int]:
    dstate = load_debate(store, task_id)
    if dstate is None:
        return set()
    dropped = dropped_focuses(dstate)
    pending: set[int] = set()
    for seat in dstate.get("seats", []):
        if str(seat.get("focus", "")) in dropped:
            continue
        for key in ("thesis_round", "cross_round"):
            raw = seat.get(key)
            if raw is not None and int(raw) not in settled:
                pending.add(int(raw))
    return pending


def _in_flight_debate_rounds(store: TaskStore, task: Task) -> list[int]:
    settled = {int(r.get("n", 0)) for r in task.rounds}
    pending = _unsettled_dispatch_rounds(store.task_dir(task.id) / "runs", settled)
    pending |= _unsettled_seat_rounds(store, task.id, settled)
    return sorted(pending)


def cmd_close(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    done_outside = bool(getattr(args, "done_outside", False))
    forced = bool(getattr(args, "force", False) or getattr(args, "abandon", False) or done_outside)
    if not forced and (pending := _in_flight_debate_rounds(store, task)):
        joined = ", ".join(f"{n:03d}" for n in pending)
        raise ValueError(
            f"Cannot close '{task.id}': unsettled debate round(s) {joined} "
            "(collect/abort them, or pass --force / --abandon)"
        )
    if done_outside and not getattr(args, "reason", ""):
        args.reason = "done outside flow"
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


# -- status and stamp ----------------------------------------------------------------------
def cmd_stamp(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(args.task_id)
    task = _refresh(store, task, _config(task), args.remote)
    emit_json({"stamp": task.code_stamp})
    return 0


def _recovery_pairs(task: Task) -> list[tuple[str, str]]:
    """Status rows about bound repos gone from disk."""
    return [
        ("repo gone (stamp frozen)", str(e["repo"]))
        for e in task.code_stamp.get("repos", [])
        if e.get("missing")
    ]


def _steps_summary(task: Task) -> str:
    if not task.steps:
        return "none"
    done = sum(1 for s in task.steps if s.get("done"))
    pending = [str(s.get("text", "")) for s in task.steps if not s.get("done")]
    tail = f" (next: {'; '.join(pending[:3])})" if pending else ""
    return f"{done}/{len(task.steps)} done{tail}"


def _approvals_summary(task: Task) -> str:
    if not task.approvals:
        return "none"
    items: list[str] = []
    for approval in task.approvals:
        action = str(approval.get("action", ""))
        target = str(approval.get("target", ""))
        stale = (
            action not in STAMP_FREE_ACTIONS
            and bool(task.stamp_key)
            and approval.get("stamp") != task.stamp_key
        )
        items.append(f"{action}:{target}{' (stale)' if stale else ''}")
    return ", ".join(items)


def _debate_summary(store: TaskStore, task: Task) -> str:
    state = load_debate(store, task.id)
    pending = _in_flight_debate_rounds(store, task)
    if state is None:
        if pending:
            return "unsettled rounds: " + ", ".join(f"{n:03d}" for n in pending)
        return "none"
    rows = debate_status(store, task.id)
    seats = ", ".join(f"{r['focus']}:{r['state']}" for r in rows) or "no seats"
    base = f"#{state.get('debate_id', '?')} ({state.get('status', '?')}) · {seats}"
    if pending:
        base += " · unsettled: " + ", ".join(f"{n:03d}" for n in pending)
    return base


def _status_pairs(store: TaskStore, task: Task) -> list[tuple[str, str]]:
    status_line = f"{task.status}{' (BLOCKED)' if task.blocked else ''} · workflow {task.workflow}"
    pairs: list[tuple[str, str]] = [("Status", status_line)]
    if task.blocked:
        pairs.append(("Blocked", f"{task.blocked.get('owner')}: {task.blocked.get('needs')}"))
    pairs += [
        ("Summary", task.summary or "-"),
        ("Code stamp", task.stamp_key or "no repository bound"),
        (
            "Repos",
            "; ".join(f"{r['path']} ({r.get('branch', '?')})" for r in task.repos) or "none",
        ),
        *_recovery_pairs(task),
        ("Steps", _steps_summary(task)),
        ("Decisions", "; ".join(str(d["text"]) for d in task.decisions[-5:]) or "none"),
        ("Approvals", _approvals_summary(task)),
        ("Debate", _debate_summary(store, task)),
    ]
    return pairs


def cmd_status(args: argparse.Namespace) -> int:
    store = _store()
    task = store.get(_resolve(store, args.task_id))
    config = _config(task)
    task = _refresh(store, task, config)
    pairs = _status_pairs(store, task)
    if args.json:
        emit_json(dict(pairs))
    else:
        emit_kv(pairs, title=f"{task.id} — {task.title}", full=True)
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
    task = _refresh(store, task, _config(task))
    request = replace(
        _approval_request(task, args.action, args.target),
        user_reply=args.user_reply,
        consequence=args.consequence,
    )
    record = build_approval(
        request, ApprovalContext(task.stamp_key, datetime.now(), task.approvals)
    )
    store.mutate(
        task.id,
        lambda t: t.approvals.append(record),
        log=f"Approved {args.action} on {args.target}",
    )
    emit_status(
        "ok",
        f"Approval '{args.action}' recorded ({record['verified']}); it expires if the code changes",
    )
    return 0


def _approval_request(task: Task, action: str, target: str) -> ApprovalRequest:
    reference = task.stamp_key or "no-code"
    return ApprovalRequest(action, target, "", task_id=task.id, reference=reference)


def cmd_ask(args: argparse.Namespace) -> int:
    """Print the question to send the user; its tag binds the reply to this request."""
    store = _store()
    task = store.get(args.task_id)
    task = _refresh(store, task, _config(task))
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


def cmd_round(args: argparse.Namespace) -> int:
    return round_cli.route(args)


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


def cmd_config(args: argparse.Namespace) -> int:
    config = load_config([TaskResolver._git_root(Path.cwd()) or Path.cwd()])
    errors = config.validate()
    emit_kv(
        [
            ("workflow", config.workflow),
            *(
                (f"role {name}", f"{r.get('agent')} {r.get('model', '')}".strip())
                for name, r in config.roles.items()
            ),
            ("allowed agents", ", ".join(sorted(config.allowed.agents)) or "none"),
            ("denied models", ", ".join(sorted(config.denied_models)) or "none"),
            ("orca cli", orca.orca_problem() or "found (needed only to dispatch workers)"),
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
        ApprovalError,
        subprocess.TimeoutExpired,
    ) as exc:
        emit_status("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
