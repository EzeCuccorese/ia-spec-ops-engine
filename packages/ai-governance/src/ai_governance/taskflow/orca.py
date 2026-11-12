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
from dataclasses import dataclass, replace

ALLOWED_VERBS = frozenset({"worker-show", "worker-list"})
# Anything else is finished: an unknown state settles as a failure instead of waiting forever.
RUNNING_STATES = frozenset({"pending", "dispatched", "starting", "ready", "running", "stopping"})
SUCCEEDED = "succeeded"
REQUIRED_KEYS = ("dispatchId", "state", "liveness")
ORCA_TIMEOUT = 30
LIST_LIMIT = 100
LIST_PAGES = 5


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
        return self.state in RUNNING_STATES


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


def orca_problem() -> str | None:
    """Why the Orca CLI cannot be used (not on PATH, bad command line), or None. No side effects."""
    try:
        argv = orca_argv()
    except OrcaError as exc:
        return str(exc)
    if not argv or shutil.which(argv[0]) is None:
        return (
            f"Orca CLI '{orca_command()}' was not found on PATH: install Orca or set "
            "ORCA_CLI_COMMAND to its command"
        )
    return None


def require_orca() -> list[str]:
    """The Orca argv prefix, or an error naming what is missing (no side effects)."""
    problem = orca_problem()
    if problem:
        raise OrcaError(problem)
    return orca_argv()


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
    # --json: the receipt names the agent and model Orca really launched (checked at collect)
    return [*argv, "--worktree", f"path:{start.worktree}", "--task-title", start.title, "--json"]


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


def _result(data: object, verb: str) -> dict[str, object]:
    """The ``result`` of Orca's ``{"ok": true, "result": {...}}`` envelope; anything else fails."""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(result, dict):
        raise OrcaError(f"Orca's {verb} answer is not an {{ok, result}} envelope (shape changed?)")
    return result


def _row(raw: object) -> WorkerRow:
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
    args = ["orchestration", "worker-show", "--dispatch", dispatch_id, "--json"]
    row = _row(_result(_run(args), "worker-show"))
    if row.dispatch_id != dispatch_id:
        raise OrcaError(f"Orca answered for dispatch {row.dispatch_id}, not {dispatch_id}")
    return row


def _page(cursor: str) -> tuple[list[object], str]:
    """One page of ``result.workers`` and the opaque ``result.nextCursor`` ("" on the last)."""
    args = ["orchestration", "worker-list", "--json", "--limit", str(LIST_LIMIT)]
    result = _result(_run([*args, "--cursor", cursor] if cursor else args), "worker-list")
    rows, following = result.get("workers"), result.get("nextCursor")
    if not isinstance(rows, list) or not (following is None or isinstance(following, str)):
        raise OrcaError("Orca's worker list has an unexpected shape (no result.workers list)")
    return rows, following or ""


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


def _with_listed_agent(row: WorkerRow) -> WorkerRow:
    """``worker-show`` has no ``agent``; the list row of the same dispatch may (read-only)."""
    try:
        listed = _listed(row.dispatch_id)
    except OrcaError:
        return row  # the provider stays unverified; the rest of the answer is still valid
    return replace(row, agent=listed.agent) if listed.agent else row


def worker_status(dispatch_id: str) -> WorkerRow:
    """The worker of ``dispatch_id``: ``worker-show`` (plus the provider from ``worker-list``
    when show has none), else a bounded scan of ``worker-list``."""
    try:
        row = _show(dispatch_id)
    except OrcaError as shown:
        try:
            return _listed(dispatch_id)
        except OrcaError as listed:
            raise OrcaError(f"{shown}; {listed}") from listed
    return row if row.agent else _with_listed_agent(row)
