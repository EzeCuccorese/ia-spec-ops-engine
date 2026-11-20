"""``ai-governance hook <agent> <event>`` — single entry point for agent hooks.

Hook commands registered by the installer all go through here, so the wire
format of each agent is handled in one place. Hooks are fail-open: an internal
error is reported on stderr and never blocks the agent. The only blocking hook
is the project quality gate (``stop-gate``), and only when the gate fails.
"""

from __future__ import annotations

import json
import os
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


def _brain_hint(cwd: Path) -> str:
    try:
        from .brain.store import BrainStore, infer_repo

        repo = infer_repo(cwd)
        if not repo:
            return ""
        count = BrainStore().count_for_repo(repo)
    except (OSError, UnicodeDecodeError):
        return ""
    if count <= 0:
        return ""
    noun = "note" if count == 1 else "notes"
    return f"BRAIN: {count} {noun} for {repo} — `ai-governance brain search <query>`"


def _combine_session_message(base: str, extra: str, max_chars: int) -> str:
    if not extra:
        return base[:max_chars] if len(base) > max_chars else base
    if len(extra) >= max_chars:
        return extra[: max_chars - 1] + "…" if len(extra) > max_chars else extra
    if not base:
        return extra
    budget = max_chars - len(extra) - 1
    if len(base) > budget:
        base = base[: budget - 1] + "…" if budget > 1 else ""
    return f"{base}\n{extra}" if base else extra


def _session_start_message(cwd: Path) -> str:
    brain_line = _brain_hint(cwd)
    found = _active_task(cwd)
    if found:
        from .taskflow.cli import digest

        store, task_id = found
        budget = (
            max(0, SESSION_CONTEXT_CHARS - len(brain_line) - 1)
            if brain_line
            else SESSION_CONTEXT_CHARS
        )
        base = digest(store, task_id, max_chars=budget) if budget > 0 else ""
        return _combine_session_message(base, brain_line, SESSION_CONTEXT_CHARS)
    return _combine_session_message(_session_hint(cwd), brain_line, SESSION_CONTEXT_CHARS)


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
    cwd = _cwd(payload)
    settings = effective(cwd)
    command = shlex.split(str(settings["hooks.gate_command"].value))
    program = shutil.which(command[0]) if command else None
    if program is None:
        return 0
    budget = settings["hooks.gate_budget_chars"].value
    timeout = float(settings["hooks.gate_timeout_seconds"].value)  # type: ignore[arg-type]
    try:
        proc = subprocess.run(
            [program, *_with_budget_arg(command[1:], budget)],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"Quality gate timed out after {timeout:.0f}s; allowing stop.", file=sys.stderr)
        return 0
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        print(
            f"Quality gate returned non-JSON output (exit {proc.returncode}); allowing stop.",
            file=sys.stderr,
        )
        return 0
    if not isinstance(result, dict) or result.get("status") != "failed":
        return 0
    log = f"\nFull log: ws log {result['log_id']}" if result.get("log_id") else ""
    label = " ".join(a for a in command if a not in ("--cache", "--json"))
    print(f"Quality gate failed ({label}):\n{result.get('text', '')}{log}", file=sys.stderr)
    return 2


def _codex_post_tool_use() -> int:
    """Codex: `block` + `reason` replaces the tool result the model sees."""
    from .frugality.cli import condensed_output, load_config

    replaced = condensed_output(_payload(), load_config())
    if replaced is not None:
        print(json.dumps({"decision": "block", "reason": replaced[0]}))
    return 0


_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|"})
_NOISY_EXECUTABLES = frozenset(
    {"pytest", "py.test", "jest", "vitest", "mvn", "mvnw", "gradle", "gradlew", "tsc", "eslint"}
)
_NOISY_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "go": frozenset({"test"}),
    "cargo": frozenset({"test", "build"}),
    "docker": frozenset({"build"}),
}
_JS_RUNNERS = frozenset({"npm", "yarn", "pnpm"})
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _command_segments(command: str) -> list[list[str]]:
    """Splits a shell line into unquoted command segments; empty on syntax errors."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _segment_executable(tokens: list[str]) -> list[str]:
    idx = 0
    while idx < len(tokens) and _ENV_ASSIGN.match(tokens[idx]):
        idx += 1
    parts = tokens[idx:]
    if not parts:
        return []
    exe = Path(parts[0]).name
    if exe == "npx":
        return parts[1:]
    if exe == "uv" and parts[1:2] == ["run"]:
        return parts[2:]
    if exe in {"python", "python3"} and parts[1:2] == ["-m"]:
        return parts[2:]
    return parts


def _is_noisy_segment(tokens: list[str]) -> bool:
    parts = _segment_executable(tokens)
    if not parts:
        return False
    exe = Path(parts[0]).name
    if exe == "ws":
        return False
    if exe in _NOISY_EXECUTABLES:
        return True
    if exe in _JS_RUNNERS:
        sub = (
            parts[2]
            if len(parts) > 2 and parts[1] == "run"
            else (parts[1] if len(parts) > 1 else "")
        )
        return sub in {"test", "build"}
    return len(parts) > 1 and parts[1] in _NOISY_SUBCOMMANDS.get(exe, frozenset())


_SHELL_META_CHARS = frozenset("><$`(){}*?[]~&")


def _needs_shell(command: str, segments: list[list[str]]) -> bool:
    if len(segments) != 1:
        return True
    if segments[0] and _ENV_ASSIGN.match(segments[0][0]):
        return True
    return any(ch in _SHELL_META_CHARS for ch in command)


def _antigravity_pre_tool_use() -> int:
    """Antigravity cannot rewrite output: deny raw noisy commands and ask for `ws run`."""
    from .frugality.cli import HELP_FLAG, SKIP_CONDENSE

    command = antigravity_command(_payload()).strip()
    if (
        not command
        or "#nofrugal" in command
        or os.environ.get("FRUGAL") == "0"
        or shutil.which("ws") is None
    ):
        return 0
    if SKIP_CONDENSE.match(command) or HELP_FLAG.search(command):
        return 0
    segments = _command_segments(command)
    if not any(_is_noisy_segment(seg) for seg in segments):
        return 0
    suggestion = (
        f"ws run -- sh -c {shlex.quote(command)}"
        if _needs_shell(command, segments)
        else f"ws run -- {command}"
    )
    reason = f"Re-run it as `{suggestion}` to get a condensed summary (full log kept)."
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
