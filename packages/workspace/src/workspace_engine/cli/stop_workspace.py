#!/usr/bin/env python3
"""
workspace_engine.cli.stop_workspace — Deterministic termination of workspace service processes.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path

from workspace_engine.common import (
    find_project_root,
    get_process_cmdline,
    log_info,
    log_success,
    log_warning,
)


def verify_process_identity(
    pid: int,
    repo_name: str,
    workspace_dir: Path,
    expected_cmd: str | None = None,
) -> bool:
    """Checks whether the process legitimately belongs to the workspace service and isn't a reused PID."""
    cmdline = get_process_cmdline(pid)
    if not cmdline:
        return False

    first_token = cmdline.split()[0].lower() if cmdline.split() else ""
    disallowed_binaries = {
        "grep",
        "ripgrep",
        "rg",
        "cat",
        "vim",
        "vi",
        "nano",
        "less",
        "more",
        "ps",
        "kill",
        "pkill",
        "top",
        "htop",
        "tail",
        "head",
        "sed",
        "awk",
    }
    if Path(first_token).name in disallowed_binaries:
        return False

    if expected_cmd and (expected_cmd in cmdline or cmdline in expected_cmd):
        return True

    ws_path_str = str(workspace_dir)
    ws_path_resolved = str(workspace_dir.resolve())
    repo_path_str = str(workspace_dir / repo_name)
    repo_path_resolved = str((workspace_dir / repo_name).resolve())

    # The process must belong to this workspace's path or this repo's path
    return bool(
        ws_path_str in cmdline
        or ws_path_resolved in cmdline
        or repo_path_str in cmdline
        or repo_path_resolved in cmdline
    )


def _parse_json_pid(raw_text: str, default_repo: str) -> tuple[int | None, str | None, str]:
    with contextlib.suppress(json.JSONDecodeError, ValueError, TypeError):
        meta = json.loads(raw_text)
        pid = int(meta.get("pid", 0))
        expected_cmd = meta.get("cmdline") or meta.get("command") or meta.get("cmd")
        repo = meta.get("repo") or default_repo
        return (pid if pid > 0 else None), expected_cmd, repo
    return None, None, default_repo


def _parse_text_pid(raw_text: str, default_repo: str) -> tuple[int | None, str | None, str]:
    lines = raw_text.splitlines()
    if not lines:
        return None, None, default_repo
    with contextlib.suppress(ValueError):
        pid = int(lines[0].strip())
        cmd = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
        return (pid if pid > 0 else None), cmd, default_repo
    return None, None, default_repo


def _parse_pid_file(pid_file: Path, default_repo: str) -> tuple[int | None, str | None, str]:
    try:
        raw_text = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None, default_repo
    if raw_text.startswith("{"):
        return _parse_json_pid(raw_text, default_repo)
    return _parse_text_pid(raw_text, default_repo)


def _signal_target(pid: int, proc_pgid: int | None, use_pg: bool, sig: int) -> None:
    if use_pg and proc_pgid is not None:
        with contextlib.suppress(OSError):
            os.killpg(proc_pgid, sig)
    with contextlib.suppress(OSError):
        os.kill(pid, sig)


def _wait_for_exit(pid: int, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.05)
        except OSError:
            return True
    return False


def _terminate_pid(pid: int, timeout: float, my_pgid: int) -> bool:
    proc_pgid = None
    with contextlib.suppress(OSError):
        proc_pgid = os.getpgid(pid)
    use_pg = proc_pgid is not None and proc_pgid == pid and proc_pgid != my_pgid

    term_deadline = time.time() + (timeout * 0.7)
    kill_deadline = time.time() + timeout
    _signal_target(pid, proc_pgid, use_pg, signal.SIGTERM)
    if _wait_for_exit(pid, term_deadline):
        return True
    _signal_target(pid, proc_pgid, use_pg, signal.SIGKILL)
    return _wait_for_exit(pid, kill_deadline)


def _stop_run_local_services(workspace_dir: Path, timeout: float) -> int:
    from workspace_engine.run_local import constants
    from workspace_engine.run_local.process_manager import graceful_kill_pid

    if not constants.PIDS_DIR.is_dir():
        return 0
    pid_files = list(constants.PIDS_DIR.glob("*.pid"))
    if not pid_files:
        return 0

    ws_resolved = workspace_dir.resolve()
    stopped = 0
    for pid_file in pid_files:
        pid, expected_cmd, name = _parse_pid_file(pid_file, pid_file.stem)
        if pid is None:
            pid_file.unlink(missing_ok=True)
            continue
        file_path: str | None = None
        with contextlib.suppress(OSError, json.JSONDecodeError):
            raw = pid_file.read_text(encoding="utf-8").strip()
            if raw.startswith("{"):
                file_path = json.loads(raw).get("path")
        if file_path and not Path(file_path).resolve().is_relative_to(ws_resolved):
            continue
        if graceful_kill_pid(
            pid,
            timeout=timeout,
            service_name=name,
            expected_cmd=expected_cmd,
            service_path=file_path or str(ws_resolved),
        ):
            stopped += 1
        pid_file.unlink(missing_ok=True)
    return stopped


def stop_workspace(start_dir: Path | None = None, timeout: float = 5.0) -> int:
    """Deterministically and boundedly stops all processes registered in .ai-toolkit/run-pids/."""
    workspace_dir = find_project_root(start_dir)
    pids_dir = workspace_dir / ".ai-toolkit" / "run-pids"
    run_local_stopped = _stop_run_local_services(workspace_dir, timeout)

    if not pids_dir.is_dir():
        if run_local_stopped > 0:
            log_success(f"Stopped {run_local_stopped} service(s).")
        else:
            log_info("No services running (.ai-toolkit/run-pids does not exist).")
        return 0

    pid_files = list(pids_dir.glob("*.pid"))
    if not pid_files:
        if run_local_stopped > 0:
            log_success(f"Stopped {run_local_stopped} service(s).")
        else:
            log_info("No active services (no .pid file found).")
        return 0

    stopped = run_local_stopped
    my_pgid = os.getpgrp()

    for pid_file in pid_files:
        pid, expected_cmd, repo = _parse_pid_file(pid_file, pid_file.stem)
        if pid is None:
            pid_file.unlink(missing_ok=True)
            continue

        try:
            os.kill(pid, 0)
        except OSError:
            log_warning(f"  {repo} (PID {pid}) is no longer running.")
            pid_file.unlink(missing_ok=True)
            continue

        if not verify_process_identity(pid, repo, workspace_dir, expected_cmd=expected_cmd):
            log_warning(
                f"  {repo} (PID {pid}) does not match the expected service identity. Signal skipped."
            )
            pid_file.unlink(missing_ok=True)
            continue

        log_info(f"Stopping {repo} (PID {pid})...")
        if _terminate_pid(pid, timeout, my_pgid):
            stopped += 1
        else:
            log_warning(
                f"  {repo} (PID {pid}) did not respond to termination signals after {timeout}s."
            )
        pid_file.unlink(missing_ok=True)

    if stopped > 0:
        log_success(f"Stopped {stopped} service(s).")
    else:
        log_info("No active services.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ws stop", description="Stops the workspace's active services."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for stopping processes.",
    )
    args = parser.parse_args(argv)
    sys.exit(stop_workspace(timeout=args.timeout))


if __name__ == "__main__":
    main()
