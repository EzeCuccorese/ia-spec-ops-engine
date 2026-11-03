"""Register a pull request that ``gh pr create`` just printed (Claude PostToolUse, Bash).

Strict on purpose: only the exact command shape ``[cd DIR &&] gh [-R OWNER/REPO] pr create ...``
counts, the last stdout line must be the PR URL (``gh`` prints it only on success), and the
payload must carry no failure marker. No network and no model are involved; the only write is
``Task.prs`` of the task bound to the working directory. A title is never echoed back."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from .models import Task, now_iso
from .prs.origin import infer_repo
from .prs.refs import PrRef
from .prs.registry import AddMeta, add_refs
from .resolver import TaskResolver
from .store import TaskStore

_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_][A-Za-z0-9._-]{0,99})"
    r"/pull/([0-9]{1,9})"
)
_OPERATORS = frozenset("();<>|&")
_FAILURE_KEYS = ("exit_code", "exitCode", "returncode")


def _tokens(command: str) -> list[str] | None:
    """The shell tokens of a one-line command, or None when it could hide another command."""
    if any(mark in command for mark in ("\n", "\r", "`", "$(")):
        return None
    try:
        return list(shlex.shlex(command, posix=True, punctuation_chars=True))
    except ValueError:
        return None


def _after_cd(tokens: list[str]) -> tuple[str, list[str]] | None:
    """Split off a leading ``cd DIR &&`` (the one operator allowed); None when it is malformed."""
    if tokens[:1] != ["cd"]:
        return "", tokens
    if len(tokens) < 4 or tokens[2] != "&&":
        return None
    return tokens[1], tokens[3:]


def _repo_flag(rest: list[str]) -> tuple[str, list[str]] | None:
    """Split off ``-R OWNER/REPO`` (or ``--repo``); None when the flag has no value."""
    if rest[:1] not in (["-R"], ["--repo"]):
        return "", rest
    return (rest[1], rest[2:]) if len(rest) >= 2 else None


def _shape(tokens: list[str]) -> tuple[str, str] | None:
    """(directory of a leading ``cd DIR &&``, repo of ``-R``) for the accepted shape, else None."""
    head = _after_cd(tokens)
    if head is None:
        return None
    directory, tokens = head
    if not tokens or tokens[0] != "gh" or any(set(t) <= _OPERATORS for t in tokens):
        return None
    flag = _repo_flag(tokens[1:])
    if flag is None:
        return None
    repo, rest = flag
    return (directory, repo) if rest[:2] == ["pr", "create"] else None


def _failed(response: object) -> bool:
    """True when the payload carries a failure marker (it may carry none at all)."""
    if not isinstance(response, dict):
        return False
    if response.get("interrupted") is True:
        return True
    codes = [response.get(key) for key in _FAILURE_KEYS]
    return any(isinstance(c, int | float) and not isinstance(c, bool) and c != 0 for c in codes)


def _stdout(payload: dict[str, Any]) -> str:
    response = payload.get("tool_response")
    if isinstance(response, dict):
        return str(response.get("stdout") or "")
    return str(payload.get("tool_output") or (response if isinstance(response, str) else ""))


def _created(text: str) -> PrRef | None:
    """The PR named by the last non-empty line, only when that whole line is its URL."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    match = _URL.fullmatch(lines[-1]) if lines else None
    return PrRef(f"{match[1]}/{match[2]}", int(match[3])) if match else None


def _hint(ref: PrRef) -> str:
    return (
        f"TASKFLOW: {ref.repo}#{ref.number} was created; "
        f"register it with `taskflow pr add <task> {ref.url}`."
    )


def _same_repo(ref: PrRef, flag: str, store: TaskStore, task_id: str) -> bool:
    """The URL repo must be the ``-R`` repo, or else the one origin of the task's bound repos."""
    if flag:
        return flag.lower() == ref.repo.lower()
    paths = [Path(r["path"]) for r in store.get(task_id).repos]
    return infer_repo(paths).lower() == ref.repo.lower()


def _accepted(payload: dict[str, Any]) -> tuple[tuple[str, str], PrRef] | None:
    """((directory, -R repo), created PR) when the payload is a clean ``gh pr create``."""
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or "gh pr create" not in command:
        return None
    tokens = _tokens(command)
    shape = _shape(tokens) if tokens else None
    ref = _created(_stdout(payload))
    if shape is None or ref is None or _failed(payload.get("tool_response")):
        return None
    return shape, ref


def _register(payload: dict[str, Any], cwd: Path) -> str:
    accepted = _accepted(payload)
    if accepted is None:
        return ""
    (directory, flag), ref = accepted
    work = (cwd / directory).resolve() if directory else cwd
    store = TaskStore()
    task_id = TaskResolver.resolve_from_context(store.list(), work)
    if not task_id or not _same_repo(ref, flag, store, task_id):
        return _hint(ref)
    added = [0]

    def change(task: Task) -> None:
        added[0] = add_refs(task, [ref], AddMeta("", "hook", now_iso()))

    store.mutate(task_id, change)
    what = "registered" if added[0] else "already registered"
    return f"TASKFLOW: {what} {ref.repo}#{ref.number} in task {task_id} (`taskflow pr list`)."


def register_created_pr(payload: dict[str, Any], cwd: Path) -> str:
    """One context line about the PR a ``gh pr create`` made ('' when none). Never raises."""
    try:
        return _register(payload, cwd)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""
