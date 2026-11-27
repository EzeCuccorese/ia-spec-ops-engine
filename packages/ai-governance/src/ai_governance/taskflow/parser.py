"""Argument wiring of ``ai-governance taskflow`` (split out of ``cli``).

The handlers stay in ``cli`` and are looked up as ``cli.cmd_*`` when the parser is built."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import TypeAlias

from . import cli, debate_cli, review_cli
from .approvals import ACTIONS
from .guide import GUIDE
from .models import ROLES, WORKFLOWS, now_iso

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
    item = add(
        "close",
        cli.cmd_close,
        "Close a task (blocked only if rounds are still in flight unless --force)",
    )
    item.add_argument("--reason", default="")
    item.add_argument("--force", action="store_true", help="Close even when rounds are unsettled")
    item.add_argument(
        "--abandon", action="store_true", help="Close a task that left the flow unfinished"
    )
    item.add_argument(
        "--done-outside",
        "--external",
        action="store_true",
        dest="done_outside",
        help="Close a task completed outside the flow",
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
    item = add("stamp", cli.cmd_stamp, "Recompute the code stamp")
    item.add_argument(
        "--remote", action="store_true", help="Verify the integration branch with git ls-remote"
    )
    item = add(
        "status",
        cli.cmd_status,
        "Task metadata, bound repos, steps, decisions, approvals and debate state",
        task="optional",
    )
    item.add_argument("--json", action="store_true")
    item = add("block", cli.cmd_block, "Mark the task blocked waiting for someone")
    item.add_argument("--owner", required=True)
    item.add_argument("--needs", required=True)
    add("unblock", cli.cmd_unblock, "Clear the block")


def _approval_commands(sub: Subparsers) -> None:
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


def _round_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "round",
        cli.cmd_round,
        "Collect or abort a dispatched Orca round",
    )
    actions = item.add_subparsers(dest="action", required=True, metavar="{collect,abort}")
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
    item = add("rounds", cli.cmd_rounds, "List the rounds, or print one")
    item.add_argument("--show", type=int)


def _evidence_flags(item: argparse.ArgumentParser) -> None:
    item.add_argument(
        "--web",
        action="store_true",
        help="Allow web research and require a source URL per external claim",
    )
    item.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="PATH",
        help="Visual or binary artifact path the worker must inspect (repeatable)",
    )


def _debate_open_args(open_cmd: argparse.ArgumentParser) -> None:
    open_cmd.add_argument("--topic-file", required=True, metavar="PATH", help="Design topic file")
    open_cmd.add_argument(
        "--agents",
        action="append",
        required=True,
        metavar="A,B,...",
        help="Comma-separated seat agent ids (at least 2 providers; repeatable)",
    )
    open_cmd.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="AGENT=MODEL",
        help="Override the model for an agent or seat focus (repeatable)",
    )
    _evidence_flags(open_cmd)
    open_cmd.add_argument("--json", action="store_true", help="Print the dispatch result as JSON")


def _debate_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "debate",
        debate_cli.route,
        "Run a multi-provider design debate (open, cross-examine, status, close)",
    )
    actions = item.add_subparsers(
        dest="debate_action", required=True, metavar="{open,cross,status,close}"
    )
    _debate_open_args(
        actions.add_parser("open", help="Dispatch one independent thesis round per debate seat")
    )
    cross_cmd = actions.add_parser(
        "cross", help="Dispatch all-against-all cross-examination rounds"
    )
    cross_cmd.add_argument("--json", action="store_true", help="Print the dispatch result as JSON")
    status_cmd = actions.add_parser("status", help="Show the state of each debate seat")
    status_cmd.add_argument("--json", action="store_true", help="Print the seat table as JSON")
    close_cmd = actions.add_parser(
        "close", help="Write synthesis.md from collected rounds and record open points"
    )
    close_cmd.add_argument(
        "--partial", action="store_true", help="Close even when cross rounds are still pending"
    )


def _review_agent_args(item: argparse.ArgumentParser, role: str, *, required: bool) -> None:
    item.add_argument("--agent", required=required, help=f"Agent id that runs the {role} rounds")
    item.add_argument("--model", default="", help=f"Model of the {role} agent")
    item.add_argument("--json", action="store_true", help="Print the dispatch result as JSON")


def _review_commands(sub: Subparsers) -> None:
    add = _adder(sub)
    item = add(
        "review",
        review_cli.route,
        "Review pull requests: one reviewer per PR, a judge of another provider, one summary",
    )
    actions = item.add_subparsers(
        dest="review_action", required=True, metavar="{open,judge,status,close,payload}"
    )
    open_cmd = actions.add_parser(
        "open", help="Capture each pull request and dispatch one reviewer round per PR"
    )
    open_cmd.add_argument(
        "--pr", action="append", required=True, metavar="URL", help="Pull request URL (repeatable)"
    )
    open_cmd.add_argument("--lens", default="", help="Extra focus for the reviewers, in a sentence")
    _review_agent_args(open_cmd, "reviewer", required=True)
    judge_cmd = actions.add_parser(
        "judge",
        help="Dispatch one judge round per reviewed PR (another provider than the reviewer)",
    )
    _review_agent_args(judge_cmd, "judge", required=False)
    status_cmd = actions.add_parser("status", help="Show the rounds of each pull request")
    status_cmd.add_argument("--json", action="store_true", help="Print the table as JSON")
    close_cmd = actions.add_parser(
        "close", help="Write summary.md for the owner from the settled rounds; publishes nothing"
    )
    close_cmd.add_argument(
        "--partial", action="store_true", help="Close even when rounds are still pending"
    )
    payload_cmd = actions.add_parser(
        "payload", help="Write the GitHub review the owner approved and print how to send it"
    )
    payload_cmd.add_argument("--pr", required=True, help="Pull request key or URL of this review")
    payload_cmd.add_argument(
        "--event", required=True, choices=("comment", "request-changes", "approve")
    )
    payload_cmd.add_argument(
        "--include",
        default="",
        metavar="N,M",
        help="Findings to publish besides the confirmed ones",
    )


def _report_commands(sub: Subparsers) -> None:
    add = _adder(sub)
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
    add("config", cli.cmd_config, "Show and validate the taskflow config", task="none")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance taskflow",
        description="Track tasks across sessions, record approvals and run design debates.",
        epilog=GUIDE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")
    _task_commands(sub)
    _content_commands(sub)
    _reference_commands(sub)
    _lifecycle_commands(sub)
    _approval_commands(sub)
    _round_commands(sub)
    _debate_commands(sub)
    _review_commands(sub)
    _report_commands(sub)
    return parser
