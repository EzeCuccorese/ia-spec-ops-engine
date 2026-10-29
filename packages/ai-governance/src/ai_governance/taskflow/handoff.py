"""Text packages built from the task state: handoff to a role, findings, ticket draft.

Everything that leaves the store goes through :func:`scrub`, so tokens and passwords that
ended up in facts or notes are never copied into a prompt or a ticket.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import JsonDict, Task

SECRET = re.compile(
    r"(?i)(gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
    r"(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+)"
)


def scrub(text: str) -> str:
    return SECRET.sub("[redacted]", text)


def _latest_verdicts(task: Task) -> list[str]:
    seen: dict[str, JsonDict] = {}
    for record in task.rounds:
        seen[f"{record.get('role')}/{record.get('focus', '')}"] = record
    return [
        f"- {key.rstrip('/')}: {r.get('verdict')} (round {int(r['n']):03d}, {r.get('state')}, "
        f"stamp {r.get('stamp')})"
        for key, r in seen.items()
    ]


def handoff(task: Task, role: str) -> str:
    lines = [
        f"# Handoff to {role}: {task.id} — {task.title}",
        f"Phase: {task.phase} · workflow {task.workflow} · owner {task.owner_mode}",
        f"Goal: {task.summary or task.title}",
        "",
        "## Repositories",
        *[
            f"- {r['path']} (branch {r.get('branch', '?')}, integration {r.get('integration_branch', '-')})"
            for r in task.repos
        ],
        "",
        "## Steps",
        *[f"- [{'x' if s.get('done') else ' '}] {s['text']}" for s in task.steps],
        "",
        "## Facts and decisions",
        *[f"- {f['text']}" for f in task.facts],
        *[f"- decision: {d['text']} ({d.get('why', '')})" for d in task.decisions],
        "",
        "## Latest verdicts",
        *_latest_verdicts(task),
    ]
    return scrub("\n".join(lines)) + "\n"


def findings(task: Task) -> str:
    judged = [
        r
        for r in task.rounds
        if r.get("role") == "judge" and r.get("verdict") in ("block", "concerns")
    ]
    lines = [
        f"# Findings for the owner: {task.id} — {task.title}",
        "",
        *[
            f"- {r['path']} @ {s.get('head', '?')[:12]}"
            for r in task.repos
            for s in task.code_stamp.get("repos", [])
            if s.get("repo") == r["path"]
        ],
        "",
    ]
    for record in judged:
        body = (
            Path(record["file"]).read_text(encoding="utf-8")
            if Path(record["file"]).exists()
            else ""
        )
        answer = body.split("## Answer", 1)[-1].strip()
        lines += [
            f"## Judge {record.get('focus') or ''} (round {int(record['n']):03d}, {record['verdict']})",
            "",
            answer,
            "",
        ]
    return scrub("\n".join(lines)) + "\n"


def ticket_draft(task: Task) -> str:
    """Draft comment for the ticket, written for the team: no tooling or agent names."""
    lines = [f"**{task.title}**", "", task.summary, "", "**Done**"]
    lines += [f"- {s['text']}" for s in task.steps if s.get("done")]
    pending = [f"- {s['text']}" for s in task.steps if not s.get("done")]
    deployed = [
        f"- {d.get('env')}: {Path(str(d.get('repo'))).name} @ {str(d.get('sha'))[:12]}"
        for d in task.deployments
    ]
    prs = [f"- {r.get('pr')}" for r in task.repos if r.get("pr")]
    for heading, items in (("Pending", pending), ("Deployed", deployed), ("PRs", prs)):
        if items:
            lines += ["", f"**{heading}**", *items]
    return scrub("\n".join(lines)) + "\n"
