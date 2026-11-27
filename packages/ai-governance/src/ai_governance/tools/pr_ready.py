"""Read-only answer to "is this pull request ready, and if not, why".

Usage: ``ai-governance pr-ready <pull request URL> [--json] [--head SHA]
[--ignore-threads ID,ID] [--gh-user LOGIN] [--allow-no-checks]``

Exit codes: 0 ready, 1 not ready, 2 the pull request could not be read.

The verdict never reports ready while something is pending or unknown:
unreadable required checks, unknown mergeability, a head that moved while
reading, zero reported checks and truncated or malformed listings all keep
``settled`` false and add a blocker.

Parsing rule: every field the verdict depends on must be present in the
response and of the expected type. An absent key differs from an explicit
null, which is accepted only where the API gives null a meaning.

A required review (REVIEW_REQUIRED) does not block ``ready``: the question
is whether the pull request can be handed to a human reviewer. Only
CHANGES_REQUESTED blocks, and ``review_decision`` is reported.

Limit: rulesets of type ``workflows`` (required workflows) cannot be mapped
to check names, so an active one gives ``required_checks_unknown``.

Limit: only checks reported on the head commit are read, not the ones
GitHub may run on the pull request's test-merge commit.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any, Generic, TypeVar
from urllib.parse import quote

from .pr_watch import FAIL_CONCLUSIONS, _gh_env

T = TypeVar("T")

HOST = "github.com"
MAX_PAGES = 20
RULES_PER_PAGE = 100
URL_PATTERN = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
PASS_CONCLUSIONS = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
KNOWN_CONCLUSIONS = FAIL_CONCLUSIONS | PASS_CONCLUSIONS | {"STALE"}
CHECK_STATUSES = frozenset(
    {"QUEUED", "IN_PROGRESS", "COMPLETED", "WAITING", "PENDING", "REQUESTED"}
)
STATUS_STATES = frozenset({"EXPECTED", "ERROR", "FAILURE", "PENDING", "SUCCESS"})
FAIL_STATUSES = frozenset({"FAILURE", "ERROR"})
MERGEABLE_VALUES = frozenset({"MERGEABLE", "CONFLICTING", "UNKNOWN"})
REVIEW_DECISIONS = frozenset({"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"})
RULE_TYPE_REQUIRED_CHECKS = "required_status_checks"
# Required workflows demand checks this command cannot map to check names.
UNMAPPABLE_RULE_TYPES = frozenset({"workflows"})
COMMIT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

META_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      isDraft mergeable reviewDecision headRefOid
      baseRef {
        name
        target { oid }
        branchProtectionRule { requiredStatusChecks { context app { databaseId } } }
      }
    }
  }
}
"""

CHECKS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      commits(last: 1) { nodes { commit { oid statusCheckRollup {
        contexts(first: 100, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            __typename
            ... on CheckRun {
              name status conclusion checkSuite { app { name databaseId } }
            }
            ... on StatusContext { context state }
          }
        }
      } } } }
    }
  }
}
"""

THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved isOutdated
          comments(first: 1) { nodes { author { login } } }
        }
      }
    }
  }
}
"""

_UNSETTLED_CODES = frozenset(
    {
        "head_moved",
        "mergeable_unknown",
        "required_checks_unknown",
        "incomplete_listing",
        "no_checks_reported",
    }
)
_UNSETTLED_PREFIXES = ("check_pending:", "required_check_missing:")


class PrReadError(RuntimeError):
    """The pull request could not be read."""


class Malformed(ValueError):
    """A field the verdict depends on is absent or has an unexpected type."""


@dataclass(frozen=True)
class PullRef:
    owner: str
    repo: str
    number: int


@dataclass(frozen=True)
class Identity:
    head: str
    base: str
    base_tip: str


@dataclass(frozen=True)
class Requirement:
    name: str
    app_id: int | None
    pinned: bool


@dataclass(frozen=True)
class PullMeta:
    identity: Identity
    draft: bool
    mergeable: str
    review_decision: str | None
    classic: tuple[Requirement, ...] | None
    complete: bool


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    state: str
    app_id: int | None


@dataclass(frozen=True)
class Thread:
    id: str
    author: str
    outdated: bool
    resolved: bool


@dataclass(frozen=True)
class Reply:
    pull: dict[str, Any]
    clean: bool


@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None
    ok: bool


@dataclass(frozen=True)
class Listing(Generic[T]):
    items: tuple[T, ...]
    complete: bool


@dataclass(frozen=True)
class RulesRead:
    requirements: tuple[Requirement, ...]
    complete: bool


@dataclass(frozen=True)
class BranchRead:
    requirements: tuple[Requirement, ...]
    tip: str


@dataclass(frozen=True)
class Snapshot:
    ref: PullRef
    first: PullMeta
    meta: PullMeta
    checks: Listing[Check]
    check_heads: tuple[str, ...]
    threads: Listing[Thread]
    branch: BranchRead | None
    rules: RulesRead | None


@dataclass(frozen=True)
class Options:
    expected_head: str | None
    ignored_threads: frozenset[str]
    allow_no_checks: bool


@dataclass(frozen=True)
class CheckView:
    name: str
    source: str
    state: str


@dataclass(frozen=True)
class ThreadView:
    id: str
    author: str
    outdated: bool


@dataclass(frozen=True)
class Report:
    url: str
    head: str
    draft: bool
    review_decision: str | None
    checks: tuple[CheckView, ...]
    settled: bool
    ready: bool
    blockers: tuple[str, ...]
    unresolved_threads: tuple[ThreadView, ...]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Malformed("object expected")
    return value


def _need(box: dict[str, Any], key: str) -> object:
    if key not in box:
        raise Malformed(f"missing {key}")
    return box[key]


def _req_dict(box: dict[str, Any], key: str) -> dict[str, Any]:
    return _as_dict(_need(box, key))


def _req_list(box: dict[str, Any], key: str) -> list[Any]:
    value = _need(box, key)
    if not isinstance(value, list):
        raise Malformed(f"{key} must be a list")
    return value


def _req_str(box: dict[str, Any], key: str) -> str:
    value = _need(box, key)
    if not isinstance(value, str) or not value.strip():
        raise Malformed(f"{key} must be a non-empty string")
    return value.strip()


def _req_commit(box: dict[str, Any], key: str) -> str:
    value = _req_str(box, key)
    if not COMMIT_ID.match(value):
        raise Malformed(f"{key} is not a commit id")
    return value


def _req_bool(box: dict[str, Any], key: str) -> bool:
    value = _need(box, key)
    if not isinstance(value, bool):
        raise Malformed(f"{key} must be a boolean")
    return value


def _req_enum(box: dict[str, Any], key: str, allowed: frozenset[str]) -> str:
    value = _need(box, key)
    if not isinstance(value, str) or value not in allowed:
        raise Malformed(f"{key} has an unknown value")
    return value


def _null_enum(box: dict[str, Any], key: str, allowed: frozenset[str]) -> str | None:
    return None if _need(box, key) is None else _req_enum(box, key, allowed)


def _null_dict(box: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = _need(box, key)
    return None if value is None else _as_dict(value)


def _null_int(box: dict[str, Any], key: str) -> int | None:
    value = _need(box, key)
    if value is not None and _int(value) is None:
        raise Malformed(f"{key} must be an integer or null")
    return _int(value)


def parse_url(url: str) -> PullRef:
    match = URL_PATTERN.match(url.strip())
    if not match:
        raise PrReadError(f"not a pull request URL: {url}")
    return PullRef(match.group(1), match.group(2), int(match.group(3)))


def _gh(args: list[str], env: dict[str, str]) -> str:
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, env=env, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrReadError(f"gh could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr.strip().splitlines() or [str(proc.returncode)])[0]
        raise PrReadError(f"gh {' '.join(args[:2])} failed: {detail}")
    return proc.stdout


def _api_json(args: list[str], env: dict[str, str]) -> object:
    """Run ``gh api`` against an explicit host, so GH_HOST cannot redirect the read."""
    try:
        return json.loads(_gh(["api", "--hostname", HOST, *args], env))
    except json.JSONDecodeError as exc:
        raise PrReadError("gh returned invalid JSON") from exc


def _graphql(query: str, ref: PullRef, cursor: str | None, env: dict[str, str]) -> Reply:
    args = ["graphql", "-f", f"query={query}", "-f", f"owner={ref.owner}"]
    args += ["-f", f"repo={ref.repo}", "-F", f"number={ref.number}"]
    if cursor:
        args += ["-f", f"after={cursor}"]
    data = _dict(_api_json(args, env))
    pull = _dict(_dict(data.get("data")).get("repository")).get("pullRequest")
    if not isinstance(pull, dict):
        raise PrReadError(f"pull request {ref.owner}/{ref.repo}#{ref.number} not found")
    return Reply(pull, not data.get("errors"))


def _page_of(container: object, parse: Callable[[object], T | None]) -> Page[T]:
    box = _dict(container)
    nodes, info = box.get("nodes"), _dict(box.get("pageInfo"))
    if not isinstance(nodes, list) or not isinstance(info.get("hasNextPage"), bool):
        return Page((), None, False)
    items = tuple(p for p in map(parse, nodes) if p is not None)
    ok = len(items) == len(nodes)
    if not info["hasNextPage"]:
        return Page(items, None, ok)
    cursor = _text(info.get("endCursor"))
    return Page(items, cursor or None, ok and bool(cursor))


def _paginate(fetch: Callable[[str | None], Page[T]]) -> Listing[T]:
    items: list[T] = []
    cursor: str | None = None
    ok = True
    for _ in range(MAX_PAGES):
        page = fetch(cursor)
        items += page.items
        ok = ok and page.ok
        if page.next_cursor is None:
            return Listing(tuple(items), ok)
        cursor = page.next_cursor
    return Listing(tuple(items), False)


def _graphql_requirement(item: object) -> Requirement:
    box = _as_dict(item)
    app = _null_dict(box, "app")
    app_id = None if app is None else _null_int(app, "databaseId")
    return Requirement(_req_str(box, "context"), app_id, app is not None)


def _classic_requirements(base_ref: dict[str, Any]) -> tuple[Requirement, ...] | None:
    """Requirements GraphQL shows for the base branch (null alone proves nothing)."""
    try:
        rule = _null_dict(base_ref, "branchProtectionRule")
        if rule is None:
            return ()
        return tuple(_graphql_requirement(i) for i in _req_list(rule, "requiredStatusChecks"))
    except Malformed:
        return None


def _meta_from(pull: dict[str, Any], clean: bool) -> PullMeta:
    base_ref = _req_dict(pull, "baseRef")
    identity = Identity(
        _req_commit(pull, "headRefOid"),
        _req_str(base_ref, "name"),
        _req_commit(_req_dict(base_ref, "target"), "oid"),
    )
    return PullMeta(
        identity=identity,
        draft=_req_bool(pull, "isDraft"),
        mergeable=_req_enum(pull, "mergeable", MERGEABLE_VALUES),
        review_decision=_null_enum(pull, "reviewDecision", REVIEW_DECISIONS),
        classic=_classic_requirements(base_ref),
        complete=clean,
    )


def fetch_meta(ref: PullRef, env: dict[str, str]) -> PullMeta:
    reply = _graphql(META_QUERY, ref, None, env)
    try:
        return _meta_from(reply.pull, reply.clean)
    except Malformed:
        return PullMeta(Identity("", "", ""), False, "UNKNOWN", None, None, False)


def _check_run_state(status: str, conclusion: str | None) -> str:
    if status != "COMPLETED":
        return "pending"
    if conclusion in FAIL_CONCLUSIONS:
        return "fail"
    return "pass" if conclusion in PASS_CONCLUSIONS else "pending"


def _check_from(node: object) -> Check:
    box = _as_dict(node)
    kind = _need(box, "__typename")
    if kind == "StatusContext":
        context = _req_str(box, "context")
        state = _req_enum(box, "state", STATUS_STATES)
        return Check(context, context.partition("/")[0].strip(), _status_state(state), None)
    if kind != "CheckRun":
        raise Malformed("unknown check type")
    app = _null_dict(_req_dict(box, "checkSuite"), "app")
    status = _req_enum(box, "status", CHECK_STATUSES)
    conclusion = _null_enum(box, "conclusion", KNOWN_CONCLUSIONS)
    source = "unknown" if app is None else _req_str(app, "name")
    app_id = None if app is None else _null_int(app, "databaseId")
    return Check(_req_str(box, "name"), source, _check_run_state(status, conclusion), app_id)


def _status_state(state: str) -> str:
    if state == "SUCCESS":
        return "pass"
    return "fail" if state in FAIL_STATUSES else "pending"


def parse_check(node: object) -> Check | None:
    try:
        return _check_from(node)
    except Malformed:
        return None


def _thread_from(node: object) -> Thread:
    box = _as_dict(node)
    comments = _req_list(_req_dict(box, "comments"), "nodes")
    first = _as_dict(comments[0]) if comments else {}
    author = _null_dict(first, "author") if comments else None
    login = _req_str(author, "login") if author is not None else "unknown"
    return Thread(
        _req_str(box, "id"), login, _req_bool(box, "isOutdated"), _req_bool(box, "isResolved")
    )


def parse_thread(node: object) -> Thread | None:
    try:
        return _thread_from(node)
    except Malformed:
        return None


def _head_commit(pull: dict[str, Any]) -> dict[str, Any]:
    nodes = _req_list(_req_dict(pull, "commits"), "nodes")
    if not nodes:
        raise Malformed("no head commit")
    return _req_dict(_as_dict(nodes[0]), "commit")


def _checks_page(pull: dict[str, Any], first_page: bool) -> tuple[str, Page[Check]]:
    try:
        commit = _head_commit(pull)
        oid = _req_str(commit, "oid")
        rollup = _need(commit, "statusCheckRollup")
    except Malformed:
        return "", Page((), None, False)
    if rollup is None:
        # A null rollup is "no checks yet" on the first page, a vanished listing afterwards.
        return oid, Page((), None, first_page)
    return oid, _page_of(_dict(rollup).get("contexts"), parse_check)


def fetch_checks(ref: PullRef, env: dict[str, str]) -> tuple[Listing[Check], tuple[str, ...]]:
    heads: list[str] = []

    def fetch(cursor: str | None) -> Page[Check]:
        reply = _graphql(CHECKS_QUERY, ref, cursor, env)
        oid, page = _checks_page(reply.pull, cursor is None)
        heads.append(oid)
        return replace(page, ok=page.ok and reply.clean)

    return _paginate(fetch), tuple(heads)


def fetch_threads(ref: PullRef, env: dict[str, str]) -> Listing[Thread]:
    def fetch(cursor: str | None) -> Page[Thread]:
        reply = _graphql(THREADS_QUERY, ref, cursor, env)
        page = _page_of(reply.pull.get("reviewThreads"), parse_thread)
        return replace(page, ok=page.ok and reply.clean)

    return _paginate(fetch)


def _rule_requirement(entry: object) -> Requirement:
    box = _as_dict(entry)
    pin = box.get("integration_id")
    return Requirement(_req_str(box, "context"), _int(pin), pin is not None)


def _rule_requirements(rule: object) -> list[Requirement]:
    box = _as_dict(rule)
    rule_type = _req_str(box, "type")
    if rule_type in UNMAPPABLE_RULE_TYPES:
        raise Malformed("rule cannot be mapped to check names")
    if rule_type != RULE_TYPE_REQUIRED_CHECKS:
        return []
    params = _req_dict(box, "parameters")
    return [_rule_requirement(e) for e in _req_list(params, RULE_TYPE_REQUIRED_CHECKS)]


def fetch_rules(ref: PullRef, base: str, env: dict[str, str]) -> RulesRead | None:
    """Ruleset requirements; gh follows the Link header and returns one list per page."""
    if not base:
        return None
    path = f"repos/{ref.owner}/{ref.repo}/rules/branches/{quote(base, safe='')}"
    args = ["--paginate", "--slurp", f"{path}?per_page={RULES_PER_PAGE}"]
    try:
        pages = _api_json(args, env)
        if not isinstance(pages, list) or not pages:
            return None
        found = [
            r
            for page in pages[:MAX_PAGES]
            for rule in _as_list(page)
            for r in _rule_requirements(rule)
        ]
    except (PrReadError, Malformed):
        return None
    return RulesRead(tuple(found), len(pages) <= MAX_PAGES)


def _as_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise Malformed("list expected")
    return value


def _branch_requirement(entry: object) -> Requirement:
    box = _as_dict(entry)
    app_id = _null_int(box, "app_id")
    pinned = app_id is not None and app_id > 0
    return Requirement(_req_str(box, "context"), app_id if pinned else None, pinned)


def _branch_requirements(branch: dict[str, Any]) -> tuple[Requirement, ...]:
    if not _req_bool(branch, "protected"):
        return ()
    checks = _null_dict(_req_dict(branch, "protection"), "required_status_checks")
    if checks is None:
        return ()
    contexts = [Requirement(c, None, False) for c in map(_text, _req_list(checks, "contexts"))]
    if not all(r.name for r in contexts):
        raise Malformed("empty context")
    pinned = [_branch_requirement(e) for e in _req_list(checks, "checks")]
    return tuple(contexts + pinned)


def fetch_branch(ref: PullRef, base: str, env: dict[str, str]) -> BranchRead | None:
    """Classic required checks from the branch itself; None when they cannot be proven."""
    if not base:
        return None
    path = f"repos/{ref.owner}/{ref.repo}/branches/{quote(base, safe='')}"
    try:
        branch = _as_dict(_api_json([path], env))
        tip = _text(_dict(branch.get("commit")).get("sha"))
        return BranchRead(_branch_requirements(branch), tip)
    except (PrReadError, Malformed):
        return None


def take_snapshot(ref: PullRef, env: dict[str, str]) -> Snapshot:
    first = fetch_meta(ref, env)
    checks, heads = fetch_checks(ref, env)
    threads = fetch_threads(ref, env)
    base = first.identity.base
    rules = fetch_rules(ref, base, env)
    branch = fetch_branch(ref, base, env)
    return Snapshot(ref, first, fetch_meta(ref, env), checks, heads, threads, branch, rules)


def _head_blockers(snap: Snapshot, options: Options) -> list[str]:
    head = snap.meta.identity.head
    moved = not head or snap.first.identity != snap.meta.identity
    moved = moved or any(seen != head for seen in snap.check_heads)
    moved = moved or (snap.branch is not None and snap.branch.tip != snap.meta.identity.base_tip)
    if options.expected_head:
        moved = moved or not head.startswith(options.expected_head)
    return ["head_moved"] if moved else []


def _merge_blockers(snap: Snapshot) -> list[str]:
    blockers: list[str] = []
    if snap.meta.mergeable == "CONFLICTING":
        blockers.append("conflict")
    elif snap.meta.mergeable != "MERGEABLE":
        blockers.append("mergeable_unknown")
    if snap.meta.review_decision == "CHANGES_REQUESTED":
        blockers.append("changes_requested")
    return blockers


def _check_blockers(snap: Snapshot, options: Options) -> list[str]:
    checks = snap.checks.items
    blockers = [f"check_failed:{c.name}" for c in checks if c.state == "fail"]
    blockers += [f"check_pending:{c.name}" for c in checks if c.state == "pending"]
    if not checks and not options.allow_no_checks:
        blockers.append("no_checks_reported")
    return blockers


def _is_satisfied(requirement: Requirement, checks: tuple[Check, ...]) -> bool:
    for check in checks:
        if check.name != requirement.name:
            continue
        if not requirement.pinned:
            return True
        if requirement.app_id is not None and check.app_id == requirement.app_id:
            return True
    return False


def _policy_blockers(snap: Snapshot) -> list[str]:
    if snap.meta.classic is None or snap.branch is None or snap.rules is None:
        return ["required_checks_unknown"]
    required = {*snap.meta.classic, *snap.branch.requirements, *snap.rules.requirements}
    missing = [r.name for r in required if not _is_satisfied(r, snap.checks.items)]
    return [f"required_check_missing:{name}" for name in missing]


def unresolved_threads(snap: Snapshot, options: Options) -> list[Thread]:
    return [t for t in snap.threads.items if not t.resolved and t.id not in options.ignored_threads]


def _listing_blockers(snap: Snapshot, options: Options) -> list[str]:
    blockers: list[str] = []
    open_threads = unresolved_threads(snap, options)
    if open_threads:
        blockers.append(f"threads_unresolved:{len(open_threads)}")
    complete = snap.first.complete and snap.meta.complete
    complete = complete and snap.checks.complete and snap.threads.complete
    if not complete or (snap.rules is not None and not snap.rules.complete):
        blockers.append("incomplete_listing")
    return blockers


def compute_blockers(snap: Snapshot, options: Options) -> tuple[str, ...]:
    found = _head_blockers(snap, options) + _merge_blockers(snap)
    found += _check_blockers(snap, options) + _policy_blockers(snap)
    found += _listing_blockers(snap, options)
    return tuple(sorted(set(found)))


def build_report(snap: Snapshot, options: Options) -> Report:
    blockers = compute_blockers(snap, options)
    unsettled = any(b in _UNSETTLED_CODES or b.startswith(_UNSETTLED_PREFIXES) for b in blockers)
    ref = snap.ref
    return Report(
        url=f"https://{HOST}/{ref.owner}/{ref.repo}/pull/{ref.number}",
        head=snap.meta.identity.head,
        draft=snap.meta.draft,
        review_decision=snap.meta.review_decision,
        checks=tuple(CheckView(c.name, c.source, c.state) for c in snap.checks.items),
        settled=not unsettled,
        ready=not unsettled and not blockers,
        blockers=blockers,
        unresolved_threads=tuple(
            ThreadView(t.id, t.author, t.outdated) for t in unresolved_threads(snap, options)
        ),
    )


def format_text(report: Report) -> str:
    verdict = "ready" if report.ready else "not ready"
    draft = " (draft)" if report.draft else ""
    lines = [f"{report.url}: {verdict} (settled: {str(report.settled).lower()})"]
    review = report.review_decision or "none"
    lines.append(f"  head {report.head[:12]}{draft}, review {review}")
    lines += [f"  blocker: {b}" for b in report.blockers]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance pr-ready", description="Read-only pull request readiness verdict."
    )
    parser.add_argument("url", help="https://github.com/<owner>/<repo>/pull/<n>")
    parser.add_argument("--json", action="store_true", help="print the verdict as JSON")
    parser.add_argument("--head", default="", help="commit the caller believes is the head")
    parser.add_argument("--ignore-threads", default="", help="comma-separated thread node ids")
    parser.add_argument("--gh-user", default="", help="gh account to read with")
    parser.add_argument(
        "--allow-no-checks",
        action="store_true",
        help="accept a head with no reported checks (repositories without CI)",
    )
    return parser


def _options(args: argparse.Namespace) -> Options:
    ignored = frozenset(i.strip() for i in args.ignore_threads.split(",") if i.strip())
    return Options(args.head.strip() or None, ignored, args.allow_no_checks)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        ref = parse_url(args.url)
        env = _gh_env(args.gh_user or None)
        snap = take_snapshot(ref, env)
    except (PrReadError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"pr-ready error: {exc}", file=sys.stderr)
        return 2
    report = build_report(snap, _options(args))
    print(json.dumps(asdict(report), indent=2) if args.json else format_text(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
