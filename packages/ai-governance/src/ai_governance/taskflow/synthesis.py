"""Deterministic debate synthesis: parse structured round answers into ``synthesis.md``.

Reads only ``answer_section(...)`` of settled round markdown files (never raw
``runs/N/answer.txt``) and emits no timestamps, so repeated runs produce
byte-identical output.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .agents import read_regular_text
from .control import DispatchError, digest_text
from .debate import _debate_lock, dropped_focuses, require_debate, save_debate
from .handoff import scrub
from .models import JsonDict, Task
from .prompts import (
    ChangedLine,
    RebutLine,
    answer_section,
    parse_changed,
    parse_position,
    parse_rebuts,
)
from .store import TaskStore, atomic_write_text

SYNTHESIS_FILE = "synthesis.md"
VALID_OUTCOMES = ("refuted", "agreed", "open")
STEP_MAX_CHARS = 200


@dataclass(frozen=True)
class _SeatSummary:
    focus: str
    agent: str
    model: str
    thesis_round: int
    cross_round: int | None
    dropped: bool
    cross_state: str
    thesis_position: str
    cross_position: str


@dataclass(frozen=True)
class _RebutEntry:
    author: str
    target_round: int
    target_focus: str
    claim: str
    evidence: str
    outcome: str


@dataclass(frozen=True)
class _ChangedEntry:
    author: str
    target_round: int
    target_focus: str
    change: str


@dataclass(frozen=True)
class _MatrixData:
    counts: dict[tuple[str, str], list[int]]
    no_structured: frozenset[str]


@dataclass
class _Accumulator:
    seats: list[_SeatSummary] = field(default_factory=list)
    rebuts: list[_RebutEntry] = field(default_factory=list)
    changes: list[_ChangedEntry] = field(default_factory=list)
    counts: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    no_structured: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)


def _pending_cross(
    seats: Sequence[JsonDict], dropped: set[str], rounds_by_n: dict[int, JsonDict]
) -> list[int]:
    pending: list[int] = []
    for seat in seats:
        if str(seat["focus"]) in dropped or seat.get("cross_round") is None:
            continue
        number = int(seat["cross_round"])
        if number not in rounds_by_n:
            pending.append(number)
    return pending


def _read_valid_answer(record: JsonDict | None) -> str | None:
    if record is None or record.get("state") != "valid":
        return None
    raw_file = record.get("file")
    if not raw_file:
        return None
    try:
        return answer_section(read_regular_text(Path(str(raw_file))))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _valid_targets(
    seats: Sequence[JsonDict], dropped: set[str], rounds_by_n: dict[int, JsonDict]
) -> dict[int, str]:
    targets: dict[int, str] = {}
    for seat in seats:
        focus = str(seat["focus"])
        thesis_n = int(seat["thesis_round"])
        rec = rounds_by_n.get(thesis_n)
        if focus not in dropped and rec is not None and rec.get("state") == "valid":
            targets[thesis_n] = focus
    return targets


def _drop_messages(state: JsonDict) -> list[str]:
    messages: list[str] = []
    for item in state.get("dropped", []):
        if isinstance(item, dict):
            msg = item.get("message") or f"dropped seat '{item.get('focus', '?')}'"
            messages.append(str(msg))
        elif isinstance(item, str) and item.strip():
            messages.append(item.strip())
    return messages


def _format_rebut(line: RebutLine) -> str:
    return f"REBUT: round {line.target:03d} | {line.claim} | {line.evidence} | {line.outcome}"


def _classify_rebuts(
    author: tuple[str, int, int],
    parsed: tuple[list[RebutLine], list[str]],
    targets: dict[int, str],
    acc: _Accumulator,
) -> None:
    focus, thesis_n, cross_n = author
    lines, malformed = parsed
    valid_count = 0
    for line in lines:
        outcome = line.outcome.strip().lower()
        target_focus = targets.get(line.target)
        if target_focus is None or line.target == thesis_n or outcome not in VALID_OUTCOMES:
            why = (
                "self-rebuttal" if line.target == thesis_n else f"invalid target {line.target:03d}"
            )
            acc.missing.append(f"{focus} (round {cross_n:03d}): {why} -> `{_format_rebut(line)}`")
            continue
        valid_count += 1
        acc.rebuts.append(
            _RebutEntry(focus, line.target, target_focus, line.claim, line.evidence, outcome)
        )
        bucket = acc.counts.setdefault((focus, target_focus), [0, 0, 0])
        bucket[VALID_OUTCOMES.index(outcome)] += 1
    for bad in malformed:
        acc.missing.append(f'{focus} (round {cross_n:03d}): malformed REBUT line "{bad}"')
    if not lines and not malformed:
        acc.no_structured.add(focus)


def _format_changed(line: ChangedLine) -> str:
    return f"CHANGED: {line.change} | round {line.target:03d}"


def _record_changes(
    author: tuple[str, int, int],
    parsed: tuple[list[ChangedLine], list[str]],
    targets: dict[int, str],
    acc: _Accumulator,
) -> None:
    focus, thesis_n, cross_n = author
    lines, malformed = parsed
    for line in lines:
        if line.target == thesis_n:
            acc.missing.append(
                f"{focus} (round {cross_n:03d}): self-changed -> `{_format_changed(line)}`"
            )
            continue
        if line.target not in targets:
            acc.missing.append(
                f"{focus} (round {cross_n:03d}): CHANGED references invalid target {line.target:03d}"
            )
            continue
        acc.changes.append(_ChangedEntry(focus, line.target, targets[line.target], line.change))
    for bad in malformed:
        acc.missing.append(f'{focus} (round {cross_n:03d}): malformed CHANGED line "{bad}"')


def _thesis_position(
    focus: str, thesis_n: int, rounds_by_n: dict[int, JsonDict], acc: _Accumulator
) -> str:
    rec = rounds_by_n.get(thesis_n)
    if rec is None or rec.get("state") != "valid":
        return ""
    answer = _read_valid_answer(rec)
    if answer is None:
        acc.missing.append(f"Unreadable thesis round file for '{focus}' (round {thesis_n:03d})")
        return ""
    return parse_position(answer, unwrapped=True)


def _cross_details(
    seat: JsonDict,
    dropped: set[str],
    lookup: tuple[dict[int, JsonDict], dict[int, str]],
    acc: _Accumulator,
) -> tuple[str, str]:
    rounds_by_n, targets = lookup
    focus = str(seat["focus"])
    if focus in dropped or seat.get("cross_round") is None:
        return "dropped" if focus in dropped else "pending", ""
    cross_n = int(seat["cross_round"])
    rec = rounds_by_n.get(cross_n)
    if rec is None:
        acc.missing.append(f"Pending cross round {cross_n:03d} for seat '{focus}'")
        return "pending", ""
    if rec.get("state") != "valid":
        reason = str(rec.get("reason") or rec.get("state") or "invalid")
        acc.missing.append(f"Invalid cross round {cross_n:03d} for seat '{focus}': {reason}")
        return "invalid", ""
    answer = _read_valid_answer(rec)
    if answer is None:
        acc.missing.append(f"Unreadable cross round file for '{focus}' (round {cross_n:03d})")
        return "invalid", ""
    thesis_n = int(seat["thesis_round"])
    author = (focus, thesis_n, cross_n)
    _classify_rebuts(author, parse_rebuts(answer, unwrapped=True), targets, acc)
    _record_changes(author, parse_changed(answer, unwrapped=True), targets, acc)
    return "valid", parse_position(answer, unwrapped=True)


def _collect_data(state: JsonDict, task: Task) -> _Accumulator:
    seats = list(state.get("seats", []))
    dropped = dropped_focuses(state)
    rounds_by_n = {int(r.get("n", 0)): r for r in task.rounds}
    targets = _valid_targets(seats, dropped, rounds_by_n)
    acc = _Accumulator(missing=_drop_messages(state))
    for seat in seats:
        focus = str(seat["focus"])
        thesis_n = int(seat["thesis_round"])
        cross_raw = seat.get("cross_round")
        cross_n = int(cross_raw) if cross_raw is not None else None
        thesis_pos = _thesis_position(focus, thesis_n, rounds_by_n, acc)
        cross_state, cross_pos = _cross_details(seat, dropped, (rounds_by_n, targets), acc)
        acc.seats.append(
            _SeatSummary(
                focus=focus,
                agent=str(seat["agent"]),
                model=str(seat.get("model", "")),
                thesis_round=thesis_n,
                cross_round=cross_n,
                dropped=focus in dropped,
                cross_state=cross_state,
                thesis_position=thesis_pos,
                cross_position=cross_pos,
            )
        )
    return acc


def _esc_cell(text: str) -> str:
    return " ".join(scrub(text).split()).replace("|", "\\|")


def _render_topic_seats(preview: Sequence[str], seats: Sequence[_SeatSummary]) -> list[str]:
    lines = ["## Topic & Seats", ""]
    lines.extend(f"> {scrub(line)}" for line in preview)
    if preview:
        lines.append("")
    lines += [
        "| Focus | Agent | Model | Thesis Round | Cross Round |",
        "|---|---|---|---|---|",
    ]
    for seat in seats:
        if seat.cross_round is not None:
            cross_col = f"{seat.cross_round:03d}"
        else:
            cross_col = "dropped" if seat.dropped else "-"
        model_col = _esc_cell(seat.model) or "-"
        lines.append(
            f"| {_esc_cell(seat.focus)} | {_esc_cell(seat.agent)} | {model_col} | "
            f"{seat.thesis_round:03d} | {cross_col} |"
        )
    return lines


def _cell_text(author: _SeatSummary, target: _SeatSummary, matrix: _MatrixData) -> str:
    if author.focus == target.focus:
        return "—"
    if author.dropped:
        return "dropped"
    if author.cross_state == "pending":
        return "pending"
    if author.cross_state == "invalid":
        return "invalid"
    if author.focus in matrix.no_structured:
        return "no structured lines"
    if target.dropped:
        return "dropped"
    r, a, o = matrix.counts.get((author.focus, target.focus), [0, 0, 0])
    return f"{r} / {a} / {o}"


def _render_matrix(seats: Sequence[_SeatSummary], matrix: _MatrixData) -> list[str]:
    headers = ["Author \\ Target", *(_esc_cell(s.focus) for s in seats)]
    sep = "|".join("---" for _ in headers)
    lines = [
        "## Cross-Examination Matrix",
        "",
        "| " + " | ".join(headers) + " |",
        f"|{sep}|",
    ]
    for author in seats:
        cells = [_cell_text(author, target, matrix) for target in seats]
        lines.append("| " + " | ".join([_esc_cell(author.focus), *cells]) + " |")
    return lines


def _render_rebut_section(heading: str, entries: Sequence[_RebutEntry]) -> list[str]:
    lines = [f"## {heading}", ""]
    if not entries:
        lines.append("(none)")
        return lines
    for entry in entries:
        claim = scrub(" ".join(entry.claim.split()))
        evidence = scrub(" ".join(entry.evidence.split()))
        lines.append(
            f"- **{entry.author}** -> **{entry.target_focus}** "
            f"(round {entry.target_round:03d}): {claim} — *evidence:* {evidence}"
        )
    return lines


def _render_position_changes(
    seats: Sequence[_SeatSummary], changes: Sequence[_ChangedEntry]
) -> list[str]:
    lines = ["## Position Changes", ""]
    for change in changes:
        target = (
            f"{change.target_focus} (round {change.target_round:03d})"
            if change.target_focus
            else f"round {change.target_round:03d}"
        )
        lines.append(
            f"- **{change.author}** (vs {target}): {scrub(' '.join(change.change.split()))}"
        )
    if changes:
        lines.append("")
    for seat in seats:
        thesis_pos = scrub(" ".join(seat.thesis_position.split())) or "(none)"
        cross_pos = scrub(" ".join(seat.cross_position.split())) or "(none)"
        lines.append(f"- **{seat.focus}**: thesis: {thesis_pos} | cross: {cross_pos}")
    return lines


def _render_missing(missing: Sequence[str]) -> list[str]:
    lines = ["## Missing", ""]
    if not missing:
        lines.append("(none)")
        return lines
    lines.extend(f"- {scrub(item)}" for item in missing)
    return lines


def _render_synthesis(task_id: str, preview: Sequence[str], acc: _Accumulator) -> str:
    matrix = _MatrixData(acc.counts, frozenset(acc.no_structured))
    refutations = [r for r in acc.rebuts if r.outcome == "refuted"]
    open_points = [r for r in acc.rebuts if r.outcome == "open"]
    sections = [
        [f"# Debate Synthesis: {task_id}"],
        _render_topic_seats(preview, acc.seats),
        _render_matrix(acc.seats, matrix),
        _render_rebut_section("Refutations", refutations),
        _render_position_changes(acc.seats, acc.changes),
        _render_rebut_section("Open Points", open_points),
        _render_missing(acc.missing),
    ]
    blocks = ["\n".join(section) for section in sections]
    return "\n\n".join(blocks) + "\n"


def _step_text(claim: str, debate_id: int = 1) -> str:
    clean = " ".join(scrub(claim).split())
    prefix = "[debate]" if debate_id == 1 else f"[debate #{debate_id}]"
    text = f"{prefix} {clean}"
    if len(text) <= STEP_MAX_CHARS:
        return text
    suffix = f" [{digest_text(clean)[:6]}]..."
    return text[: STEP_MAX_CHARS - len(suffix)].rstrip() + suffix


def _pending_open_steps(
    debate_id: int, open_entries: Sequence[_RebutEntry], recorded: Sequence[str]
) -> tuple[list[str], list[str]]:
    seen = set(recorded)
    new_keys: list[str] = []
    new_texts: list[str] = []
    for entry in open_entries:
        key = f"{debate_id}:{entry.author}:{entry.target_round}:{entry.claim}"
        if key in seen:
            continue
        seen.add(key)
        new_keys.append(key)
        new_texts.append(_step_text(entry.claim, debate_id))
    return new_keys, new_texts


def _record_open_steps(
    store: TaskStore, task_id: str, state: JsonDict, open_entries: Sequence[_RebutEntry]
) -> list[str]:
    debate_id = int(state.get("debate_id", 1))
    recorded = [str(k) for k in state.get("recorded_open_keys", [])]
    new_keys, new_texts = _pending_open_steps(debate_id, open_entries, recorded)
    if not new_keys:
        return recorded

    def add_steps(task: Task) -> None:
        existing = {str(step.get("text", "")) for step in task.steps}
        for text in new_texts:
            if text not in existing:
                task.steps.append({"text": text, "done": False})
                existing.add(text)

    store.mutate(task_id, add_steps)
    return [*recorded, *new_keys]


def _load_closable(store: TaskStore, task_id: str, partial: bool) -> tuple[JsonDict, Task]:
    state = require_debate(store, task_id)
    if state.get("status") not in ("open", "closed"):
        raise DispatchError(
            f"debate for '{task_id}' has unsupported status '{state.get('status')}'"
        )
    seats = list(state.get("seats", []))
    if not seats or all(seat.get("cross_round") is None for seat in seats):
        raise DispatchError(
            f"cannot close debate for '{task_id}': cross-examination has not been dispatched"
        )
    task = store.get(task_id)
    rounds_by_n = {int(r.get("n", 0)): r for r in task.rounds}
    if (pending := _pending_cross(seats, dropped_focuses(state), rounds_by_n)) and not partial:
        joined = ", ".join(f"{n:03d}" for n in pending)
        raise DispatchError(
            f"cross round(s) still pending: {joined}; collect them or pass --partial"
        )
    return state, task


def _close_debate_locked(store: TaskStore, task_id: str, *, partial: bool) -> Path:
    state, task = _load_closable(store, task_id, partial)
    acc = _collect_data(state, task)
    preview = [str(line) for line in state.get("topic_preview", [])]
    out_path = store.task_dir(task_id) / SYNTHESIS_FILE
    atomic_write_text(out_path, _render_synthesis(task_id, preview, acc))
    open_entries = [r for r in acc.rebuts if r.outcome == "open"]
    updated = json.loads(json.dumps(state))
    updated["recorded_open_keys"] = _record_open_steps(store, task_id, state, open_entries)
    updated["status"] = "closed"
    save_debate(store, task_id, updated)
    return out_path


def close_debate(store: TaskStore, task_id: str, *, partial: bool = False) -> Path:
    """Parse collected debate rounds, write ``synthesis.md`` and record open points as steps."""
    with _debate_lock(store, task_id):
        return _close_debate_locked(store, task_id, partial=partial)
