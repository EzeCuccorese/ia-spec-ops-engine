"""``ws run``, ``ws condense`` and ``ws log`` — condensed command output for agents."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from typing import IO

from workspace_engine.common.subprocess import DEFAULT_COMMAND_TIMEOUT

from . import logs
from .engine import DEFAULT_BUDGET, condense

_SUBPROCESS_RUN = subprocess.run
_SUBPROCESS_POPEN = subprocess.Popen
_TERM_GRACE_SECONDS = 1.0
_MAX_CAPTURE_BYTES = 10 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024


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


def _try_save_log(output: str, command: str) -> str | None:
    try:
        return logs.save(output, command)
    except OSError as exc:
        print(f"WARNING: could not save full log: {exc}", file=sys.stderr)
        return None


def _emit_run_result(
    output: str,
    display: str,
    exit_code: int,
    elapsed_and_budget: tuple[float, int],
) -> int:
    elapsed, budget = elapsed_and_budget
    result = condense(output, display, exit_code, budget)
    log_id = _try_save_log(output, display) if result.truncated else None
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


def _kill_process_tree(proc: subprocess.Popen, sig: int, is_posix: bool) -> None:
    if is_posix:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, sig)
        return
    if sig == signal.SIGTERM:
        proc.terminate()
    else:
        proc.kill()


def _terminate_and_drain(proc: subprocess.Popen[str], is_posix: bool) -> tuple[str, str]:
    _kill_process_tree(proc, signal.SIGTERM, is_posix)
    try:
        stdout, stderr = proc.communicate(timeout=_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc, signal.SIGKILL, is_posix)
        stdout, stderr = proc.communicate()
    else:
        if is_posix:
            _kill_process_tree(proc, signal.SIGKILL, True)
    return stdout, stderr


def _terminate_process(proc: subprocess.Popen[bytes], is_posix: bool) -> None:
    _kill_process_tree(proc, signal.SIGTERM, is_posix)
    try:
        proc.wait(timeout=_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc, signal.SIGKILL, is_posix)
        proc.wait()
    else:
        if is_posix:
            _kill_process_tree(proc, signal.SIGKILL, True)


def _read_stream_capped(
    stream: IO[bytes] | None, limit: int, chunks: list[bytes], truncated: list[bool]
) -> None:
    if stream is None:
        return
    remaining = limit
    while data := stream.read(_READ_CHUNK_BYTES):
        if remaining <= 0:
            truncated[0] = True
            continue
        take = data[:remaining]
        chunks.append(take)
        remaining -= len(take)
        if len(data) > len(take):
            truncated[0] = True


def _decode_capped(chunks: list[bytes], was_truncated: bool) -> str:
    text = b"".join(chunks).decode("utf-8", errors="replace")
    if was_truncated:
        text += "\n... [output truncated at capture limit]"
    return text


def _run_popen_mock(
    target: str | list[str], shell: bool, timeout: int | None, is_posix: bool
) -> subprocess.CompletedProcess[str]:
    with subprocess.Popen(
        target,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=is_posix,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(target, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _terminate_and_drain(proc, is_posix)
            raise subprocess.TimeoutExpired(
                cmd=target, timeout=exc.timeout, output=stdout, stderr=stderr
            ) from exc


def _collect_popen(
    proc: subprocess.Popen[bytes], timeout: int | None, is_posix: bool
) -> tuple[str, str, subprocess.TimeoutExpired | None]:
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    out_trunc, err_trunc = [False], [False]
    t_out = threading.Thread(
        target=_read_stream_capped,
        args=(proc.stdout, _MAX_CAPTURE_BYTES, out_chunks, out_trunc),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_read_stream_capped,
        args=(proc.stderr, _MAX_CAPTURE_BYTES, err_chunks, err_trunc),
        daemon=True,
    )
    t_out.start()
    t_err.start()
    timed_out_exc: subprocess.TimeoutExpired | None = None
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out_exc = exc
        _terminate_process(proc, is_posix)
    t_out.join(timeout=1.0)
    t_err.join(timeout=1.0)
    return (
        _decode_capped(out_chunks, out_trunc[0]),
        _decode_capped(err_chunks, err_trunc[0]),
        timed_out_exc,
    )


def _run_subprocess(
    target: str | list[str], shell: bool, timeout: int | None
) -> subprocess.CompletedProcess[str]:
    if subprocess.run is not _SUBPROCESS_RUN:
        return subprocess.run(
            target,
            shell=shell,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout,
        )
    is_posix = os.name == "posix"
    if subprocess.Popen is not _SUBPROCESS_POPEN:
        return _run_popen_mock(target, shell, timeout, is_posix)
    with subprocess.Popen(
        target,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=is_posix,
    ) as proc:
        stdout, stderr, timed_out_exc = _collect_popen(proc, timeout, is_posix)
        if timed_out_exc is not None:
            raise subprocess.TimeoutExpired(
                cmd=target, timeout=timed_out_exc.timeout, output=stdout, stderr=stderr
            ) from timed_out_exc
        return subprocess.CompletedProcess(target, proc.returncode, stdout, stderr)


def run(argv: list[str]) -> int:
    command, budget, raw_timeout = _parse_run_args(argv)
    shell = len(command) == 1
    timeout = raw_timeout if raw_timeout > 0 else None
    display = command[0] if shell else shlex.join(command)
    started = time.monotonic()
    try:
        proc = _run_subprocess(command[0] if shell else command, shell, timeout)
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
    text = sys.stdin.read(_MAX_CAPTURE_BYTES)
    result = condense(text, args.command, args.exit_code, args.budget)
    log_id = _try_save_log(text, args.command) if result.truncated else None
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
