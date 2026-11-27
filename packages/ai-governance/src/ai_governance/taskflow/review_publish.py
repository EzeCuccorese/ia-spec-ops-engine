"""``review payload``: the GitHub review the owner approved, as a file ready to send.

After the owner read the summary and said what to publish, this builds the request body of
GitHub's "create a review" call for one pull request: an inline comment for each chosen
finding whose line is in the diff, and the rest in the review body. The engine does not send
it: it prints the command for the coordinating session to run once the approval is recorded.

Refused when the pull request moved since it was reviewed: the findings would be about code
that is no longer there.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .control import DispatchError
from .models import JsonDict
from .review import require_review
from .review_format import Finding
from .review_source import PullSnapshot, current_head
from .review_summary import Judged, read_rounds
from .store import TaskStore, atomic_write_text

EVENTS = {"comment": "COMMENT", "request-changes": "REQUEST_CHANGES", "approve": "APPROVE"}
_FILE_HEADER = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# The certainty tags reviewers add to each claim are for the judge, not for the pull request.
_CERTAINTY_TAG = re.compile(r"\s*[\[(](?:seen|assumed|unknown)[\])]", re.IGNORECASE)
# Names of the review's own capture files, meaningless to a reader of the pull request.
_CAPTURE_FILES = (("pr.diff", "the diff"), ("pr.json", "the pull request"))


@dataclass(frozen=True)
class PayloadRequest:
    """What the owner asked to publish for one pull request."""

    pull: str  # the pull request's key or URL
    event: str
    include: tuple[int, ...] = ()  # findings to publish besides the confirmed ones


@dataclass(frozen=True)
class Payload:
    path: Path
    command: list[str]
    inline: int
    in_body: int


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """Per file, the line numbers of the new version that appear in the diff: the only places
    GitHub accepts an inline comment."""
    lines: dict[str, set[int]] = {}
    path, number = "", 0
    for raw in diff.splitlines():
        if match := _FILE_HEADER.match(raw):
            path, number = ("" if match.group(1) == "/dev/null" else match.group(1)), 0
        elif match := _HUNK_HEADER.match(raw):
            number = int(match.group(1))
        elif path and number and raw[:1] in ("+", " "):
            lines.setdefault(path, set()).add(number)
            number += 1
    return lines


def _clean(text: str) -> str:
    cleaned = _CERTAINTY_TAG.sub("", text)
    for name, wording in _CAPTURE_FILES:
        cleaned = cleaned.replace(name, wording)
    return cleaned.strip()


def _comment_text(finding: Finding) -> str:
    return f"{_clean(finding.claim)}\n\n{_clean(finding.evidence)}"


def _chosen(judged: Sequence[Judged], include: Sequence[int]) -> list[Finding]:
    known = {item.finding.number for item in judged}
    if unknown := sorted(set(include) - known):
        raise DispatchError(f"no finding numbered {', '.join(map(str, unknown))} in this review")
    return [
        item.finding
        for item in judged
        if item.verdict.outcome == "confirmed" or item.finding.number in include
    ]


def _body(findings: Sequence[Finding]) -> str:
    return "\n\n".join(
        f"**`{finding.path}:{finding.line}`**: {_comment_text(finding)}" for finding in findings
    )


def build_payload(snapshot: PullSnapshot, findings: Sequence[Finding], event: str) -> JsonDict:
    """The body of ``POST /repos/{owner}/{repo}/pulls/{n}/reviews`` for these findings."""
    allowed = commentable_lines(snapshot.diff_file.read_text(encoding="utf-8"))
    inline = [f for f in findings if f.line in allowed.get(f.path, set())]
    rest = [f for f in findings if f not in inline]
    return {
        "commit_id": snapshot.head_sha,
        "event": EVENTS[event],
        "body": _body(rest),
        "comments": [
            {"path": f.path, "line": f.line, "side": "RIGHT", "body": _comment_text(f)}
            for f in inline
        ],
    }


def _entry(state: JsonDict, pull: str) -> JsonDict:
    for entry in state.get("prs", []):
        if isinstance(entry, dict) and pull in (entry.get("key"), entry.get("url")):
            return entry
    raise DispatchError(f"no pull request '{pull}' in this review")


def write_payload(store: TaskStore, task_id: str, request: PayloadRequest) -> Payload:
    """Write the review payload of one pull request and return the command that sends it."""
    if request.event not in EVENTS:
        raise DispatchError(f"event must be one of {', '.join(EVENTS)}")
    state = require_review(store, task_id)
    if state.get("status") != "closed":
        raise DispatchError("close the review first: the owner decides from its summary")
    report = read_rounds(store.get(task_id), _entry(state, request.pull))
    snapshot = report.snapshot
    if (head := current_head(snapshot.ref)) != snapshot.head_sha:
        raise DispatchError(
            f"{snapshot.ref.url} moved since it was reviewed (reviewed {snapshot.head_sha[:10]}, "
            f"now {head[:10]}): open a new review"
        )
    findings = _chosen(report.judged, request.include)
    if not findings and request.event != "approve":
        raise DispatchError("nothing to publish: no confirmed finding and none passed in --include")
    payload = build_payload(snapshot, findings, request.event)
    path = snapshot.directory / "publish.json"
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    ref = snapshot.ref
    command = ["gh", "api", "--method", "POST"]
    command += [f"repos/{ref.slug}/pulls/{ref.number}/reviews", "--input", str(path)]
    return Payload(
        path, command, len(payload["comments"]), len(findings) - len(payload["comments"])
    )
