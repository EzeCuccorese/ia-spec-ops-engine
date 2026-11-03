"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

from .models import Task
from .prs.board import summary_for
from .store import TaskStore


def _pick_focus(tasks: list[Task], focus_id: str | None) -> Task | None:
    return next((t for t in tasks if t.id == focus_id), None) or next(iter(tasks), None)


def _focus_lines(focus: Task) -> list[str]:
    lines = [
        f"- {focus.id} [{focus.phase}{', blocked' if focus.blocked else ''}]: {focus.summary or focus.title}"
    ]
    pending = [s["text"] for s in focus.steps if not s.get("done")][:5]
    if pending:
        lines.append("  next: " + "; ".join(pending))
    return lines


def digest(store: TaskStore, focus_id: str | None = None, max_chars: int = 1600) -> str:
    tasks = store.list()
    focus = _pick_focus(tasks, focus_id)
    lines = [f"TASKFLOW ({len(tasks)} open) — `ai-governance taskflow --help` explains the flow"]
    if focus:
        lines += _focus_lines(focus)
        if prs := summary_for(store, focus.id):
            lines.append(f"  {prs}")
    others = [t.id for t in tasks if focus is None or t.id != focus.id]
    if others:
        lines.append("  others: " + ", ".join(others[:8]))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
