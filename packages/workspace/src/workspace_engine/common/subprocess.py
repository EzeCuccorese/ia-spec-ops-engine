"""
workspace_engine.common.subprocess — Deterministic, safe subprocess execution with strict timeouts.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from workspace_engine.common.colors import Color, log_error

DEFAULT_COMMAND_TIMEOUT = 120  # 2 minutes by default


def _isolate_git_env(merged_env: dict[str, str]) -> None:
    """Strips GIT_* variables (except author/committer identity) and disables global/system git config."""
    for k in list(merged_env.keys()):
        if k.startswith("GIT_") and k not in (
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            del merged_env[k]
    merged_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    merged_env["GIT_CONFIG_SYSTEM"] = "/dev/null"


def run_command(
    command: str | list[str],
    check: bool = True,
    capture_output: bool = True,
    show_command: bool = False,
    error_message: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    timeout: int | None = DEFAULT_COMMAND_TIMEOUT,
    isolated_git: bool = False,
) -> str | None:
    """
    Runs a system command deterministically with a configurable timeout and clean output capture.

    `command` is never passed through a shell: a string is tokenized with `shlex.split`
    and a list is used as-is (argv form).
    """
    if show_command:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        print(f"{Color.CYAN}🚀 Running: {cmd_str}{Color.RESET}")

    merged_env = os.environ.copy()
    if isolated_git:
        _isolate_git_env(merged_env)
    if env:
        merged_env.update(env)

    target_cmd = shlex.split(command) if isinstance(command, str) else command

    try:
        result = subprocess.run(
            target_cmd,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            env=merged_env,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        return result.stdout.strip() if capture_output else ""
    except subprocess.TimeoutExpired:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        log_error(f"Timed out ({timeout}s) running: {cmd_str}")
        if check:
            raise
        return None
    except subprocess.CalledProcessError as e:
        if error_message:
            log_error(error_message)
        if capture_output:
            cmd_str = command if isinstance(command, str) else " ".join(command)
            log_error(f"Error running command: {cmd_str}")
            if e.stderr:
                print(f"{Color.RED}{e.stderr.strip()}{Color.RESET}", file=sys.stderr)
        if check:
            raise
        return None
    except (OSError, subprocess.SubprocessError) as e:
        if error_message:
            log_error(error_message)
        log_error(f"Unexpected error: {e}")
        if check:
            raise
        return None


def run_command_safe(
    cmd: str | list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = DEFAULT_COMMAND_TIMEOUT,
    isolated_git: bool = False,
) -> tuple[int, str, str]:
    """
    Safe wrapper that returns (returncode, stdout, stderr) without raising uncontrolled exceptions.
    """
    target_cmd = shlex.split(cmd) if isinstance(cmd, str) else cmd
    merged_env = os.environ.copy()
    if isolated_git:
        _isolate_git_env(merged_env)
    if env:
        merged_env.update(env)

    try:
        res = subprocess.run(
            target_cmd,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"TimeoutExpired after {timeout}s"
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
