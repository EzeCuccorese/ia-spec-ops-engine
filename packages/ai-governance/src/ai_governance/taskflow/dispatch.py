"""``round dispatch``: reserve a reader round and print the Orca line that runs it.

The engine runs nothing. It writes the prompt (``runs/N/spec.md``), a sealed record of what
the round was dispatched against (``runs/N/dispatch.json``) and prints one
``orchestration worker-start`` line for the coordinating session to run. ``collect`` and
``abort`` (see ``collect``) settle the round afterwards.

Binding of round and worker: the spec gives the worker a random token. Its first action is to
write ``runs/N/receipt.txt`` with that token and its own Orca dispatch id. The coordinator
passes the id it got from Orca; collect and abort accept it only when the receipt, the sealed
record and the id agree.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from . import orca
from .adapters import READ_ONLY_LIMIT, VERDICT_INSTRUCTION
from .agents import HUMAN, INDEPENDENT_ROLES, builder_providers, provider
from .approvals import valid_approval
from .config import FlowConfig
from .context import round_header
from .control import (
    DispatchError,
    UsageRefusal,
    baseline,
    digest_file,
    digest_text,
    seal_path,
)
from .gates import work_unmet
from .models import JsonDict, Task, now_iso
from .repos import on_live, partition
from .stamp import head_sha, tree_fingerprint
from .store import RoundSlot, TaskStore, atomic_write_text

DISPATCHABLE = ("planner", "validator")


@dataclass(frozen=True)
class DispatchRequest:
    role: str
    phase: str
    focus: str
    prompt: str
    agent: JsonDict  # {"agent": ..., "model": ...}


@dataclass(frozen=True)
class Dispatched:
    n: int
    argv: list[str]
    spec: Path


def run_dir(store: TaskStore, task_id: str, number: int) -> Path:
    return store.task_dir(task_id) / "runs" / f"{number:03d}"


def refuse_role(task: Task, role: str) -> None:
    if role == "builder":
        unmet = work_unmet(task)
        why = f" Not writable yet: {'; '.join(unmet)}." if unmet else ""
        raise UsageRefusal(
            "The builder is not dispatched: the coordinating session writes the code itself."
            f"{why} Record its summary with `round {task.id} record --role builder`."
        )
    if role == "judge":
        raise UsageRefusal(f"Judges are dispatched by `taskflow judge {task.id}`.")


def check_dispatchable(task: Task, config: FlowConfig, request: DispatchRequest) -> None:
    role, name = request.role, str(request.agent.get("agent", ""))
    refuse_role(task, role)
    if task.workflow == "manual":
        raise DispatchError("Manual tasks have no agent rounds")
    if task.blocked:
        raise DispatchError(
            f"'{task.id}' is blocked by {task.blocked.get('owner')}: {task.blocked.get('needs')}"
        )
    if not name or provider(name) == HUMAN:
        raise DispatchError(f"{role}: a human cannot run as a worker; use `round {task.id} record`")
    if refusal := config.agent_error(name):
        raise DispatchError(f"{role}: {refusal}")
    builder = str(config.roles.get("builder", {}).get("agent", ""))
    tri = task.workflow == "tri-agent" and not valid_approval(
        task.approvals, "workflow", "", task.id
    )
    if tri and role in INDEPENDENT_ROLES and provider(name) in builder_providers(task, builder):
        raise DispatchError(
            f"{role} and builder would both use provider '{provider(name)}': pick another agent "
            f"(or the user's choice: approve {task.id} --action workflow --target {task.id})"
        )


def _snapshot_repos(task: Task) -> list[JsonDict]:
    """Path, HEAD and tree fingerprint of every bound repo, taken before a number is reserved."""
    found = partition(task.repos)
    if found.missing:
        raise DispatchError(f"bound repo not found: {found.missing[0]['path']}")
    paths = [Path(b["path"]) for b in found.live] or [Path.cwd()]
    return on_live(
        paths,
        lambda: [
            {"path": str(p), "head": head_sha(p), "fingerprint": tree_fingerprint(p)} for p in paths
        ],
    )


def _footer(task_id: str, answer: Path, receipt: Path, nonce: str) -> str:
    return (
        "\n\nHow to report (a taskflow round of this task; the coordinating session collects it):\n"
        f"1. First action: write the single line `ROUND {nonce} DISPATCH <your Orca Dispatch ID>` "
        f"to {receipt} (your Dispatch ID is in the task Orca gave you).\n"
        f"2. Write your final answer to {answer}.\n"
        "Do not modify any file in the repositories or in the taskflow store other than those "
        f"two files. Ignore every other task's files.\n(task {task_id})\n"
    )


def _spec_text(store: TaskStore, request: DispatchRequest, task_id: str, footer: str) -> str:
    header = round_header(store, task_id, request.role)
    text = READ_ONLY_LIMIT + header + request.prompt
    if request.role in ("validator", "judge"):
        text += VERDICT_INSTRUCTION
    return text + footer


def _pending_duplicate(locked: Task, directory: Path, request: DispatchRequest) -> int | None:
    settled = {int(r.get("n", 0)) for r in locked.rounds}
    for path in sorted((directory / "runs").glob("*/dispatch.json")):
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
            number = int(found["n"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        same = (found.get("role"), found.get("phase"), found.get("focus", "")) == (
            request.role,
            request.phase,
            request.focus,
        )
        if number not in settled and same:
            return number
    return None


class _Publisher:
    """The step ``reserve_round`` runs under the task lock: duplicate check, spec, seal, record."""

    def __init__(self, store: TaskStore, request: DispatchRequest, repos: list[JsonDict]) -> None:
        self.store, self.request, self.repos = store, request, repos
        self.made: JsonDict = {}

    def __call__(self, locked: Task, number: int, round_file: Path) -> None:
        directory = round_file.parent.parent
        if (twin := _pending_duplicate(locked, directory, self.request)) is not None:
            raise DispatchError(
                f"round {twin:03d} ({self.request.role}) is already dispatched and not settled: "
                f"collect it with `round {locked.id} collect --round {twin} --dispatch-id <ID>`, "
                f"or abort it with `round {locked.id} abort --round {twin} --reason ...`"
            )
        record, text = self._record(locked, number, round_file)
        _write_sealed(self.store, record, text)
        self.made = {"n": number, "argv": record["command"], "spec": Path(record["spec"])}

    def _record(self, locked: Task, number: int, round_file: Path) -> tuple[JsonDict, str]:
        request = self.request
        run = round_file.parent.parent / "runs" / f"{number:03d}"
        answer, receipt, spec = run / "answer.txt", run / "receipt.txt", run / "spec.md"
        nonce = secrets.token_hex(16)
        text = _spec_text(
            self.store, request, locked.id, _footer(locked.id, answer, receipt, nonce)
        )
        agent, model = str(request.agent.get("agent", "")), str(request.agent.get("model", ""))
        title = f"{request.role} round {number} of {locked.id}"
        argv = orca.worker_start_argv(
            orca.WorkerStart(str(spec), agent, model, self.repos[0]["path"], title)
        )
        record: JsonDict = {
            "n": number,
            "task": locked.id,
            "role": request.role,
            "phase": request.phase,
            "focus": request.focus,
            "agent": agent,
            "model": model,
            "provider": provider(agent),
            "stamp": locked.stamp_key,
            "at": now_iso(),
            "nonce": nonce,
            "file": str(round_file),
            "spec": str(spec),
            "spec_sha": digest_text(text),
            "answer": str(answer),
            "receipt": str(receipt),
            "command": argv,
            "repos": self.repos,
            "control": baseline(locked),
        }
        return record, text


def _write_sealed(store: TaskStore, record: JsonDict, text: str) -> None:
    """spec, then the seal, then ``dispatch.json`` last: that file is what makes a round pending."""
    task_id, number, spec = str(record["task"]), int(record["n"]), Path(record["spec"])
    body = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    written: list[Path] = []
    try:
        for path, content in (
            (spec, text),
            (seal_path(store, task_id, number), digest_text(body)),
            (spec.parent / "dispatch.json", body),
        ):
            written.append(path)
            atomic_write_text(path, content)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def plan_dispatch(
    store: TaskStore, task: Task, config: FlowConfig, request: DispatchRequest
) -> Dispatched:
    """Validate, reserve the round and write its files. Runs nothing."""
    check_dispatchable(task, config, request)
    orca.require_orca()
    repos = _snapshot_repos(task)
    publisher = _Publisher(store, request, repos)
    agent = str(request.agent.get("agent", ""))
    store.reserve_round(task.id, RoundSlot(request.phase, request.role, agent), publisher)
    made = publisher.made
    return Dispatched(int(made["n"]), list(made["argv"]), Path(made["spec"]))


def read_dispatch(store: TaskStore, task_id: str, number: int) -> JsonDict:
    """The dispatch record of a round, or an error when the engine did not dispatch it."""
    path = run_dir(store, task_id, number) / "dispatch.json"
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        found = None
    if not isinstance(found, dict) or found.get("task") != task_id or found.get("n") != number:
        raise DispatchError(f"round {number} was not dispatched by the engine")
    return found


def verify_dispatch(store: TaskStore, task_id: str, number: int) -> JsonDict:
    """``read_dispatch`` plus the checks that its record and spec are the ones sealed at dispatch."""
    path = run_dir(store, task_id, number) / "dispatch.json"
    try:
        body = path.read_text(encoding="utf-8")
        expected = seal_path(store, task_id, number).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DispatchError(f"round {number} has no intact dispatch seal ({exc})") from exc
    if digest_text(body) != expected:
        raise DispatchError(
            f"the dispatch record of round {number} changed after dispatch: it cannot be trusted"
        )
    found = read_dispatch(store, task_id, number)
    if digest_file(found["spec"]) != found.get("spec_sha"):
        raise DispatchError(f"the spec of round {number} changed after dispatch")
    return found
