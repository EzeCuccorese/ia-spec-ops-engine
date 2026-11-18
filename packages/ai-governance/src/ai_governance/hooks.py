"""``ai-governance hook <agent> <event>`` — single entry point for agent hooks.

Hook commands registered by the installer all go through here, so the wire
format of each agent is handled in one place. Hooks are fail-open: an internal
error is reported on stderr and never blocks the agent. The only blocking hook
is the project quality gate (``stop-gate``), and only when the gate fails.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .settings import effective

SESSION_CONTEXT_CHARS = 400


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _cwd(payload: dict[str, Any]) -> Path:
    raw = payload.get("cwd")
    if not raw:
        paths = payload.get("workspacePaths")
        if isinstance(paths, list) and paths and isinstance(paths[0], str):
            raw = paths[0]
    return Path(raw or Path.cwd())


def _claude_pre_tool_use() -> int:
    """Bash: frugality advice on wasteful commands."""
    from .frugality.cli import load_config, run_pre_bash

    run_pre_bash(load_config())
    return 0


def _claude_post_tool_use() -> int:
    from .frugality.cli import load_config, post_bash_output

    fields = post_bash_output(_payload(), load_config()) or {}
    if fields:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", **fields}}))
    return 0


def _active_task(repo: Path) -> tuple[Any, Any] | None:
    from .taskflow.resolver import TaskResolver
    from .taskflow.store import TaskStore

    store = TaskStore()
    task_id = TaskResolver.resolve_from_context(store.list(), repo)
    return (store, task_id) if task_id else None


NO_TASK_HINT = (
    "TASKFLOW: no task bound to this repository/branch. For multi-session tickets or design "
    "debates, run 'ai-governance taskflow new'; normal code changes use 'ws check --changed'."
)


def _session_start_message(cwd: Path) -> str:
    found = _active_task(cwd)
    if found:
        from .taskflow.cli import digest

        store, task_id = found
        return digest(store, task_id, max_chars=SESSION_CONTEXT_CHARS)
    return _session_hint(cwd)


def _claude_session_start() -> int:
    """Injects 1-3 lines about the task bound to this repository (stdout -> context); in a
    repository without one, a reminder that code changes start a task, not the edit."""
    if msg := _session_start_message(_cwd(_payload())):
        print(msg)
    return 0


def _antigravity_session_start() -> int:
    """Antigravity SessionStart: inject active task summary via ``injectSteps``."""
    if msg := _session_start_message(_cwd(_payload())):
        print(json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": msg}}]}))
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
        try:
            proc = subprocess.run(
                ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError):  # gone directory or a hung git
            return "?"
        return proc.stdout.strip() if proc.returncode == 0 else "?"

    status = git("status", "--porcelain")
    changed = (
        "an unknown number of"
        if status == "?"
        else len([line for line in status.splitlines() if line])
    )
    store.append_log(
        task_id,
        f"Session ended on {git('branch', '--show-current')} @ {git('rev-parse', '--short', 'HEAD')}"
        f" with {changed} uncommitted file(s).",
    )
    return 0


def _with_budget_arg(args: list[str], budget: object) -> list[str]:
    if any(arg == "--budget" or arg.startswith("--budget=") for arg in args):
        return args
    return [*args, "--budget", str(budget)]


def _claude_stop_gate() -> int:
    """Project quality gate on turn end: exit 2 + condensed failures blocks stopping."""
    payload = _payload()
    if payload.get("stop_hook_active"):
        return 0  # already continued once because of this gate: never loop
    settings = effective()
    command = shlex.split(str(settings["hooks.gate_command"].value))
    program = shutil.which(command[0]) if command else None
    if program is None:
        return 0
    budget = settings["hooks.gate_budget_chars"].value
    proc = subprocess.run(
        [program, *_with_budget_arg(command[1:], budget)],
        cwd=_cwd(payload),
        capture_output=True,
        text=True,
        timeout=float(settings["hooks.gate_timeout_seconds"].value),  # type: ignore[arg-type]
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return 0
    if result.get("status") != "failed":
        return 0
    log = f"\nFull log: ws log {result['log_id']}" if result.get("log_id") else ""
    label = " ".join(a for a in command if a not in ("--cache", "--json"))
    print(f"Quality gate failed ({label}):\n{result['text']}{log}", file=sys.stderr)
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
    from .frugality.cli import HELP_FLAG, SKIP_CONDENSE

    command = antigravity_command(_payload()).strip()
    if not command or command.startswith("ws ") or "#nofrugal" in command:
        return 0
    if (
        SKIP_CONDENSE.match(command)
        or HELP_FLAG.search(command)
        or not NOISY_COMMAND.search(command)
    ):
        return 0
    reason = f"Re-run it as `ws run -- {command}` to get a condensed summary (full log kept)."
    print(json.dumps({"decision": "deny", "reason": reason}))
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
    ("claude", "stop-gate"): _claude_stop_gate,
    ("claude", "session-start"): _claude_session_start,
    ("claude", "session-end"): _claude_session_end,
    ("codex", "session-start"): _claude_session_start,
    ("codex", "post-tool-use"): _codex_post_tool_use,
    ("antigravity", "session-start"): _antigravity_session_start,
    ("antigravity", "pre-tool-use"): _antigravity_pre_tool_use,
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
