"""Bounded Orca worker status & reserved-round launcher for the visual dashboard."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..taskflow import orca
from ..taskflow.dispatch import DispatchError, verify_dispatch
from ..taskflow.store import TaskStore, atomic_write_text


def list_live_workers() -> dict[str, Any]:
    """Return live Orca workers using the read-only ``orca`` helper, degrading gracefully."""
    try:
        raw_rows, _ = orca._page("")
        rows = [orca._row(item) for item in raw_rows if isinstance(item, dict)]
    except orca.OrcaError as exc:
        return {"available": False, "reason": str(exc), "workers": []}
    return {
        "available": True,
        "reason": "",
        "workers": [
            {
                "dispatch_id": row.dispatch_id,
                "state": row.state,
                "liveness": row.liveness,
                "agent": row.agent,
                "running": row.running,
            }
            for row in rows
        ],
    }


def _validate_reserved_argv(found: dict[str, Any]) -> list[str]:
    raw_argv = found.get("argv")
    if (
        not isinstance(raw_argv, list)
        or not raw_argv
        or not all(isinstance(x, str) for x in raw_argv)
    ):
        raise DispatchError("Reserved dispatch has no valid argv")
    prefix = orca.require_orca()
    if raw_argv[: len(prefix)] != prefix or "worker-start" not in raw_argv:
        raise DispatchError("Refusing to run command that is not a sealed Orca worker-start")
    return list(raw_argv)


def _extract_dispatch_id(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    result = data.get("result")
    if isinstance(result, dict) and isinstance(result.get("dispatchId"), str):
        return str(result["dispatchId"])
    if isinstance(data.get("dispatchId"), str):
        return str(data["dispatchId"])
    return ""


def launch_reserved_round(store: TaskStore, task_id: str, round_n: int) -> dict[str, Any]:
    """Execute the sealed ``worker-start`` argv of a reserved round and persist its launch receipt."""
    found = verify_dispatch(store, task_id, round_n)
    task = store.get(task_id)
    if any(int(item.get("n", 0)) == round_n for item in task.rounds):
        raise DispatchError(f"Round {round_n:03d} is already settled")
    argv = _validate_reserved_argv(found)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except OSError as exc:
        raise orca.OrcaError(f"Failed to start Orca worker: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise orca.OrcaError(f"Orca worker-start failed: {detail}")
    launch_path = Path(str(found.get("launch", "")))
    if launch_path:
        atomic_write_text(launch_path, proc.stdout)
    return {
        "task_id": task_id,
        "round": round_n,
        "dispatch_id": _extract_dispatch_id(proc.stdout),
        "agent": str(found.get("agent", "")),
        "model": str(found.get("model", "")),
        "launch_file": str(launch_path),
    }
