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


def _cwd(payload: dict[str, Any]) -> Path:
    return Path(payload.get("cwd") or Path.cwd())


def _claude_pre_tool_use() -> int:
    from .frugality.cli import load_config, run_pre_bash

    run_pre_bash(load_config())
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
    from .session.resolver import TaskResolver
    from .session.tracker import SessionTracker

    tracker = SessionTracker()
    task_id = TaskResolver.resolve_from_context(tracker.list_tasks(), repo)
    return (tracker, task_id) if task_id else None


def _claude_session_start() -> int:
    """Injects 1-3 lines about the task bound to this repository (stdout -> context)."""
    found = _active_task(_cwd(_payload()))
    if found:
        tracker, task_id = found
        print(tracker.digest(task_id, max_chars=SESSION_CONTEXT_CHARS))
    return 0


def _claude_session_end() -> int:
    """Records deterministic facts (branch, HEAD, changed files) in the task log."""
    repo = _cwd(_payload())
    found = _active_task(repo)
    if not found:
        return 0
    tracker, task_id = found

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5, check=False
        )
        return proc.stdout.strip() if proc.returncode == 0 else "?"

    changed = len([line for line in git("status", "--porcelain").splitlines() if line])
    tracker.append_log(
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

    command = str((_payload().get("tool_input") or {}).get("command", "")).strip()
    if not command or command.startswith("ws ") or "#nofrugal" in command:
        return 0
    if SKIP_CONDENSE.match(command) or not NOISY_COMMAND.search(command):
        return 0
    reason = f"Re-run it as `ws run -- {command}` to get a condensed summary (full log kept)."
    print(json.dumps({"decision": "deny", "reason": reason}))
    return 0


NOISY_COMMAND = re.compile(
    r"\b(pytest|jest|vitest|go test|cargo (test|build)|mvnw?|gradlew?|npm (run )?(test|build)|"
    r"yarn (test|build)|pnpm (test|build)|tsc|eslint|docker build)\b"
)


HANDLERS: dict[tuple[str, str], Callable[[], int]] = {
    ("claude", "pre-tool-use"): _claude_pre_tool_use,
    ("claude", "post-tool-use"): _claude_post_tool_use,
    ("claude", "stop"): _claude_stop,
    ("claude", "stop-gate"): _claude_stop_gate,
    ("claude", "session-start"): _claude_session_start,
    ("claude", "session-end"): _claude_session_end,
    ("codex", "post-tool-use"): _codex_post_tool_use,
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
