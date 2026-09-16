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


def stop_workspace(start_dir: Path | None = None, timeout: float = 5.0) -> int:
    """Deterministically and boundedly stops all processes registered in .ai-toolkit/run-pids/."""
    workspace_dir = find_project_root(start_dir)
    pids_dir = workspace_dir / ".ai-toolkit" / "run-pids"

    if not pids_dir.is_dir():
        log_info("No services running (.ai-toolkit/run-pids does not exist).")
        return 0

    pid_files = list(pids_dir.glob("*.pid"))
    if not pid_files:
        log_info("No active services (no .pid file found).")
        return 0

    stopped = 0
    my_pgid = os.getpgrp()

    for pid_file in pid_files:
        repo = pid_file.stem
        raw_text = ""
        try:
            raw_text = pid_file.read_text(encoding="utf-8").strip()
        except OSError:
            pid_file.unlink(missing_ok=True)
            continue

        pid: int | None = None
        expected_cmd: str | None = None

        if raw_text.startswith("{"):
            try:
                meta = json.loads(raw_text)
                pid = int(meta.get("pid", 0))
                expected_cmd = meta.get("cmdline") or meta.get("command") or meta.get("cmd")
                if meta.get("repo"):
                    repo = meta["repo"]
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        else:
            lines = raw_text.splitlines()
            if lines:
                try:
                    pid = int(lines[0].strip())
                    if len(lines) > 1 and lines[1].strip():
                        expected_cmd = lines[1].strip()
                except ValueError:
                    pass

        if pid is None or pid <= 0:
            pid_file.unlink(missing_ok=True)
            continue

        is_running = False
        try:
            os.kill(pid, 0)
            is_running = True
        except OSError:
            is_running = False

        if not is_running:
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

        proc_pgid = None
        with contextlib.suppress(OSError):
            proc_pgid = os.getpgid(pid)

        # Only signal the process group if it's the group leader and NOT our own group
        use_pg = proc_pgid is not None and proc_pgid == pid and proc_pgid != my_pgid

        if use_pg and proc_pgid is not None:
            with contextlib.suppress(OSError):
                os.killpg(proc_pgid, signal.SIGTERM)
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)

        term_deadline = time.time() + (timeout * 0.7)
        kill_deadline = time.time() + timeout
        process_terminated = False

        while time.time() < term_deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except OSError:
                process_terminated = True
                break

        if not process_terminated:
            if use_pg and proc_pgid is not None:
                with contextlib.suppress(OSError):
                    os.killpg(proc_pgid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)

            while time.time() < kill_deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.05)
                except OSError:
                    process_terminated = True
                    break

        if process_terminated:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Stops the workspace's active services.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for stopping processes.",
    )
    args = parser.parse_args()
    sys.exit(stop_workspace(timeout=args.timeout))


if __name__ == "__main__":
    main()
