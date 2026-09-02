#!/usr/bin/env python3
"""
workspace_engine.cli.stop_workspace — Detención determinista de procesos de servicios levantados en el workspace.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import time
from pathlib import Path

from workspace_engine.utils import find_project_root, log_info, log_success, log_warning


def stop_workspace(start_dir: Path | None = None) -> int:
    """Detiene todos los procesos registrados en .ai-toolkit/run-pids/."""
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
    for pid_file in pid_files:
        repo = pid_file.stem
        try:
            pid = int(pid_file.read_text().strip())
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)
            continue

        is_running = False
        try:
            os.kill(pid, 0)
            is_running = True
        except OSError:
            is_running = False

        if is_running:
            log_info(f"Deteniendo {repo} (PID {pid})...")
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except OSError:
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGTERM)

            for _ in range(50):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except OSError:
                    break
            stopped += 1
        else:
            log_warning(f"  {repo} (PID {pid}) ya no está corriendo.")

        pid_file.unlink(missing_ok=True)

    if stopped > 0:
        log_success(f"Se detuvieron {stopped} servicio(s).")
    else:
        log_info("No había servicios activos.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Detiene los servicios activos del workspace.")
    parser.parse_args()
    sys.exit(stop_workspace())


if __name__ == "__main__":
    main()
