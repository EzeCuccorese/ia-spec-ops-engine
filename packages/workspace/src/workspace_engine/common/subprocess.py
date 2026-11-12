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


def run_git(
    repo_path: str | Path, *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Runs git commands hermetically, isolating environment variables from subshells."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    clean_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    clean_env.setdefault("GIT_AUTHOR_NAME", "Workspace User")
    clean_env.setdefault("GIT_AUTHOR_EMAIL", "workspace@example.com")
    clean_env.setdefault("GIT_COMMITTER_NAME", "Workspace User")
    clean_env.setdefault("GIT_COMMITTER_EMAIL", "workspace@example.com")
    return subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True,
        text=True,
        env=clean_env,
        timeout=timeout,
    )


def _cmd_str(command: str | list[str]) -> str:
    return command if isinstance(command, str) else " ".join(command)


def _build_env(env: dict[str, str] | None, isolated_git: bool) -> dict[str, str]:
    merged_env = os.environ.copy()
    if isolated_git:
        _isolate_git_env(merged_env)
    if env:
        merged_env.update(env)
    return merged_env


def _log_process_failure(
    command: str | list[str],
    exc: subprocess.CalledProcessError,
    capture_output: bool,
    error_message: str | None,
) -> None:
    if error_message:
        log_error(error_message)
    if capture_output:
        log_error(f"Error running command: {_cmd_str(command)}")
        if exc.stderr:
            print(f"{Color.RED}{exc.stderr.strip()}{Color.RESET}", file=sys.stderr)


def _log_run_error(
    command: str | list[str],
    exc: BaseException,
    *,
    capture_output: bool,
    error_message: str | None,
) -> None:
    if isinstance(exc, subprocess.TimeoutExpired):
        log_error(f"Timed out ({exc.timeout}s) running: {_cmd_str(command)}")
        return
    if isinstance(exc, subprocess.CalledProcessError):
        _log_process_failure(command, exc, capture_output, error_message)
        return
    if error_message:
        log_error(error_message)
    log_error(f"Unexpected error: {exc}")


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
    """Runs a system command deterministically with a configurable timeout."""
    if show_command:
        print(f"{Color.CYAN}🚀 Running: {_cmd_str(command)}{Color.RESET}")
    target_cmd = shlex.split(command) if isinstance(command, str) else command
    pipe = subprocess.PIPE if capture_output else None
    try:
        result = subprocess.run(
            target_cmd,
            check=check,
            text=True,
            stdout=pipe,
            stderr=pipe,
            env=_build_env(env, isolated_git),
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        return result.stdout.strip() if capture_output else ""
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        _log_run_error(command, exc, capture_output=capture_output, error_message=error_message)
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
    merged_env = _build_env(env, isolated_git)

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
