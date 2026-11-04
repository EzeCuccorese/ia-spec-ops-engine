"""What GitHub said about one pull request, validated and reduced to plain facts.

``parse`` never defaults: a key GitHub did not send makes that one dimension ``unknown``, and a
malformed whole (a bad state, an error array) is a ``SyncError`` with a fixed code, never the
raw response or any stderr.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, TypeGuard

from .text import clean_text

STATES = ("OPEN", "CLOSED", "MERGED")
NOT_FOUND = "pull request not found"
NO_ACCESS = "not found or no access with any logged-in account"
RATE_LIMITED = "rate limited"
TIMEOUT = "timeout"
GRAPHQL_ERRORS = "graphql-errors"
UNEXPECTED = "unexpected response"
NO_GH = "gh not found on PATH"
ERROR_CODES = (NOT_FOUND, NO_ACCESS, RATE_LIMITED, TIMEOUT, GRAPHQL_ERRORS, UNEXPECTED, NO_GH)
OK, UNKNOWN = "ok", "unknown"
_CI = {
    "FAILURE": "failed",
    "ERROR": "failed",
    "PENDING": "running",
    "EXPECTED": "running",
    "SUCCESS": OK,
}
_REVIEW = {"CHANGES_REQUESTED": "changes", "REVIEW_REQUIRED": "required", "APPROVED": OK}
_MERGEABLE = {"MERGEABLE": OK, "CONFLICTING": "conflicting"}
PARENT_KINDS = ("none", "open", "merged", "closed", "ambiguous", "unknown")


@dataclass(frozen=True)
class SyncError:
    """A sync that produced no snapshot; ``code`` is one of ``ERROR_CODES``."""

    code: str


@dataclass(frozen=True)
class ThreadExtra:
    """Unresolved threads counted on pages after the first; ``complete`` = nothing left unread."""

    open: int = 0
    complete: bool = False


@dataclass(frozen=True)
class Parent:
    """The PR this one is stacked on (derived from its base branch), or why it is unknown."""

    kind: str = "none"
    number: int = 0


@dataclass(frozen=True)
class Snapshot:
    state: str
    is_draft: bool
    base: str
    head: str
    default_branch: str
    head_repo: str
    title: str
    ci: str
    review: str
    mergeable: str
    threads_open: int | None
    threads_incomplete: bool = False
    parent: Parent = field(default_factory=Parent)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Snapshot | None:
        """The snapshot a cache entry holds, or None when it is not a valid one."""
        if not isinstance(data, dict):
            return None
        try:
            parent = data.get("parent") or {}
            snap = cls(
                **{
                    **data,
                    "parent": Parent(parent.get("kind", "none"), int(parent.get("number", 0))),
                }
            )
        except (TypeError, ValueError, AttributeError):
            return None
        valid = snap.state in STATES and isinstance(snap.is_draft, bool)
        return snap if valid and snap.parent.kind in PARENT_KINDS else None

    def with_parent(self, parent: Parent) -> Snapshot:
        return replace(self, parent=parent)


def dig(data: object, *path: str) -> object:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def error_code(errors: object) -> str:
    """The fixed code for a GraphQL ``errors`` array (the messages are never surfaced)."""
    for item in errors if isinstance(errors, list) else []:
        if isinstance(item, dict) and item.get("type") == "RATE_LIMITED":
            return RATE_LIMITED
        if not isinstance(item, dict) or item.get("type") != "NOT_FOUND":
            continue
        path = item.get("path")
        return NOT_FOUND if isinstance(path, list) and path[-1:] == ["pullRequest"] else NO_ACCESS
    return GRAPHQL_ERRORS


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _head_repo(pr: dict[str, Any]) -> str | None:
    """``owner/name`` of the head repository; a deleted fork is null, an absent key is invalid."""
    if "headRepository" not in pr:
        return None
    head = pr["headRepository"]
    if head is None:
        return ""
    return _text(head.get("nameWithOwner")) if isinstance(head, dict) else None


def _ci(pr: dict[str, Any]) -> str:
    commits = pr.get("commits")
    nodes = commits.get("nodes") if isinstance(commits, dict) else None
    if not isinstance(nodes, list):
        return UNKNOWN
    if not nodes:
        return OK
    commit = nodes[-1].get("commit") if isinstance(nodes[-1], dict) else None
    if not isinstance(commit, dict) or "statusCheckRollup" not in commit:
        return UNKNOWN
    rollup = commit["statusCheckRollup"]
    if rollup is None:
        return OK
    state = rollup.get("state") if isinstance(rollup, dict) else None
    return _CI.get(state, UNKNOWN) if isinstance(state, str) else UNKNOWN


def _review(pr: dict[str, Any]) -> str:
    if "reviewDecision" not in pr:
        return UNKNOWN
    decision = pr["reviewDecision"]
    if decision is None:
        return OK
    return _REVIEW.get(decision, UNKNOWN) if isinstance(decision, str) else UNKNOWN


def thread_nodes_ok(nodes: object) -> TypeGuard[list[dict[str, Any]]]:
    """True when every review thread carries a boolean ``isResolved``."""
    return isinstance(nodes, list) and all(
        isinstance(n, dict) and isinstance(n.get("isResolved"), bool) for n in nodes
    )


def _threads(pr: dict[str, Any], extra: ThreadExtra) -> tuple[int | None, bool]:
    """(unresolved count or None when unknown, whether the count is incomplete)."""
    block = pr.get("reviewThreads")
    nodes, page = dig(block, "nodes"), dig(block, "pageInfo")
    if not isinstance(page, dict) or not thread_nodes_ok(nodes):
        return None, False
    open_count = sum(1 for n in nodes if not n["isResolved"]) + extra.open
    incomplete = page.get("hasNextPage") is not False and not extra.complete
    if incomplete and open_count == 0:
        return None, True
    return open_count, incomplete


def _facts(pr: dict[str, Any], default: str | None) -> dict[str, Any] | None:
    """The identity fields, or None when any of them is missing or of the wrong type."""
    state, draft = pr.get("state"), pr.get("isDraft")
    base, head, head_repo = (
        _text(pr.get("baseRefName")),
        _text(pr.get("headRefName")),
        _head_repo(pr),
    )
    if state not in STATES or not isinstance(draft, bool):
        return None
    if base is None or head is None or default is None or head_repo is None:
        return None
    return {
        "state": state,
        "is_draft": draft,
        "base": base,
        "head": head,
        "default_branch": default,
        "head_repo": head_repo,
        "title": clean_text(pr.get("title", ""), 200),
    }


def parse(response: object, extra: ThreadExtra | None = None) -> Snapshot | SyncError:
    """Validate one GraphQL response; ``extra`` carries the threads of the later pages."""
    if not isinstance(response, dict):
        return SyncError(UNEXPECTED)
    if response.get("errors"):
        return SyncError(error_code(response["errors"]))
    repo = dig(response, "data", "repository")
    pr = repo.get("pullRequest") if isinstance(repo, dict) else None
    if not isinstance(repo, dict) or not isinstance(pr, dict):
        return SyncError(UNEXPECTED)
    facts = _facts(pr, _text(dig(repo, "defaultBranchRef", "name")))
    if facts is None:
        return SyncError(UNEXPECTED)
    mergeable = pr.get("mergeable")
    count, incomplete = _threads(pr, extra or ThreadExtra())
    return Snapshot(
        **facts,
        ci=_ci(pr),
        review=_review(pr),
        mergeable=_MERGEABLE.get(mergeable, UNKNOWN) if isinstance(mergeable, str) else UNKNOWN,
        threads_open=count,
        threads_incomplete=incomplete,
    )


def _owned(nodes: list[Any], repo: str) -> list[dict[str, Any]]:
    """PRs whose head lives in ``repo`` itself (forks and look-alike names are excluded)."""
    mine = []
    for node in nodes:
        head = dig(node, "headRepository", "nameWithOwner")
        if isinstance(head, str) and head.lower() == repo.lower() and isinstance(node, dict):
            mine.append(node)
    return mine


def _lookup(response: object) -> tuple[dict[str, Any], list[Any], bool] | None:
    """The repository block, its PR nodes and the has-more flag, or None for any bad shape."""
    if not isinstance(response, dict) or response.get("errors"):
        return None
    block = dig(response, "data", "repository")
    prs = block.get("pullRequests") if isinstance(block, dict) else None
    nodes, more = dig(prs, "nodes"), dig(prs, "pageInfo", "hasNextPage")
    if not isinstance(block, dict) or not isinstance(nodes, list) or not isinstance(more, bool):
        return None
    return block, nodes, more


def parent_from(response: object, repo: str) -> Parent:
    """Who a stacked PR waits on, from the bounded lookup of PRs whose head is its base."""
    found = _lookup(response)
    if found is None:
        return Parent("unknown")
    block, nodes, more = found
    mine = _owned(nodes, repo)
    opened = [n for n in mine if n.get("state") == "OPEN"]
    if more or len(opened) > 1:
        return Parent("ambiguous")
    return _resolved_parent(mine, opened, block)


def _resolved_parent(
    mine: list[dict[str, Any]], opened: list[dict[str, Any]], block: dict[str, Any]
) -> Parent:
    if opened:
        return Parent("open", int(opened[0].get("number", 0)))
    if any(n.get("state") == "MERGED" for n in mine):
        return Parent("merged")
    if mine:
        return Parent("closed", int(mine[0].get("number", 0)))
    # No PR: a branch that still exists is a long-lived base; a vanished one is unknown.
    return Parent("none") if isinstance(block.get("ref"), dict) else Parent("unknown")
