"""Which pull requests a task has: registrations only, never live status.

Besides ``Task.prs`` the older ways of naming a PR still count, read without any state:
``references`` of kind ``pr`` and the ``pr`` of each bound repo. ``Task.pr_removed`` hides a
legacy PR after ``pr rm`` so it does not reappear. These functions only reshape a ``Task``
(run them inside ``TaskStore.mutate``); they touch no file and no network.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..models import JsonDict, Task
from .refs import PrRef, scan
from .text import clean_text

SOURCES = ("cli", "hook", "paste")


@dataclass(frozen=True)
class Registration:
    ref: PrRef
    group: str = ""
    source: str = "cli"
    legacy: bool = False


@dataclass(frozen=True)
class AddMeta:
    """What is recorded with an added PR: its group, where it came from and when."""

    group: str = ""
    source: str = "cli"
    added_at: str = ""


def _legacy_texts(task: Task) -> list[str]:
    texts = [
        str(r.get("value", "")) + " " + str(r.get("url", ""))
        for r in task.references
        if r.get("kind") == "pr"
    ]
    return texts + [str(r["pr"]) for r in task.repos if r.get("pr")]


def _explicit(task: Task) -> list[Registration]:
    found = []
    for item in task.prs:
        repo, number = item.get("repo"), item.get("number")
        if isinstance(repo, str) and isinstance(number, int) and not isinstance(number, bool):
            found.append(
                Registration(
                    PrRef(repo, number),
                    clean_text(item.get("group", ""), 40),
                    str(item.get("source", "cli")),
                )
            )
    return found


def registrations(task: Task) -> tuple[list[Registration], int]:
    """(the task's PRs without duplicates, bare ``#N`` of legacy sources that were skipped)."""
    hidden = {key.lower() for key in task.pr_removed}
    found: dict[str, Registration] = {}
    for item in _explicit(task):
        found.setdefault(item.ref.key, item)
    skipped = 0
    for text in _legacy_texts(task):
        result = scan(text)
        skipped += result.bare_skipped
        for ref in result.refs:
            if ref.key not in hidden:
                found.setdefault(ref.key, Registration(ref, legacy=True))
    return list(found.values()), skipped


def add_refs(task: Task, refs: Iterable[PrRef], meta: AddMeta) -> int:
    """Register ``refs`` (idempotent by key); returns how many were new."""
    known = {item.ref.key: item for item in _explicit(task)}
    new = 0
    for ref in refs:
        if ref.key in {k.lower() for k in task.pr_removed}:
            task.pr_removed = [k for k in task.pr_removed if k.lower() != ref.key]
        if ref.key in known:
            _regroup(task, ref, meta.group)
            continue
        task.prs.append(_entry(ref, meta))
        known[ref.key] = Registration(ref)
        new += 1
    return new


def _entry(ref: PrRef, meta: AddMeta) -> JsonDict:
    return {
        "repo": ref.repo,
        "number": ref.number,
        "url": ref.url,
        "group": clean_text(meta.group, 40),
        "added_at": meta.added_at,
        "source": meta.source if meta.source in SOURCES else "cli",
    }


def _regroup(task: Task, ref: PrRef, group: str) -> None:
    if not group:
        return
    for item in task.prs:
        if PrRef(str(item.get("repo")), _number(item)).key == ref.key:
            item["group"] = clean_text(group, 40)


def remove_ref(task: Task, ref: PrRef) -> bool:
    """Drop ``ref`` from the task; a legacy-derived PR is hidden instead. False if absent."""
    before = len(task.prs)
    task.prs = [i for i in task.prs if PrRef(str(i.get("repo")), _number(i)).key != ref.key]
    removed = len(task.prs) != before
    legacy = [r for r in registrations(task)[0] if r.legacy and r.ref.key == ref.key]
    if legacy and ref.key not in {k.lower() for k in task.pr_removed}:
        task.pr_removed.append(ref.key)
        removed = True
    return removed


def _number(item: JsonDict) -> int:
    value = item.get("number", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
