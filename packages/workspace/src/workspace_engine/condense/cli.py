"""``ws run``, ``ws condense`` and ``ws log`` — condensed command output for agents."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time

from . import logs
from .engine import DEFAULT_BUDGET, condense


def _footer(exit_code: int, seconds: float | None, log_id: str | None) -> str:
    parts = [f"exit={exit_code}"]
    if seconds is not None:
        parts.append(f"{seconds:.1f}s")
    if log_id:
        parts.append(f"full log: ws log {log_id} [--grep RE | --lines A-B]")
    return "[" + " · ".join(parts) + "]"


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws run", description="Run a command, print a summary")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command: ws run -- <command>")
    shell = len(command) == 1
    started = time.monotonic()
    proc = subprocess.run(
        command[0] if shell else command,
        shell=shell,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    output = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    display = command[0] if shell else shlex.join(command)
    result = condense(output, display, proc.returncode, args.budget)
    log_id = logs.save(output, display) if result.truncated else None
    if result.text:
        print(result.text)
    print(_footer(proc.returncode, time.monotonic() - started, log_id))
    return proc.returncode


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
