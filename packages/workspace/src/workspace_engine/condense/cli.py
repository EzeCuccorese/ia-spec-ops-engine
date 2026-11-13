"""``ws run``, ``ws condense`` and ``ws log`` — condensed command output for agents."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time

from workspace_engine.common.subprocess import DEFAULT_COMMAND_TIMEOUT

from . import logs
from .engine import DEFAULT_BUDGET, condense


def _decode_partial(stream: bytes | str | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def _combine_output(stdout: str, stderr: str) -> str:
    return stdout + (("\n" + stderr) if stderr else "")


def _footer(exit_code: int, seconds: float | None, log_id: str | None) -> str:
    parts = [f"exit={exit_code}"]
    if seconds is not None:
        parts.append(f"{seconds:.1f}s")
    if log_id:
        parts.append(f"full log: ws log {log_id} [--grep RE | --lines A-B]")
    return "[" + " · ".join(parts) + "]"


def _emit_run_result(
    output: str,
    display: str,
    exit_code: int,
    elapsed_and_budget: tuple[float, int],
) -> int:
    elapsed, budget = elapsed_and_budget
    result = condense(output, display, exit_code, budget)
    log_id = logs.save(output, display) if result.truncated else None
    if result.text:
        print(result.text)
    print(_footer(exit_code, elapsed, log_id))
    return exit_code


def _parse_run_args(argv: list[str]) -> tuple[list[str], int, int]:
    parser = argparse.ArgumentParser(prog="ws run", description="Run a command, print a summary")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        help="Command timeout in seconds (<= 0 disables)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command: ws run -- <command>")
    return command, args.budget, args.timeout


def run(argv: list[str]) -> int:
    command, budget, raw_timeout = _parse_run_args(argv)
    shell = len(command) == 1
    timeout = raw_timeout if raw_timeout > 0 else None
    display = command[0] if shell else shlex.join(command)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command[0] if shell else command,
            shell=shell,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = _combine_output(_decode_partial(exc.stdout), _decode_partial(exc.stderr))
        print(f"ERROR: command timed out after {raw_timeout}s: {display}", file=sys.stderr)
        return _emit_run_result(output, display, 124, (time.monotonic() - started, budget))
    output = _combine_output(proc.stdout, proc.stderr)
    return _emit_run_result(output, display, proc.returncode, (time.monotonic() - started, budget))


def condense_stdin(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws condense", description="Condense text on stdin")
    parser.add_argument("--command", default="")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    text = sys.stdin.read()
    result = condense(text, args.command, args.exit_code, args.budget)
    log_id = logs.save(text, args.command) if result.truncated else None
    if args.json:
        payload = {
            "schema_version": 1,
            "text": result.text,
            "tool": result.tool,
            "truncated": result.truncated,
            "original_chars": result.original_chars,
            "log_id": log_id,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(result.text)
        if log_id:
            print(_footer(args.exit_code or 0, None, log_id))
    return 0


def show_log(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws log", description="Read a saved full output")
    parser.add_argument("log_id", nargs="?", help="Log id (omit with --last)")
    parser.add_argument("--last", action="store_true", help="Read the most recent log")
    parser.add_argument("--grep")
    parser.add_argument("--lines", help="Range A-B (1-based)")
    args = parser.parse_args(argv)
    try:
        if not args.log_id and not args.last:
            raise ValueError("Pass a log id or --last")
        log_id = "--last" if args.last else args.log_id
        print(logs.read(log_id, grep=args.grep, lines=args.lines))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
