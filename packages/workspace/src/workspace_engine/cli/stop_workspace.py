#!/usr/bin/env python3
"""
workspace_engine.cli.stop_workspace — Detención determinista de procesos de servicios levantados en el workspace.
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

from workspace_engine.utils import (
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
    """Verifica si el proceso pertenece legítimamente al servicio del workspace y no es un PID reutilizado."""
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
    """Detiene determinista y acotadamente todos los procesos registrados en .ai-toolkit/run-pids/."""
    workspace_dir = find_project_root(start_dir)
    pids_dir = workspace_dir / ".ai-toolkit" / "run-pids"

    if not pids_dir.is_dir():
        log_info("No hay servicios corriendo (.ai-toolkit/run-pids no existe).")
        return 0

    pid_files = list(pids_dir.glob("*.pid"))
    if not pid_files:
        log_info("No hay servicios activos (ningún archivo .pid encontrado).")
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
            except Exception:
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
            log_warning(f"  {repo} (PID {pid}) ya no está corriendo.")
            pid_file.unlink(missing_ok=True)
            continue

        if not verify_process_identity(pid, repo, workspace_dir, expected_cmd=expected_cmd):
            log_warning(
                f"  {repo} (PID {pid}) no coincide con la identidad esperada del servicio. Señal omitida."
            )
            pid_file.unlink(missing_ok=True)
            continue

        log_info(f"Deteniendo {repo} (PID {pid})...")

        proc_pgid = None
        with contextlib.suppress(OSError):
            proc_pgid = os.getpgid(pid)

        # Solo señalizar el process group si es líder de grupo y NO es nuestro propio grupo
        use_pg = proc_pgid is not None and proc_pgid == pid and proc_pgid != my_pgid

        if use_pg:
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
            if use_pg:
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
                f"  {repo} (PID {pid}) no respondió a las señales de terminación tras {timeout}s."
            )

        pid_file.unlink(missing_ok=True)

    if stopped > 0:
        log_success(f"Se detuvieron {stopped} servicio(s).")
    else:
        log_info("No había servicios activos.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Detiene los servicios activos del workspace.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Tiempo límite en segundos para la detención de procesos.",
    )
    args = parser.parse_args()
    sys.exit(stop_workspace(timeout=args.timeout))


if __name__ == "__main__":
    main()
