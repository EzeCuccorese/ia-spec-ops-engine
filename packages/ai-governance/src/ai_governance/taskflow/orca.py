"""Read-only view of the Orca CLI.

The engine never starts, stops or changes a worker: it prints the ``worker-start`` line for
the coordinating session to run, and it may only ask about workers (``worker-show`` and
``worker-list``). Anything else is refused here, before a process is spawned. The answers
are a best-effort guard ("is it still running", "which agent ran it"); they never decide
alone whether a round is accepted.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

ALLOWED_VERBS = frozenset({"worker-show", "worker-list"})
FAILED_STATES = frozenset({"failed", "cancelled", "canceled", "stopped", "abandoned", "timed_out"})
SUCCEEDED = "succeeded"
REQUIRED_KEYS = ("dispatchId", "state", "liveness")
ORCA_TIMEOUT = 30
LIST_LIMIT = 100
LIST_PAGES = 5
_WRAPPERS = ("worker", "dispatch", "result")
_LISTS = ("workers", "items", "rows", "results")
_CURSORS = ("nextCursor", "next_cursor", "next")


class OrcaError(ValueError):
    """Orca is absent, answered unexpectedly, or does not know the dispatch."""


@dataclass(frozen=True)
class WorkerRow:
    dispatch_id: str
    state: str
    liveness: str
    agent: str  # empty when Orca no longer reports it (released workers lose their identity)

    @property
    def running(self) -> bool:
        return self.state != SUCCEEDED and self.state not in FAILED_STATES


def orca_command() -> str:
    """The Orca CLI: ``ORCA_CLI_COMMAND``, else ``orca-dev`` when ``ORCA_DEV_REPO_ROOT`` is
    set, else ``orca-ide`` on Linux, else ``orca``."""
    explicit = os.environ.get("ORCA_CLI_COMMAND", "").strip()
    if explicit:
        return explicit
    if os.environ.get("ORCA_DEV_REPO_ROOT", "").strip():
        return "orca-dev"
    return "orca-ide" if sys.platform.startswith("linux") else "orca"


def orca_argv() -> list[str]:
    try:
        return shlex.split(orca_command())
    except ValueError as exc:
        raise OrcaError(f"ORCA_CLI_COMMAND is not a valid command line: {exc}") from exc


def require_orca() -> list[str]:
    """The Orca argv prefix, or an error naming what is missing (no side effects)."""
    argv = orca_argv()
    if not argv or shutil.which(argv[0]) is None:
        raise OrcaError(
            f"Orca CLI '{orca_command()}' was not found on PATH: install Orca or set "
            "ORCA_CLI_COMMAND to its command"
        )
    return argv


@dataclass(frozen=True)
class WorkerStart:
    """What one ``worker-start`` line needs: the spec file, who runs it, where, and its title."""

    spec: str
    agent: str
    model: str
    worktree: str
    title: str


def worker_start_argv(start: WorkerStart) -> list[str]:
    """The line the coordinator runs. Built here, printed, and never executed by the engine."""
    argv = [
        *orca_argv(),
        *("orchestration", "worker-start", "--spec-file", start.spec, "--agent", start.agent),
    ]
    if start.model:
        argv += ["--model", start.model]
    return [*argv, "--worktree", f"path:{start.worktree}", "--task-title", start.title]


def worker_stop_line(dispatch_id: str) -> str:
    return shlex.join([*orca_argv(), "orchestration", "worker-stop", "--dispatch", dispatch_id])


def wait_line() -> str:
    return shlex.join(
        [*orca_argv(), "orchestration", "check", "--wait", "--types", "worker_done"]
        + ["--timeout-ms", "600000"]
    )


def _run(args: list[str]) -> object:
    """One allow-listed Orca call; returns the parsed JSON."""
    if len(args) < 2 or args[0] != "orchestration" or args[1] not in ALLOWED_VERBS:
        raise OrcaError(f"refused: the engine only runs {', '.join(sorted(ALLOWED_VERBS))}")
    argv = [*require_orca(), *args]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=ORCA_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OrcaError(f"{argv[0]} could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr.strip().splitlines() or [str(proc.returncode)])[0]
        raise OrcaError(f"{argv[0]} {args[1]} exited {proc.returncode}: {detail}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise OrcaError(f"{argv[0]} {args[1]} did not print JSON") from exc


def _row(raw: object) -> WorkerRow:
    if isinstance(raw, dict):
        for key in _WRAPPERS:
            if "dispatchId" not in raw and isinstance(raw.get(key), dict):
                raw = raw[key]
                break
    if not isinstance(raw, dict):
        raise OrcaError("Orca answered with something that is not a worker row")
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise OrcaError(f"Orca's worker row lacks {', '.join(missing)} (its output shape changed?)")
    agent = raw.get("agent")
    return WorkerRow(
        str(raw["dispatchId"]),
        str(raw["state"]),
        str(raw["liveness"]),
        agent if isinstance(agent, str) else "",
    )


def _show(dispatch_id: str) -> WorkerRow:
    row = _row(_run(["orchestration", "worker-show", "--dispatch", dispatch_id, "--json"]))
    if row.dispatch_id != dispatch_id:
        raise OrcaError(f"Orca answered for dispatch {row.dispatch_id}, not {dispatch_id}")
    return row


def _page(cursor: str) -> tuple[list[object], str]:
    args = ["orchestration", "worker-list", "--json", "--limit", str(LIST_LIMIT)]
    data = _run([*args, "--cursor", cursor] if cursor else args)
    rows: object = data
    if isinstance(data, dict):
        rows = next((data[key] for key in _LISTS if isinstance(data.get(key), list)), None)
    if not isinstance(rows, list):
        raise OrcaError("Orca's worker list has an unexpected shape")
    following = next((str(data[k]) for k in _CURSORS if isinstance(data, dict) and data.get(k)), "")
    return rows, following


def _listed(dispatch_id: str) -> WorkerRow:
    cursor = ""
    for _ in range(LIST_PAGES):
        rows, cursor = _page(cursor)
        for raw in rows:
            if isinstance(raw, dict) and raw.get("dispatchId") == dispatch_id:
                return _row(raw)
        if not cursor:
            break
    raise OrcaError(f"dispatch {dispatch_id} is not in Orca's worker list")


def worker_status(dispatch_id: str) -> WorkerRow:
    """The worker of ``dispatch_id``: ``worker-show``, else a bounded scan of ``worker-list``."""
    try:
        return _show(dispatch_id)
    except OrcaError as shown:
        try:
            return _listed(dispatch_id)
        except OrcaError as listed:
            raise OrcaError(f"{shown}; {listed}") from listed
