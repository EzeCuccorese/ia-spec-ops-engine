"""``review close``: turn the settled reviewer and judge rounds into one summary for the owner.

Per pull request the summary lists what the judge confirmed, what needs the owner's decision,
what the judge rejected, how the open review threads were triaged, and whether anything was
written to the pull request while the review ran. It publishes nothing: the owner reads it
and decides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .control import DispatchError
from .debate import _debate_lock as _state_lock
from .handoff import scrub
from .models import JsonDict, Task
from .prompts import parse_position
from .review import require_review, save_review, snapshot_of
from .review_format import (
    Finding,
    ThreadTriage,
    Verdict,
    checked_verdicts,
    parse_findings,
    parse_threads,
    parse_verdicts,
)
from .review_source import PullSnapshot, activity_since, current_head
from .store import TaskStore, atomic_write_text
from .synthesis import _read_valid_answer

SUMMARY_FILE = "summary.md"
BLOCKING_SEVERITIES = ("blocker", "major")
NO_VERDICT = Verdict(0, "needs-human", "", 0, "", "the judge gave no verdict for this finding")


@dataclass(frozen=True)
class Judged:
    finding: Finding
    verdict: Verdict


@dataclass
class PullReport:
    """Everything the summary says about one pull request."""

    snapshot: PullSnapshot
    reviewer: str
    judge: str
    judged: list[Judged] = field(default_factory=list)
    threads: list[ThreadTriage] = field(default_factory=list)
    positions: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    head_now: str = ""
    activity: list[str] = field(default_factory=list)

    def of(self, outcome: str) -> list[Judged]:
        return [item for item in self.judged if item.verdict.outcome == outcome]

    @property
    def action(self) -> str:
        """The engine's reading of the verdicts; the owner decides."""
        if any(j.finding.severity in BLOCKING_SEVERITIES for j in self.of("confirmed")):
            return "request changes (a confirmed blocker or major finding)"
        if self.problems or self.of("needs-human"):
            return "your decision is needed before any action"
        if self.of("confirmed"):
            return "comment (only minor findings confirmed)"
        return "approve (no finding confirmed)"


def _round_record(task: Task, slot: object) -> JsonDict | None:
    if not isinstance(slot, dict):
        return None
    number = int(slot["round"])
    return next((r for r in task.rounds if int(r.get("n", 0)) == number), None)


def _pending(task: Task, entries: Sequence[JsonDict]) -> list[str]:
    """Pull requests whose reviewer or judge round is not settled yet."""
    waiting: list[str] = []
    for entry in entries:
        for role in ("reviewer", "judge"):
            slot = entry.get(role)
            if slot is None and role == "judge":
                waiting.append(f"{entry['key']} (judge not dispatched)")
            elif isinstance(slot, dict) and _round_record(task, slot) is None:
                waiting.append(f"{entry['key']} ({role} round {int(slot['round']):03d})")
    return waiting


def _malformed(report: PullReport, who: str, lines: Sequence[str]) -> None:
    report.problems += [f"{who} wrote a line the engine could not read: {line}" for line in lines]


def _judge_into(report: PullReport, findings: Sequence[Finding], answer: str | None) -> None:
    """Pair every finding with its verdict; a finding with no verdict needs the owner."""
    if answer is None:
        report.problems.append("no valid judge round: every finding is unverified")
        report.judged = [Judged(finding, NO_VERDICT) for finding in findings]
        return
    verdicts = parse_verdicts(answer)
    threads = parse_threads(answer)
    _malformed(report, "the judge", [*verdicts.malformed, *threads.malformed])
    by_number = {
        verdict.number: verdict
        for verdict in checked_verdicts(report.snapshot.source, verdicts.items)
    }
    known = {finding.number for finding in findings}
    report.judged = [Judged(f, by_number.get(f.number, NO_VERDICT)) for f in findings]
    report.problems += [
        f"the judge gave a verdict for finding {number}, which the reviewer did not write"
        for number in sorted(set(by_number) - known)
    ]
    report.threads = list(threads.items)
    report.positions["judge"] = parse_position(answer, unwrapped=True)


def _check_github(report: PullReport, state: JsonDict) -> None:
    """Whether the pull request moved or was written to while the review ran. A failed check
    is reported as unknown, never as clean."""
    snapshot = report.snapshot
    try:
        report.head_now = current_head(snapshot.ref)
        report.activity = activity_since(
            snapshot.ref, str(state.get("viewer", "")), str(state["opened_at"]), snapshot.is_draft
        )
    except DispatchError as exc:
        report.problems.append(f"could not check the pull request on GitHub: {exc}")


def read_rounds(task: Task, entry: JsonDict) -> PullReport:
    """What the settled reviewer and judge rounds of one pull request say (no GitHub call)."""
    reviewer_slot, judge_slot = entry.get("reviewer") or {}, entry.get("judge") or {}
    report = PullReport(
        snapshot=snapshot_of(entry),
        reviewer=f"{reviewer_slot.get('agent', '?')} (round {int(reviewer_slot.get('round', 0)):03d})",
        judge=f"{judge_slot.get('agent', '?')} (round {int(judge_slot.get('round', 0)):03d})"
        if judge_slot
        else "none",
    )
    review = _read_valid_answer(_round_record(task, entry.get("reviewer")))
    if review is None:
        report.problems.append("no valid reviewer round: this pull request was not reviewed")
    else:
        findings = parse_findings(review)
        _malformed(report, "the reviewer", findings.malformed)
        report.positions["reviewer"] = parse_position(review, unwrapped=True)
        judge_answer = _read_valid_answer(_round_record(task, entry.get("judge")))
        _judge_into(report, findings.items, judge_answer)
    return report


def _pull_report(task: Task, entry: JsonDict, state: JsonDict) -> PullReport:
    report = read_rounds(task, entry)
    _check_github(report, state)
    return report


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _where(finding: Finding) -> str:
    return f"`{finding.path}:{finding.line}`"


def _finding_table(title: str, items: Sequence[Judged]) -> list[str]:
    if not items:
        return []
    lines = [f"### {title} ({len(items)})", ""]
    lines += ["| # | severity | kind | where | claim | judge |", "|---|---|---|---|---|---|"]
    for item in items:
        finding, verdict = item.finding, item.verdict
        note = f" ({verdict.note})" if verdict.note else ""
        lines.append(
            f"| {finding.number} | {finding.severity} | {finding.kind} | {_where(finding)} | "
            f"{_cell(finding.claim)} | {_cell(verdict.reason)}{note} |"
        )
    return [*lines, ""]


def _thread_lines(threads: Sequence[ThreadTriage]) -> list[str]:
    if not threads:
        return []
    lines = [f"### Open review threads ({len(threads)})", ""]
    lines += [f"- `{t.thread}` **{t.action}**: {_cell(t.reason)}" for t in threads]
    return [*lines, ""]


def _head_line(report: PullReport) -> str:
    snapshot = report.snapshot
    if not report.head_now:
        return f"- Reviewed commit: `{snapshot.head_sha[:10]}` (current commit unknown)"
    if report.head_now != snapshot.head_sha:
        return (
            f"- Reviewed commit: `{snapshot.head_sha[:10]}`. **The pull request moved to "
            f"`{report.head_now[:10]}` since: these findings may be stale.**"
        )
    return f"- Reviewed commit: `{snapshot.head_sha[:10]}` (still the current one)"


def _activity_line(report: PullReport, viewer: str) -> str:
    if report.activity:
        return (
            f"- **Written to the pull request while the review ran: {'; '.join(report.activity)}.** "
            "A review round must write nothing: check these were yours."
        )
    return f"- Nothing was written to the pull request by {viewer or 'your account'} during the review."


def _render_pull(report: PullReport, viewer: str) -> list[str]:
    ref = report.snapshot.ref
    lines = [f"## {ref.slug}#{ref.number}: {report.snapshot.title}", "", f"- {ref.url}"]
    lines += [_head_line(report), f"- Reviewer: {report.reviewer}. Judge: {report.judge}."]
    lines.append(f"- Reading of the verdicts: **{report.action}**")
    lines += [f"- Position of the {who}: {text}" for who, text in report.positions.items() if text]
    lines += [_activity_line(report, viewer), ""]
    lines += _finding_table("Confirmed by the judge", report.of("confirmed"))
    lines += _finding_table("Needs your decision", report.of("needs-human"))
    lines += _finding_table("Rejected by the judge", report.of("rejected"))
    lines += _thread_lines(report.threads)
    if report.problems:
        lines += ["### Problems reading this review", ""]
        lines += [f"- {problem}" for problem in report.problems] + [""]
    return lines


def render_summary(task_id: str, state: JsonDict, reports: Sequence[PullReport]) -> str:
    lines = [
        f"# Review {int(state['review_id'])} of {task_id}",
        "",
        "Nothing was published. Each finding was written by one agent and checked against the "
        "code by an agent of another provider. A confirmed finding quotes a line that exists "
        "in the reviewed commit; that proves the text is there, not that the claim follows.",
        "",
    ]
    viewer = str(state.get("viewer", ""))
    for report in reports:
        lines += _render_pull(report, viewer)
    return scrub("\n".join(lines).rstrip() + "\n")


def _close_locked(store: TaskStore, task_id: str, *, partial: bool) -> Path:
    state = require_review(store, task_id)
    if state.get("status") != "open":
        raise DispatchError(f"review for '{task_id}' is {state.get('status')}, not open")
    task = store.get(task_id)
    entries = [entry for entry in state.get("prs", []) if isinstance(entry, dict)]
    if not partial and (waiting := _pending(task, entries)):
        raise DispatchError(
            "cannot close the review, still pending: "
            + ", ".join(waiting)
            + " (collect or abort them, run `review judge`, or pass --partial)"
        )
    reports = [_pull_report(task, entry, state) for entry in entries]
    path = store.task_dir(task_id) / "review" / f"{int(state['review_id']):03d}" / SUMMARY_FILE
    atomic_write_text(path, render_summary(task_id, state, reports))
    save_review(store, task_id, {**state, "status": "closed", "summary": str(path)})
    return path


def close_review(store: TaskStore, task_id: str, *, partial: bool = False) -> Path:
    """Write ``summary.md`` from the settled rounds and close the review."""
    with _state_lock(store, task_id):
        return _close_locked(store, task_id, partial=partial)
