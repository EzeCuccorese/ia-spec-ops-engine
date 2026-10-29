"""``ai-governance hook <agent> <event>`` — single entry point for agent hooks.

Hook commands registered by the installer all go through here, so the wire
format of each agent is handled in one place. Hooks are fail-open: an internal
error is reported on stderr and never blocks the agent. The only blocking hook
is the project quality gate (``stop-gate``), and only when the gate fails.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

SESSION_CONTEXT_CHARS = 400
GATE_BUDGET_CHARS = 1500


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _stdin_text() -> str:
    try:
        return sys.stdin.read()
    except OSError:
        return ""


def _cwd(payload: dict[str, Any]) -> Path:
    return Path(payload.get("cwd") or Path.cwd())


def _claude_pre_tool_use() -> int:
    """Bash: refuse while another agent holds the writer lease, else frugality advice."""
    from io import StringIO

    from .frugality.cli import load_config, run_pre_bash

    raw = _stdin_text()
    if _deny_claude(raw):
        return 0
    sys.stdin = StringIO(raw)
    run_pre_bash(load_config())
    return 0


def _target_path(payload: dict[str, Any]) -> Path:
    """The file a tool is about to write (``notebook_path`` for notebooks); a relative path
    is anchored at the session's directory, not the hook process's."""
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    path = Path(str(raw)) if raw else _cwd(payload)
    return path if path.is_absolute() else _cwd(payload) / path


def _deny_claude(raw: str, denial: Callable[[Path], str] | None = None) -> bool:
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        return False
    reason = (denial or _lease_denial)(_target_path(payload))
    if reason:
        decision = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
        print(json.dumps({"hookSpecificOutput": decision}))
    return bool(reason)


def _lease_denial(path: Path) -> str:
    """Reason to refuse a write in ``path``'s repository while another agent writes it."""
    from .taskflow.resolver import TaskResolver
    from .taskflow.rounds import active_lease
    from .taskflow.store import TaskStore

    root = TaskResolver.root_of_target(path)
    lease = active_lease(TaskStore(), root) if root else None
    if lease is None:
        return ""
    return f"{root} is being written by {lease.get('holder')} (taskflow writer lease): wait for that round to finish."


def _is_agent_config(path: Path) -> bool:
    """The user's own agent configuration and the taskflow state are never gated."""
    from .taskflow.store import TaskStore

    home = Path.home()
    free = [home / ".claude", home / ".codex", home / ".gemini", home / ".config", TaskStore().root]
    target = path.expanduser().resolve()
    return any(target.is_relative_to(base.resolve()) for base in free)


def _edit_denial(path: Path) -> str:
    """File edits also need a task bound to the repository: the session-start hint alone is
    easy to skip. Shell commands are not gated, so reading and exploring stay free."""
    from .taskflow.resolver import TaskResolver

    root = None if _is_agent_config(path) else TaskResolver.root_of_target(path)
    if root and not _has_task(root):
        return NO_TASK_HINT + " Tracking-only work: `taskflow new --workflow manual`."
    return _lease_denial(path)


def _claude_writer_lease() -> int:
    """Claude PreToolUse on edit tools: deny without a task for the repository, or while
    another agent holds the writer lease."""
    _deny_claude(_stdin_text(), _edit_denial)
    return 0


def _claude_post_tool_use() -> int:
    from .frugality.cli import load_config, run_post_bash

    run_post_bash(load_config())
    return 0


def _claude_stop() -> int:
    from .telemetry.cli import main as telemetry_main

    telemetry_main(["thresholds", "--notify"])
    return 0


def _active_task(repo: Path) -> tuple[Any, Any] | None:
    from .taskflow.resolver import TaskResolver
    from .taskflow.store import TaskStore

    store = TaskStore()
    task_id = TaskResolver.resolve_from_context(store.list(), repo)
    return (store, task_id) if task_id else None


NO_TASK_HINT = (
    "TASKFLOW: no task for this repository/branch. Before changing code, create one "
    "(`ai-governance taskflow new`, tri-agent) and start with the plan; `taskflow --help`."
)


def _has_task(repo: Path) -> bool:
    """An open task bound to this repository allows edits (even when several make
    ``taskflow here`` ask which one is meant); a branch name alone never does."""
    from .taskflow.resolver import TaskResolver
    from .taskflow.store import TaskStore

    return bool(TaskResolver.bound_to(TaskStore().list(), repo))


def _claude_session_start() -> int:
    """Injects 1-3 lines about the task bound to this repository (stdout -> context); in a
    repository without one, a reminder that code changes start a task, not the edit."""
    cwd = _cwd(_payload())
    found = _active_task(cwd)
    if found:
        from .taskflow.cli import digest

        store, task_id = found
        print(digest(store, task_id, max_chars=SESSION_CONTEXT_CHARS))
    elif hint := _session_hint(cwd):
        print(hint)
    return 0


def _session_hint(cwd: Path) -> str:
    from .taskflow.resolver import TaskResolver
    from .taskflow.store import TaskStore

    several = TaskResolver.bound_to(TaskStore().list(), cwd)
    if several:
        return (
            f"TASKFLOW: several tasks are bound here ({', '.join(sorted(several))}): "
            "pass the task id to taskflow commands."
        )
    return NO_TASK_HINT if TaskResolver._git_root(cwd) else ""


def _claude_session_end() -> int:
    """Records deterministic facts (branch, HEAD, changed files) in the task log."""
    repo = _cwd(_payload())
    found = _active_task(repo)
    if not found:
        return 0
    store, task_id = found

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5, check=False
        )
        return proc.stdout.strip() if proc.returncode == 0 else "?"

    changed = len([line for line in git("status", "--porcelain").splitlines() if line])
    store.append_log(
        task_id,
        f"Session ended on {git('branch', '--show-current')} @ {git('rev-parse', '--short', 'HEAD')}"
        f" with {changed} uncommitted file(s).",
    )
    return 0


def _claude_stop_gate() -> int:
    """Project quality gate on turn end: exit 2 + condensed failures blocks stopping."""
    payload = _payload()
    if payload.get("stop_hook_active"):
        return 0  # already continued once because of this gate: never loop
    ws = shutil.which("ws")
    if ws is None:
        return 0
    proc = subprocess.run(
        [ws, "check", "--changed", "--cache", "--json", "--budget", str(GATE_BUDGET_CHARS)],
        cwd=_cwd(payload),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return 0
    if result.get("status") != "failed":
        return 0
    log = f"\nFull log: ws log {result['log_id']}" if result.get("log_id") else ""
    print(f"Quality gate failed (ws check --changed):\n{result['text']}{log}", file=sys.stderr)
    return 2


def _codex_post_tool_use() -> int:
    """Codex: `block` + `reason` replaces the tool result the model sees."""
    from .frugality.cli import condensed_output, load_config

    replaced = condensed_output(_payload(), load_config())
    if replaced is not None:
        print(json.dumps({"decision": "block", "reason": replaced[0]}))
    return 0


def _antigravity_pre_tool_use() -> int:
    """Antigravity cannot rewrite output: deny raw noisy commands and ask for `ws run`."""
    from .frugality.cli import SKIP_CONDENSE

    payload = _payload()
    if _deny_antigravity(payload):
        return 0
    command = antigravity_command(payload).strip()
    if not command or command.startswith("ws ") or "#nofrugal" in command:
        return 0
    if SKIP_CONDENSE.match(command) or not NOISY_COMMAND.search(command):
        return 0
    reason = f"Re-run it as `ws run -- {command}` to get a condensed summary (full log kept)."
    print(json.dumps({"decision": "deny", "reason": reason}))
    return 0


ANTIGRAVITY_WRITE_TOOL = re.compile(r"write|replace|edit|delete|move|run_command", re.IGNORECASE)


def _deny_antigravity(payload: dict[str, Any]) -> bool:
    call = payload.get("toolCall") or {}
    name = str(call.get("name", "")) if isinstance(call, dict) else ""
    reason = _lease_denial(_cwd(payload)) if ANTIGRAVITY_WRITE_TOOL.search(name) else ""
    if reason:
        print(json.dumps({"decision": "deny", "reason": reason}))
    return bool(reason)


def _antigravity_writer_lease() -> int:
    """Antigravity PreToolUse on every tool: deny writes while another agent holds the lease."""
    _deny_antigravity(_payload())
    return 0


def antigravity_command(payload: dict[str, Any]) -> str:
    """Shell command of a `run_command` tool call (camelCase payload: toolCall.args.CommandLine)."""
    call = payload.get("toolCall") or {}
    if not isinstance(call, dict) or call.get("name") != "run_command":
        return ""
    args = call.get("args") or {}
    return str(args.get("CommandLine", "")) if isinstance(args, dict) else ""


NOISY_COMMAND = re.compile(
    r"\b(pytest|jest|vitest|go test|cargo (test|build)|mvnw?|gradlew?|npm (run )?(test|build)|"
    r"yarn (test|build)|pnpm (test|build)|tsc|eslint|docker build)\b"
)


HANDLERS: dict[tuple[str, str], Callable[[], int]] = {
    ("claude", "pre-tool-use"): _claude_pre_tool_use,
    ("claude", "post-tool-use"): _claude_post_tool_use,
    ("claude", "writer-lease"): _claude_writer_lease,
    ("claude", "stop"): _claude_stop,
    ("claude", "stop-gate"): _claude_stop_gate,
    ("claude", "session-start"): _claude_session_start,
    ("claude", "session-end"): _claude_session_end,
    ("codex", "post-tool-use"): _codex_post_tool_use,
    ("antigravity", "pre-tool-use"): _antigravity_pre_tool_use,
    ("antigravity", "writer-lease"): _antigravity_writer_lease,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 2 or (args[0], args[1]) not in HANDLERS:
        known = ", ".join(f"{agent} {event}" for agent, event in HANDLERS)
        print(f"Usage: ai-governance hook <agent> <event>  (known: {known})", file=sys.stderr)
        return 0
    try:
        return HANDLERS[(args[0], args[1])]()
    except Exception:  # noqa: BLE001 - hook boundary: never disrupt the agent
        traceback.print_exc(file=sys.stderr)
        return 0
