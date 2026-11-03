"""Argument wiring of ``ai-governance taskflow`` (split out of ``cli``, no behavior change).

The handlers stay in ``cli`` and are looked up as ``cli.cmd_*`` when the parser is built."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import TypeAlias

from . import cli
from .approvals import ACTIONS
from .guide import GUIDE
from .models import EXIT_PHASES, PHASES, ROLES, VERDICTS, WORKFLOWS, now_iso

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
    item = add("list", cli.cmd_list, "List open tasks", task="none")
    item.add_argument("--all", action="store_true", help="Include closed tasks")
    item.add_argument("--json", action="store_true")
    for name, text in (
        ("show", "Show a task (default: the one bound to this directory)"),
        ("here", "Task bound to this branch/repository"),
    ):
        item = add(name, cli.cmd_show, text, task="optional" if name == "show" else "none")
        item.add_argument("--full", action="store_true", help="Include the long log")
        item.add_argument("--json", action="store_true")
        if name == "here":
            item.set_defaults(task_id=None)
    item = add("new", cli.cmd_new, "Create a task (ID = Jira key or slug)")
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
    item = add("switch", cli.cmd_switch, "Set the active subtask of a task")
    item.add_argument("subtask")
    item = add("summary", cli.cmd_summary, "Replace the summary")
    item.add_argument("text")
    item = add("step", cli.cmd_step, "Add, complete or remove a step")
    item.add_argument("action", choices=("add", "done", "remove"))
    item.add_argument("value", help="Step text, or its 1-based number for done/remove")
    item = add(
        "fact",
        cli._list_append("facts", lambda a: {"text": a.text, "at": now_iso()}),
        "Record a verified fact",
    )
    item.add_argument("text")
    item = add(
        "decide",
        cli._list_append("decisions", lambda a: {"text": a.text, "why": a.why, "at": now_iso()}),
        "Record a decision",
    )
    item.add_argument("text")
    item.add_argument("--why", default="")


def _reference_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "link",
        cli._list_append("links", lambda a: {"title": a.title, "url": a.url}),
        "Add a titled URL",
    )
    item.add_argument("title")
    item.add_argument("url")
    item = add(
        "reference",
        cli._list_append("references", lambda a: {"kind": a.kind, "value": a.value, "url": a.url}),
        "Add an external reference (jira, pr, slack...)",
    )
    item.add_argument("kind")
    item.add_argument("value")
    item.add_argument("--url", default="")
    item = add("note", cli.cmd_note, "Append to the long log")
    item.add_argument("text")
    item = add("friction", cli.cmd_friction, "Record a friction of the flow itself")
    item.add_argument("text")


def _lifecycle_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    for name, status in (("pause", "paused"), ("reopen", "active"), ("resume", "active")):
        item = add(name, cli._set_status(status), f"Mark the task {status}")
        item.add_argument("--reason", default="")
    item = add("close", cli.cmd_close, "Close a task (after done/findings, or --abandon)")
    item.add_argument("--reason", default="")
    item.add_argument(
        "--abandon", action="store_true", help="Close a task that left the flow unfinished"
    )
    item = add("bind", cli.cmd_bind, "Bind a repository/worktree to the task")
    item.add_argument("--repo", default=".")
    item.add_argument("--branch", default="")
    item.add_argument(
        "--integration-branch",
        default="",
        help="Branch that is deployed/merged into (e.g. develop)",
    )
    item.add_argument("--pr", default="")
    item = add("unbind", cli.cmd_unbind, "Remove a bound repository")
    item.add_argument("--repo", default=".")
    item = add("stamp", cli.cmd_stamp, "Recompute the code stamp and the risk")
    item.add_argument(
        "--remote", action="store_true", help="Verify the integration branch with git ls-remote"
    )
    item = add(
        "status",
        cli.cmd_status,
        "Phase, missing requirements, stale verdicts and next command",
        task="optional",
    )
    item.add_argument("--json", action="store_true")
    item = add("phase", cli.cmd_phase, "Move the task to a phase (checked against the gates)")
    item.add_argument("target", choices=(*PHASES, *EXIT_PHASES))
    item = add("block", cli.cmd_block, "Mark the task blocked waiting for someone")
    item.add_argument("--owner", required=True)
    item.add_argument("--needs", required=True)
    add("unblock", cli.cmd_unblock, "Clear the block")


def _approval_round_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("ask", cli.cmd_ask, "Print the tag your approval question must carry")
    item.add_argument("--action", required=True, choices=ACTIONS)
    item.add_argument("--target", required=True)
    item = add("approve", cli.cmd_approve, "Record the user's approval given in the chat")
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
    item = add("tdd", cli.cmd_tdd, "Record the red/green test runs (or a skip the user approved)")
    item.add_argument("stage", choices=("red", "green", "skip"))
    item.add_argument("--cmd", default="", help="Test command, the same for red and green")
    item.add_argument("--reason", default="")


def _round_agent_args(item: argparse.ArgumentParser) -> None:
    item.add_argument("--phase", choices=PHASES, help="Default: the task's phase")
    item.add_argument("--prompt-file")
    item.add_argument("--prompt")
    item.add_argument("--agent", default="", help="Override the configured agent")
    item.add_argument("--model", default="")


def _round_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "round",
        cli.cmd_round,
        "Dispatch a reader round to an Orca worker and collect or abort it, or record one",
    )
    actions = item.add_subparsers(dest="action", required=True, metavar="action")
    run = actions.add_parser("run", help=argparse.SUPPRESS)  # removed: migration stub
    run.add_argument("--role", choices=ROLES)
    _round_agent_args(run)
    run.add_argument("--timeout", type=int, default=0)
    record = actions.add_parser("record", help="Record a round that ran elsewhere (context only)")
    record.add_argument("--role", required=True, choices=ROLES)
    _round_agent_args(record)
    record.add_argument("--verdict", choices=VERDICTS, default="info")
    record.add_argument("--file", help="The round's text (default: stdin)")
    _dispatch_commands(actions)


def _dispatch_commands(actions: Subparsers) -> None:
    dispatch = actions.add_parser(
        "dispatch", help="Reserve a planner/validator round and print its Orca worker-start line"
    )
    dispatch.add_argument("--role", required=True, choices=ROLES)
    _round_agent_args(dispatch)
    dispatch.add_argument("--focus", default="")
    dispatch.add_argument("--json", action="store_true", help="Print the command as a JSON array")
    collect = actions.add_parser("collect", help="Settle a dispatched round from its worker")
    collect.add_argument("--round", type=int, required=True)
    collect.add_argument("--dispatch-id", required=True, help="Orca's id of the worker you started")
    collect.add_argument("--answer-file", help="Read the answer here instead of runs/N/answer.txt")
    abort = actions.add_parser("abort", help="Settle a dispatched round as aborted (audited)")
    abort.add_argument("--round", type=int, required=True)
    abort.add_argument("--reason", required=True)
    binding = abort.add_mutually_exclusive_group(required=True)
    binding.add_argument("--dispatch-id", help="Orca's id of the worker that ran this round")
    binding.add_argument(
        "--never-started",
        action="store_true",
        help="Your assertion that no worker was started for it (recorded; it is not evidence)",
    )


def _judge_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add("rounds", cli.cmd_rounds, "List the rounds, or print one")
    item.add_argument("--show", type=int)
    item = add(
        "judge",
        cli.cmd_judge,
        "Run the checks on the committed code, then print the Orca line of every required judge",
    )
    item.add_argument("--focus", default="", help="Run only this focus (the gate still needs all)")
    item = add("deploy", cli.cmd_deploy, "Record a deployment the user made (never deploys)")
    item.add_argument("--env", required=True)
    item.add_argument("--repo", required=True)
    item.add_argument("--sha", required=True)
    item.add_argument("--provenance", choices=("ci", "health", "k8s", "manual"), required=True)
    item = add(
        "evidence", cli.cmd_evidence, "Store evidence (test results, captures) bound to a SHA"
    )
    item.add_argument("--kind", required=True, choices=("staging", "review", "prod", "other"))
    item.add_argument("--file", required=True)
    item.add_argument("--deployed-sha", default="")
    for name, handler, text in (
        ("findings", cli.cmd_findings, "Findings package for another owner"),
        ("draft", cli.cmd_draft, "Draft comment for the ticket"),
    ):
        item = add(name, handler, text)
        item.add_argument("--out")
    item = add("handoff", cli.cmd_handoff, "Context package for a role, secrets scrubbed")
    item.add_argument("--to", required=True, choices=ROLES)
    item.add_argument("--out")
    item = add("digest", cli.cmd_digest, "Compact context of the open tasks", task="none")
    item.add_argument("--id", dest="task_id")
    item.add_argument("--max-chars", type=int, default=1600)
    item = add(
        "trust", cli.cmd_trust, "Approve the check commands a repository defines", task="none"
    )
    item.add_argument("--repo", default=".")
    item.add_argument("--yes", action="store_true", help="Do not ask (outside agent mode)")
    add("config", cli.cmd_config, "Show and validate the taskflow config", task="none")


def build_parser() -> argparse.ArgumentParser:
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
    _round_commands(sub)
    _judge_commands(sub)
    return parser
