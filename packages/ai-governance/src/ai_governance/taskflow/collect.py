"""``round collect`` and ``round abort``: settle a dispatched round, fail-closed.

Every check runs before the first write, any refusal changes nothing, and a second call that
finds the round already settled reports it (collect) or refuses (abort). The writes happen in
one ``store.mutate``: the checks that guard against a concurrent settle (round still
pending, Orca dispatch id not used by another round) are repeated there against the freshly
loaded task, and the round markdown is written only after they pass.

An accepted collect needs all of: the sealed dispatch record and spec unchanged, the receipt
the worker wrote (round token plus its Orca dispatch id) equal to the id the coordinator
passes, a worker that is not running and whose agent, when Orca still reports it, has the
dispatched provider, a non-blank answer written after dispatch, the taskflow control files
unchanged (see ``control``), and the repositories unchanged since dispatch. When the
coordinator saved Orca's ``worker-start --json`` receipt to ``runs/N/launch.json``, the agent
and model Orca really launched must also be the dispatched ones.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import orca
from .agents import provider
from .control import DispatchError, drift
from .dispatch import read_dispatch, verify_dispatch
from .models import JsonDict, Task, now_iso
from .prompts import parse_changes, parse_verdict
from .repos import guard
from .stamp import changed_paths, head_sha, tree_fingerprint
from .store import TaskStore, atomic_write_text


@dataclass(frozen=True)
class Settled:
    record: JsonDict
    already: bool


@dataclass(frozen=True)
class RoundRef:
    """Which round of which task a collect or abort settles."""

    task_id: str
    number: int


@dataclass(frozen=True)
class _Settlement:
    """What one settle writes: the round record, its markdown, and optional audit evidence."""

    record: JsonDict
    text: str
    extra: JsonDict | None = None


class _Lost(Exception):
    """Another process settled the round between the checks and the write."""

    def __init__(self, record: JsonDict) -> None:
        super().__init__("round already settled")
        self.record = record


def _find(task: Task, number: int) -> JsonDict | None:
    return next((r for r in task.rounds if int(r.get("n", 0)) == number), None)


def _unused(task: Task, number: int, dispatch_id: str) -> None:
    for found in task.rounds:
        if found.get("session") == dispatch_id and int(found.get("n", 0)) != number:
            raise DispatchError(
                f"dispatch {dispatch_id} already settled round {int(found['n']):03d}: "
                "one Orca dispatch settles at most one round"
            )


def _already(record: JsonDict, dispatch_id: str) -> Settled:
    number = int(record["n"])
    if record.get("settlement") == "aborted":
        raise DispatchError(f"round {number:03d} was aborted ({record.get('reason', '')})")
    if record.get("session") != dispatch_id:
        raise DispatchError(
            f"round {number:03d} was already collected with dispatch {record.get('session')}, "
            f"not {dispatch_id}"
        )
    return Settled(record, True)


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def check_receipt(found: JsonDict, dispatch_id: str, number: int) -> None:
    """The receipt the worker wrote must carry this round's token and the id being presented."""
    path = Path(found["receipt"])
    try:
        words = (path.read_text(encoding="utf-8").strip().splitlines() or [""])[0].split()
        fresh = path.stat().st_mtime >= _epoch(found["at"])
    except OSError as exc:
        raise DispatchError(
            f"no dispatch receipt at {path} ({exc.strerror or exc}): the worker of round {number} "
            "did not report that it started; if you are sure it never started, abort with "
            "--never-started (your assertion is recorded)"
        ) from exc
    if len(words) != 4 or words[0] != "ROUND" or words[2] != "DISPATCH":
        raise DispatchError(f"the receipt at {path} is malformed")
    if words[1] != found["nonce"] or not fresh:
        raise DispatchError(f"the receipt at {path} does not belong to round {number}")
    if words[3] != dispatch_id:
        raise DispatchError(
            f"dispatch {dispatch_id} is not the worker of round {number}: its receipt names "
            f"dispatch {words[3]}"
        )


def _worker(dispatch_id: str, number: int, *, settling: bool) -> orca.WorkerRow:
    try:
        row = orca.worker_status(dispatch_id)
    except orca.OrcaError as exc:
        raise DispatchError(
            f"cannot confirm the worker for dispatch {dispatch_id} ({exc}); retry once Orca "
            f"answers. If the worker never started, `round abort --round {number} --reason ... "
            "--never-started` records that you assert it. A worker that did start is not stopped "
            "by aborting"
        ) from exc
    if row.running and settling:
        raise DispatchError(
            f"worker for round {number} is still running (state {row.state}); wait with: "
            f"{orca.wait_line()} then retry"
        )
    if row.running:
        raise DispatchError(
            f"worker for round {number} is still running (state {row.state}); stop it first with: "
            f"{orca.worker_stop_line(dispatch_id)} then abort again"
        )
    return row


def _provider_verified(row: orca.WorkerRow, found: JsonDict) -> bool:
    """True when Orca reports the agent and its provider is the dispatched one; a released
    worker reports none, which is neither a match nor a mismatch."""
    if not row.agent:
        return False
    if provider(row.agent) != found["provider"]:
        raise DispatchError(
            f"dispatch {row.dispatch_id} ran as '{row.agent}', not as the dispatched provider "
            f"'{found['provider']}'"
        )
    return True


@dataclass(frozen=True)
class Launch:
    """What Orca's worker-start receipt says it launched."""

    dispatch_id: str
    agent: str
    model: str


def parse_launch(data: object) -> Launch | None:
    """Orca's ``worker-start --json`` receipt: ``{"ok": true, "result": {"dispatchId", "agent",
    "model", ...}}`` (Orca 1.4). A nested ``result.launch.effective`` is read instead when
    present. None when it is not a successful-start envelope."""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(result, dict):
        return None
    launch = result.get("launch")
    effective = launch.get("effective") if isinstance(launch, dict) else None
    source = effective if isinstance(effective, dict) else result
    return Launch(
        str(result.get("dispatchId") or ""),
        str(source.get("agent") or ""),
        str(source.get("model") or ""),
    )


def _read_launch(found: JsonDict) -> Launch | None:
    path = Path(str(found.get("launch", "")))
    if not found.get("launch") or not path.is_file():
        return None
    try:
        return parse_launch(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def launch_verified(found: JsonDict, dispatch_id: str) -> bool:
    """True only when the saved receipt is this dispatch's and shows the dispatched provider
    and (when one was requested) the dispatched model.

    No receipt, a receipt that is not a successful start, or one without a dispatch id is
    unverified, not a failure (older dispatches have none). A receipt of another dispatch,
    or one naming another provider or model, refuses the collect."""
    launch = _read_launch(found)
    if launch is None or not launch.dispatch_id:
        return False
    _refuse_mismatch(launch, found, dispatch_id)
    wanted = str(found.get("model", ""))
    return bool(launch.agent) and (not wanted or launch.model == wanted)


def _refuse_mismatch(launch: Launch, found: JsonDict, dispatch_id: str) -> None:
    """A receipt of another dispatch, provider or model is evidence against the round."""
    number, wanted = found["n"], str(found.get("model", ""))
    if launch.dispatch_id != dispatch_id:
        raise DispatchError(
            f"the launch receipt of round {number} belongs to dispatch {launch.dispatch_id}, "
            f"not {dispatch_id}"
        )
    if launch.agent and provider(launch.agent) != found["provider"]:
        raise DispatchError(
            f"Orca launched round {number} as '{launch.agent}', not as the dispatched provider "
            f"'{found['provider']}': abort it and dispatch again"
        )
    if wanted and launch.model and launch.model != wanted:
        raise DispatchError(
            f"Orca launched round {number} on model '{launch.model}', not on the dispatched "
            f"'{wanted}' (it fell back?): abort it and dispatch again"
        )


def _used_scratch(found: JsonDict) -> bool:
    path = Path(str(found.get("scratch", "")))
    return bool(found.get("scratch")) and path.is_dir() and any(path.iterdir())


def _read_answer(found: JsonDict, answer_file: Path | None) -> tuple[str, str]:
    path = answer_file or Path(found["answer"])
    try:
        text = path.read_text(encoding="utf-8")
        fresh = path.stat().st_mtime >= _epoch(found["at"])
    except OSError as exc:
        raise DispatchError(f"no answer at {path}") from exc
    if not text.strip() or not fresh:
        raise DispatchError(f"no answer at {path}" + ("" if text.strip() else " (it is blank)"))
    return text, "answer_file" if answer_file else "file"


def _tree_reasons(found: JsonDict) -> list[str]:
    reasons: list[str] = []
    for entry in found["repos"]:
        path = Path(entry["path"])
        seen = (
            guard({"path": str(path)}, lambda p: (head_sha(p), tree_fingerprint(p)))
            if path.is_dir()
            else None
        )
        if seen is None:
            reasons.append(f"bound repo not found: {path}")
        elif seen[0] != entry["head"]:
            reasons.append(f"{path}: HEAD moved")
        elif seen[1] != entry["fingerprint"]:
            reasons.append(f"{path}: {', '.join(changed_paths(path)[:10])}")
    return reasons


def _outcome(found: JsonDict, row: orca.WorkerRow, answer: str) -> tuple[str, str, str]:
    """(state, verdict, reason) of a worker that ended."""
    if row.state != orca.SUCCEEDED:
        return "invalid", "block", f"worker ended as {row.state}"
    if reasons := _tree_reasons(found):
        reason = "reader changed the tree or HEAD moved (kept, not discarded) - " + "; ".join(
            reasons
        )
        return "invalid", "block", reason
    verdict = parse_verdict(answer) if found["role"] in ("validator", "judge") else "info"
    return "valid", verdict, ""


def _render(record: JsonDict, found: JsonDict, answer: str) -> str:
    focus = f" · {record['focus']}" if record.get("focus") else ""
    spec = Path(found["spec"]).read_text(encoding="utf-8")
    check = "provider verified" if record.get("provider_verified") else "provider not verified"
    launch = "launch verified" if record.get("launch_verified") else "launch not verified"
    reason = f": {record['reason']}" if record.get("reason") else ""
    extra = ""
    if record.get("rebuts"):
        extra += (
            "- Cross-examines rounds: " + ", ".join(f"{n:03d}" for n in record["rebuts"]) + "\n"
        )
    if record.get("scratch_used"):
        extra += f"- Scratch evidence: {found['scratch']}\n"
    if record.get("changes"):
        extra += "- Required changes:\n" + "".join(f"  - {c}\n" for c in record["changes"])
    return (
        f"# Round {record['n']:03d} · {record['phase']} · {record['role']}{focus} · "
        f"{record['agent']} {record['model']}\n\n"
        f"- Date: {record['at']}\n- Code stamp: {record['stamp']}\n"
        f"- Command: `{shlex.join(found['command'])}`\n"
        f"- Dispatch: {record['session']} ({check}, {launch})\n"
        f"- Verdict: {record['verdict']} ({record['state']}{reason})\n{extra}\n"
        f"## Request\n\n{spec}\n\n## Answer\n\n{answer}\n"
    )


def _base_record(found: JsonDict) -> JsonDict:
    keys = ("n", "phase", "role", "focus", "agent", "model", "stamp", "file", "provider")
    return {
        **{key: found[key] for key in keys},
        **{"at": now_iso(), "source": "engine", "via": "orca"},
    }


def _write_settled(store: TaskStore, task_id: str, settlement: _Settlement) -> None:
    """Append the record (and ``extra`` evidence) in one mutate, after re-checking under the lock."""
    record, text, extra = settlement.record, settlement.text, settlement.extra
    number, session = int(record["n"]), str(record.get("session", ""))

    def settle(task: Task) -> None:
        if (found := _find(task, number)) is not None:
            raise _Lost(found)
        if session:
            _unused(task, number, session)
        atomic_write_text(Path(record["file"]), text)
        task.rounds.append(record)
        if extra is not None:
            task.evidence.append(extra)

    store.mutate(task_id, settle)


def collect_round(
    store: TaskStore, ref: RoundRef, dispatch_id: str, answer_file: Path | None = None
) -> Settled:
    task_id, number = ref.task_id, ref.number
    task = store.get(task_id)
    read_dispatch(store, task_id, number)
    if (done := _find(task, number)) is not None:
        return _already(done, dispatch_id)
    found = verify_dispatch(store, task_id, number)
    _unused(task, number, dispatch_id)
    row = _worker(dispatch_id, number, settling=True)
    verified = _provider_verified(row, found)
    check_receipt(found, dispatch_id, number)
    failed = row.state != orca.SUCCEEDED
    answer, transport = ("", "none") if failed else _read_answer(found, answer_file)
    if changed := drift(task, found["control"]):
        raise DispatchError(
            "taskflow control files changed since dispatch (" + ", ".join(changed[:6]) + "): "
            "the round was not settled; inspect the store before going on"
        )
    launched = launch_verified(found, dispatch_id)
    state, verdict, reason = _outcome(found, row, answer)
    reviews = found["role"] in ("validator", "judge")
    record = {
        **_base_record(found),
        **{"verdict": verdict, "state": state, "reason": reason, "session": dispatch_id},
        **{"provider_verified": verified, "answer_transport": transport},
        **{"launch_verified": launched, "rebuts": list(found.get("rebuts", []))},
        **{"changes": parse_changes(answer) if reviews else []},
        **{"scratch_used": _used_scratch(found)},
    }
    try:
        _write_settled(store, task_id, _Settlement(record, _render(record, found, answer)))
    except _Lost as lost:
        return _already(lost.record, dispatch_id)
    return Settled(record, False)


def _project_abort_log(store: TaskStore, task_id: str, record: JsonDict) -> bool:
    """The log line of an abort, written once however many times this runs (crash recovery)."""
    number = int(record["n"])
    who = record.get("session") or "none: the operator asserts the worker never started"
    return store.append_log_once(
        task_id,
        f"aborted-round {task_id} {number:03d}",
        f"Round {number:03d} ({record['role']}) aborted: {record['reason']} (worker: {who})",
    )


def _abort_record(found: JsonDict, reason: str, session: str, verified: bool) -> JsonDict:
    return {
        **_base_record(found),
        **{"verdict": "block", "state": "invalid", "settlement": "aborted", "reason": reason},
        **{"session": session, "provider_verified": verified},
        **{"operator_assertion": "" if session else "never-started"},
    }


def _abort_text(record: JsonDict) -> str:
    who = record["session"] or "none (operator asserts it never started)"
    return (
        f"# Round {record['n']:03d} {record['role']}: aborted\n\n{record['reason']}\n\n"
        f"- Dispatch: {who}\n- Date: {record['at']}\n"
    )


def abort_round(store: TaskStore, ref: RoundRef, reason: str, dispatch_id: str | None) -> JsonDict:
    """Settle a pending round as aborted. ``dispatch_id`` None is the operator's assertion that
    no worker started; it is recorded as such and is not evidence."""
    task_id, number = ref.task_id, ref.number
    if not reason.strip():
        raise DispatchError("--reason must say why the round is aborted")
    task = store.get(task_id)
    read_dispatch(store, task_id, number)
    if (done := _find(task, number)) is not None:
        healed = done.get("settlement") == "aborted" and _project_abort_log(store, task_id, done)
        what = "aborted" if done.get("settlement") == "aborted" else "collected"
        raise DispatchError(
            f"round {number:03d} was already {what}; nothing changes"
            + (" (its audit log entry was restored)" if healed else "")
        )
    found = verify_dispatch(store, task_id, number)
    session, verified = "", False
    if dispatch_id is not None:
        _unused(task, number, dispatch_id)
        check_receipt(found, dispatch_id, number)
        row = _worker(dispatch_id, number, settling=False)
        session, verified = dispatch_id, _provider_verified(row, found)
    record = _abort_record(found, reason.strip(), session, verified)
    audit = {
        **{"kind": "aborted-round", "n": number, "task": task_id, "reason": record["reason"]},
        **{"session": session, "assertion": record["operator_assertion"]},
        **{"stamp": record["stamp"], "at": record["at"]},
    }
    try:
        _write_settled(store, task_id, _Settlement(record, _abort_text(record), audit))
    except _Lost as lost:
        raise DispatchError(
            f"round {number:03d} was settled meanwhile ({lost.record['state']})"
        ) from lost
    _project_abort_log(store, task_id, record)
    return record
