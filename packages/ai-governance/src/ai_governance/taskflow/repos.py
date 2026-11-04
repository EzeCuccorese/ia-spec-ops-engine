"""Bound repositories that may have vanished from disk (a deleted worktree must not block).

One place decides what "missing" means and how it is reported: every consumer of
``task.repos`` that runs git goes through ``partition`` / ``guard`` / ``report``.
"""

from __future__ import annotations

import errno
import sys
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .models import JsonDict

T = TypeVar("T")
NONE_LIVE = "no bound repo exists on disk: bind a repo or work on a live one"
_WARNED: ContextVar[set[str] | None] = ContextVar("taskflow_warned_repos", default=None)


@dataclass(frozen=True)
class RepoSet:
    live: tuple[JsonDict, ...]
    missing: tuple[JsonDict, ...]


def partition(repos: Iterable[JsonDict]) -> RepoSet:
    """Split bindings (original order kept) by whether their path is still a directory."""
    live: list[JsonDict] = []
    missing: list[JsonDict] = []
    for binding in repos:
        (live if Path(binding["path"]).is_dir() else missing).append(binding)
    return RepoSet(tuple(live), tuple(missing))


def guard(binding: JsonDict, work: Callable[[Path], T]) -> T | None:
    """Run ``work(path)``; if it fails because the path vanished meanwhile, return None
    (the repo is missing). Any other failure is re-raised."""
    path = Path(binding["path"])
    try:
        return work(path)
    except (OSError, RuntimeError) as exc:
        if path.is_dir() or not _blames(exc, [path]):
            raise
        return None


def begin_invocation() -> None:
    """Start a fresh warning scope: each CLI invocation warns once per missing path."""
    _WARNED.set(set())


def report(paths: Iterable[str]) -> None:
    warned = _WARNED.get()
    if warned is None:
        warned = set()
        _WARNED.set(warned)
    for path in paths:
        if path not in warned:
            warned.add(path)
            print(f"bound repo not found, skipped: {path}", file=sys.stderr)


def first_live(repos: Iterable[JsonDict]) -> tuple[Path, tuple[Path, ...]] | None:
    """The first existing repo and the other existing ones; ValueError if bindings exist
    but none is on disk; None if the task has no binding at all."""
    bound = list(repos)
    if not bound:
        return None
    found = partition(bound)
    report(str(b["path"]) for b in found.missing)
    if not found.live:
        raise ValueError(NONE_LIVE)
    paths = [Path(b["path"]) for b in found.live]
    return paths[0], tuple(paths[1:])


def vanished(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if not path.is_dir()]


def _chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__  # type: ignore[assignment]


def _blames(exc: BaseException, gone: list[Path]) -> list[Path]:
    """The vanished repos that a missing-file error in the chain points into."""
    hit: list[Path] = []
    for item in _chain(exc):
        if isinstance(item, OSError) and item.errno in (errno.ENOENT, errno.ENOTDIR):
            where = Path(str(item.filename)) if item.filename is not None else None
            hit += [g for g in gone if where is not None and (where == g or g in where.parents)]
    return hit


def on_live(paths: Iterable[Path], work: Callable[[], T]) -> T:
    """Run ``work`` (git or a process inside those repos). Only a missing-file error that
    points into a repo that vanished meanwhile is reported and turned into a refusal; any
    other failure (permissions, store, lease, runtime) surfaces untouched, even if a repo
    happens to be gone too. Interrupts are never caught."""
    bound = list(paths)
    try:
        return work()
    except (OSError, RuntimeError) as exc:
        blamed = _blames(exc, vanished(bound))
        if not blamed:
            raise
        report(str(path) for path in blamed)
        if len(blamed) < len(bound) and any(p.is_dir() for p in bound):
            names = ", ".join(str(path) for path in blamed)
            raise ValueError(
                f"bound repo vanished during the command, run it again: {names}"
            ) from exc
        raise ValueError(NONE_LIVE) from exc
