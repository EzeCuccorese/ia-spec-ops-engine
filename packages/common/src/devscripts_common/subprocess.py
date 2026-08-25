"""
devscripts_common.subprocess — Ejecución determinista y segura de subprocesos con timeout estricto.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from devscripts_common.colors import Color, log_error

DEFAULT_COMMAND_TIMEOUT = 120  # 2 minutos por defecto


def run_command(
    command: Union[str, List[str]],
    check: bool = True,
    capture_output: bool = True,
    show_command: bool = False,
    error_message: Optional[str] = None,
    shell: bool = False,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Union[str, Path]] = None,
    timeout: Optional[int] = DEFAULT_COMMAND_TIMEOUT,
    isolated_git: bool = False,
) -> Optional[str]:
    """
    Ejecuta un comando de sistema de forma determinista con timeout configurable y captura limpia.
    """
    if show_command:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        print(f"{Color.CYAN}🚀 Ejecutando: {cmd_str}{Color.RESET}")

    merged_env = os.environ.copy()
    if isolated_git:
        for k in list(merged_env.keys()):
            if k.startswith("GIT_") and k not in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
                del merged_env[k]
        merged_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        merged_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    if env:
        merged_env.update(env)

    target_cmd = command
    if isinstance(command, str) and not shell:
        target_cmd = shlex.split(command)

    try:
        result = subprocess.run(
            target_cmd,
            shell=shell,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            env=merged_env,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        return result.stdout.strip() if capture_output else ""
    except subprocess.TimeoutExpired as e:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        log_error(f"Tiempo de espera agotado ({timeout}s) ejecutando: {cmd_str}")
        if check:
            raise
        return None
    except subprocess.CalledProcessError as e:
        if error_message:
            log_error(error_message)
        if capture_output:
            cmd_str = command if isinstance(command, str) else " ".join(command)
            log_error(f"Error ejecutando comando: {cmd_str}")
            if e.stderr:
                print(f"{Color.RED}{e.stderr.strip()}{Color.RESET}", file=sys.stderr)
        if check:
            raise
        return None
    except Exception as e:
        if error_message:
            log_error(error_message)
        log_error(f"Error inesperado: {str(e)}")
        if check:
            raise
        return None


def run_command_safe(
    cmd: Union[str, List[str]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = DEFAULT_COMMAND_TIMEOUT,
    isolated_git: bool = False,
) -> Tuple[int, str, str]:
    """
    Wrapper seguro que retorna (returncode, stdout, stderr) sin lanzar excepciones no controladas.
    """
    target_cmd = shlex.split(cmd) if isinstance(cmd, str) else cmd
    merged_env = os.environ.copy()
    if isolated_git:
        for k in list(merged_env.keys()):
            if k.startswith("GIT_") and k not in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
                del merged_env[k]
        merged_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        merged_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
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
    except Exception as e:
        return 1, "", str(e)
