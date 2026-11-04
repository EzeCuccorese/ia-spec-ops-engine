"""Deterministic PR status: every unknown / ambiguous / stale case, over real response shapes."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ai_governance.taskflow.prs.cache import make_entry
from ai_governance.taskflow.prs.snapshot import (
    GRAPHQL_ERRORS,
    NO_ACCESS,
    NOT_FOUND,
    RATE_LIMITED,
    UNEXPECTED,
    Parent,
    Snapshot,
    SyncError,
    ThreadExtra,
    parent_from,
    parse,
)
from ai_governance.taskflow.prs.status import (
    SYNC_HINT,
    Evaluation,
    bucket,
    classify,
    evaluate,
    summarize,
)
from prs_real_samples import (
    MERGED_47,
    OPEN_DRAFT_49,
    PARENT_FOUND,
    PARENT_NO_BRANCH,
    PR_NOT_FOUND,
    REPO,
    REPO_NOT_FOUND,
    THREADS_PAGE_1,
    THREADS_PAGE_2,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def iso(hours_ago: float = 0, seconds: int = 0) -> str:
    return (NOW - timedelta(hours=hours_ago, seconds=-seconds)).isoformat(timespec="seconds")


def pr_of(response: dict[str, Any]) -> dict[str, Any]:
    return response["data"]["repository"]["pullRequest"]


def ci_node(state: str | None) -> dict[str, Any]:
    rollup = None if state is None else {"state": state}
    return {"nodes": [{"commit": {"statusCheckRollup": rollup}}]}


def healthy(**changes: Any) -> dict[str, Any]:
    """The real open-PR response, made non-draft and green, with fields overridden."""
    data = deepcopy(OPEN_DRAFT_49)
    pr_of(data).update({"isDraft": False, "commits": ci_node("SUCCESS"), **changes})
    return data


def without(key: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    data = deepcopy(base or healthy())
    del pr_of(data)[key]
    return data


def snap(response: dict[str, Any] | None = None, extra: ThreadExtra | None = None) -> Snapshot:
    result = parse(response or healthy(), extra)
    assert isinstance(result, Snapshot), result
    return result


def blockers(response: dict[str, Any], extra: ThreadExtra | None = None) -> tuple[str, ...]:
    return classify(snap(response, extra))


def threads(nodes: list[bool], more: bool = False) -> dict[str, Any]:
    return {
        "totalCount": len(nodes),
        "pageInfo": {"hasNextPage": more, "endCursor": "c"},
        "nodes": [{"isResolved": flag} for flag in nodes],
    }


# -- the real shapes ------------------------------------------------------------------------
def test_real_open_draft_response_is_parsed_and_classified() -> None:
    result = snap(OPEN_DRAFT_49)
    assert (result.state, result.is_draft, result.base, result.default_branch) == (
        "OPEN",
        True,
        "main",
        "main",
    )
    assert (result.ci, result.review, result.mergeable) == ("running", "ok", "ok")
    assert (result.threads_open, result.threads_incomplete, result.head_repo) == (0, False, REPO)
    assert classify(result) == ("draft", "ci-running")


def test_real_merged_response_shows_state_only() -> None:
    result = snap(MERGED_47)
    assert result.state == "MERGED"
    assert result.mergeable == "unknown"  # GitHub reports UNKNOWN for merged PRs
    assert classify(result) == ()
    shown = evaluate(make_entry(result, iso(100)), NOW)
    assert (shown.state, shown.ready, shown.stale, shown.blockers) == ("merged", False, False, ())


def test_real_thread_pages_keep_their_shape() -> None:
    first = snap(THREADS_PAGE_1)  # hasNextPage true, nothing counted yet
    assert (first.threads_open, first.threads_incomplete) == (None, True)
    done = snap(THREADS_PAGE_1, ThreadExtra(0, complete=True))
    assert (done.threads_open, done.threads_incomplete) == (0, False)
    last = snap(THREADS_PAGE_2)
    assert (last.threads_open, last.threads_incomplete) == (0, False)


# -- ci / review / mergeable ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("rollup", "expected"),
    [
        ("FAILURE", ("ci-failed",)),
        ("ERROR", ("ci-failed",)),
        ("PENDING", ("ci-running",)),
        ("EXPECTED", ("ci-running",)),
        ("SUCCESS", ()),
        (None, ()),
        ("WEIRD", ("unknown-ci",)),
    ],
)
def test_ci_dimension(rollup: str | None, expected: tuple[str, ...]) -> None:
    assert blockers(healthy(commits=ci_node(rollup))) == expected


@pytest.mark.parametrize(
    "commits",
    [
        {"nodes": [{"commit": {}}]},
        {"nodes": "x"},
        {"nodes": [{"commit": {"statusCheckRollup": {"state": 5}}}]},
        {"nodes": [{"commit": None}]},
        5,
    ],
)
def test_ci_shape_problems_are_unknown_never_ok(commits: Any) -> None:
    assert blockers(healthy(commits=commits)) == ("unknown-ci",)


def test_no_commits_means_no_checks_but_a_missing_key_is_unknown() -> None:
    assert blockers(healthy(commits={"nodes": []})) == ()
    assert blockers(without("commits")) == ("unknown-ci",)


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("CHANGES_REQUESTED", ("changes-requested",)),
        ("REVIEW_REQUIRED", ("needs-approval",)),
        ("APPROVED", ()),
        (None, ()),
        ("WEIRD", ("unknown-review",)),
    ],
)
def test_review_dimension(decision: str | None, expected: tuple[str, ...]) -> None:
    assert blockers(healthy(reviewDecision=decision)) == expected


def test_review_decision_null_is_ok_but_a_missing_key_is_unknown() -> None:
    assert blockers(healthy(reviewDecision=None)) == ()
    assert blockers(without("reviewDecision")) == ("unknown-review",)


@pytest.mark.parametrize(
    ("mergeable", "expected"),
    [("MERGEABLE", ()), ("CONFLICTING", ("conflict",)), ("UNKNOWN", ("unknown-mergeable",))],
)
def test_mergeable_dimension(mergeable: str, expected: tuple[str, ...]) -> None:
    assert blockers(healthy(mergeable=mergeable)) == expected


def test_unknown_mergeable_is_visible_everywhere_and_never_ready() -> None:
    result = snap(healthy(mergeable="UNKNOWN"))
    assert result.to_dict()["mergeable"] == "unknown"  # shown in --json
    shown = evaluate(make_entry(result, iso(1)), NOW)
    assert shown.blockers == ("unknown-mergeable",)
    assert not shown.ready
    assert blockers(without("mergeable")) == ("unknown-mergeable",)  # never invented as a conflict


def test_a_healthy_fresh_pr_is_ready() -> None:
    shown = evaluate(make_entry(snap(), iso(1)), NOW)
    assert (shown.state, shown.blockers, shown.ready, shown.stale, shown.age_s) == (
        "open",
        (),
        True,
        False,
        3600,
    )


# -- whole-response failures ----------------------------------------------------------------
def test_graphql_errors_with_partial_data_are_a_sync_error() -> None:
    partial = healthy()
    partial["errors"] = [{"type": "FORBIDDEN", "message": "Resource not accessible"}]
    assert parse(partial) == SyncError(GRAPHQL_ERRORS)


def test_real_not_found_responses_map_to_fixed_codes() -> None:
    assert parse(PR_NOT_FOUND) == SyncError(NOT_FOUND)
    assert parse(REPO_NOT_FOUND) == SyncError(NO_ACCESS)
    limited = {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "x"}]}
    assert parse(limited) == SyncError(RATE_LIMITED)


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        "text",
        {},
        {"data": None},
        {"data": {"repository": None}},
        {"data": {"repository": {}}},
    ],
)
def test_unexpected_envelopes_are_sync_errors(response: Any) -> None:
    assert parse(response) == SyncError(UNEXPECTED)


MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "state-unknown": lambda pr: pr.update(state="WEIRD"),
    "state-lowercase": lambda pr: pr.update(state="open"),
    "state-missing": lambda pr: pr.pop("state"),
    "draft-string": lambda pr: pr.update(isDraft="false"),
    "draft-missing": lambda pr: pr.pop("isDraft"),
    "base-number": lambda pr: pr.update(baseRefName=5),
    "base-empty": lambda pr: pr.update(baseRefName=""),
    "head-missing": lambda pr: pr.pop("headRefName"),
    "head-repository-missing": lambda pr: pr.pop("headRepository"),
    "head-repository-wrong-type": lambda pr: pr.update(headRepository="x"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_wrong_typed_required_fields_fail_the_whole_snapshot(name: str) -> None:
    data = healthy()
    MUTATIONS[name](pr_of(data))
    assert parse(data) == SyncError(UNEXPECTED)


def test_missing_default_branch_fails_the_whole_snapshot() -> None:
    data = healthy()
    del data["data"]["repository"]["defaultBranchRef"]
    assert parse(data) == SyncError(UNEXPECTED)


def test_a_deleted_fork_head_is_allowed() -> None:
    assert snap(healthy(headRepository=None)).head_repo == ""


# -- threads --------------------------------------------------------------------------------
def test_unresolved_threads_are_counted() -> None:
    reviewed = healthy(reviewThreads=threads([False, True, False]))
    assert blockers(reviewed) == ("2-open-threads",)
    assert blockers(healthy(reviewThreads=threads([True, True]))) == ()


def test_incomplete_pagination_is_flagged_with_a_plus() -> None:
    page = healthy(reviewThreads=threads([False, False, False], more=True))
    assert blockers(page, ThreadExtra(2, complete=False)) == ("5+-open-threads",)
    assert blockers(page, ThreadExtra(2, complete=True)) == ("5-open-threads",)


def test_nothing_counted_and_incomplete_is_unknown_threads() -> None:
    page = healthy(reviewThreads=threads([True], more=True))
    result = snap(page)
    assert (result.threads_open, result.threads_incomplete) == (None, True)
    assert classify(result) == ("unknown-threads",)


@pytest.mark.parametrize(
    "block",
    [
        {"totalCount": 1, "pageInfo": {"hasNextPage": False}, "nodes": [{"isResolved": "yes"}]},
        {"totalCount": 1, "pageInfo": {"hasNextPage": False}, "nodes": "x"},
        {"totalCount": 1, "nodes": []},
        None,
    ],
)
def test_malformed_threads_are_unknown(block: Any) -> None:
    assert blockers(healthy(reviewThreads=block)) == ("unknown-threads",)
    assert blockers(without("reviewThreads")) == ("unknown-threads",)


# -- ordering of the vocabulary -------------------------------------------------------------
def _snapshot(**changes: Any) -> Snapshot:
    base: dict[str, Any] = {
        "state": "OPEN",
        "is_draft": False,
        "base": "main",
        "head": "h",
        "default_branch": "main",
        "head_repo": "o/r",
        "title": "t",
        "ci": "ok",
        "review": "ok",
        "mergeable": "ok",
        "threads_open": 0,
    }
    return Snapshot(**{**base, **changes})


def test_blockers_come_out_in_the_documented_order() -> None:
    everything = _snapshot(
        is_draft=True,
        ci="failed",
        review="required",
        mergeable="conflicting",
        threads_open=2,
        parent=Parent("open", 7),
    )
    assert classify(everything) == (
        "draft",
        "ci-failed",
        "needs-approval",
        "conflict",
        "2-open-threads",
        "waits-on-#7",
    )
    running = _snapshot(ci="running", review="changes")
    assert classify(running) == ("ci-running", "changes-requested")


def test_unknowns_come_after_the_known_blockers() -> None:
    unknown = _snapshot(
        ci="unknown",
        review="unknown",
        mergeable="unknown",
        threads_open=None,
        parent=Parent("unknown"),
    )
    assert classify(unknown) == (
        "unknown-ci",
        "unknown-review",
        "unknown-mergeable",
        "unknown-threads",
        "unknown-parent",
    )
    mixed = _snapshot(ci="failed", review="unknown", parent=Parent("closed", 9))
    assert classify(mixed) == ("ci-failed", "parent-closed-#9", "unknown-review")


@pytest.mark.parametrize(
    ("parent", "expected"),
    [
        (Parent("none"), ()),
        (Parent("merged"), ()),
        (Parent("open", 7), ("waits-on-#7",)),
        (Parent("closed", 7), ("parent-closed-#7",)),
        (Parent("ambiguous"), ("ambiguous-parent",)),
        (Parent("unknown"), ("unknown-parent",)),
    ],
)
def test_parent_blockers(parent: Parent, expected: tuple[str, ...]) -> None:
    assert classify(_snapshot(parent=parent)) == expected


def test_merged_and_closed_pull_requests_have_no_blockers() -> None:
    noisy = {"is_draft": True, "ci": "failed", "review": "required", "parent": Parent("open", 3)}
    assert classify(_snapshot(state="MERGED", **noisy)) == ()
    assert classify(_snapshot(state="CLOSED", **noisy)) == ()


# -- derived stacking -----------------------------------------------------------------------
def node(number: int, state: str, head_repo: str = "o/r") -> dict[str, Any]:
    return {"number": number, "state": state, "headRepository": {"nameWithOwner": head_repo}}


def parents(nodes: list[dict[str, Any]], more: Any = False, ref: bool = True) -> dict[str, Any]:
    block = {"nodes": nodes, "pageInfo": {"hasNextPage": more}}
    return {"data": {"repository": {"ref": {"name": "b"} if ref else None, "pullRequests": block}}}


PARENT_CASES = {
    "one-open": (parents([node(7, "OPEN")]), Parent("open", 7)),
    "open-beats-an-older-merged": (
        parents([node(7, "OPEN"), node(3, "MERGED")]),
        Parent("open", 7),
    ),
    "head-name-case-differs": (parents([node(7, "OPEN", "O/R")]), Parent("open", 7)),
    "merged-only": (parents([node(7, "MERGED")]), Parent("merged")),
    "closed-and-merged": (parents([node(7, "CLOSED"), node(3, "MERGED")]), Parent("merged")),
    "closed-only": (parents([node(7, "CLOSED")]), Parent("closed", 7)),
    "two-open": (parents([node(7, "OPEN"), node(8, "OPEN")]), Parent("ambiguous")),
    "more-pages": (parents([node(7, "OPEN")], more=True), Parent("ambiguous")),
    "fork-with-the-same-branch-is-ignored": (parents([node(7, "OPEN", "fork/r")]), Parent("none")),
    "release-branch-without-a-pr": (parents([]), Parent("none")),
    "deleted-or-renamed-parent-branch": (parents([], ref=False), Parent("unknown")),
    "graphql-errors": (
        {**parents([node(7, "OPEN")]), "errors": [{"type": "X"}]},
        Parent("unknown"),
    ),
    "not-an-object": ([], Parent("unknown")),
    "pull-requests-missing": ({"data": {"repository": {"ref": None}}}, Parent("unknown")),
    "page-info-not-a-bool": (parents([node(7, "OPEN")], more="no"), Parent("unknown")),
}


@pytest.mark.parametrize("name", sorted(PARENT_CASES))
def test_parent_discovery(name: str) -> None:
    response, expected = PARENT_CASES[name]
    assert parent_from(response, "o/r") == expected


def test_untracked_parent_comes_from_github_not_from_any_registration() -> None:
    assert parent_from(PARENT_FOUND, REPO) == Parent("open", 49)


def test_real_lookup_of_a_vanished_branch_is_unknown_not_stacked() -> None:
    assert parent_from(PARENT_NO_BRANCH, REPO) == Parent("unknown")  # ref is null: B-c


# -- snapshot persistence -------------------------------------------------------------------
def test_snapshot_round_trips_through_json() -> None:
    original = snap(healthy(), ThreadExtra())
    stacked = original.with_parent(Parent("open", 4))
    assert Snapshot.from_dict(json.loads(json.dumps(stacked.to_dict()))) == stacked


@pytest.mark.parametrize(
    "data",
    ["x", None, {}, {"state": "WEIRD"}, {**_snapshot().to_dict(), "extra": 1}]
    + [
        {**_snapshot().to_dict(), **bad}
        for bad in ({"state": "WEIRD"}, {"is_draft": "x"}, {"parent": "p"})
    ]
    + [{**_snapshot().to_dict(), "parent": {"kind": "weird", "number": 1}}],
)
def test_corrupt_snapshots_are_rejected(data: Any) -> None:
    assert Snapshot.from_dict(data) is None


def test_titles_are_stored_clean() -> None:
    result = snap(healthy(title="a\nb \x1b[31mred\x1b[0m\u202e"))
    assert result.title == "a b red"
    assert snap(healthy(title="x" * 500)).title.endswith("...")


# -- freshness ------------------------------------------------------------------------------
def entry_of(response: dict[str, Any], hours_ago: float = 1, seconds: int = 0) -> dict[str, Any]:
    return make_entry(snap(response), iso(hours_ago, seconds))


def test_open_pr_older_than_six_hours_is_stale_and_not_ready() -> None:
    shown = evaluate(entry_of(healthy(), 7), NOW)
    assert (shown.stale, shown.ready, shown.blockers) == (True, False, ())
    assert shown.age_s == 7 * 3600


def test_the_stale_boundary_is_six_hours() -> None:
    assert not evaluate(entry_of(healthy(), 6), NOW).stale
    assert evaluate(entry_of(healthy(), 6, seconds=-1), NOW).stale


def test_reopened_pr_is_not_presented_as_current() -> None:
    closed = healthy(state="CLOSED")
    assert evaluate(entry_of(closed, 1), NOW).stale is False
    old = evaluate(entry_of(closed, 7), NOW)
    assert (old.state, old.stale, old.ready) == ("closed", True, False)


def test_merged_is_final_and_never_stale() -> None:
    shown = evaluate(entry_of(MERGED_47, 24 * 30), NOW)
    assert (shown.state, shown.stale) == ("merged", False)


@pytest.mark.parametrize(
    "stamp", [iso(-1), "yesterday", "", None, 12345, "2026-13-45T00:00:00"], ids=str
)
def test_future_unparsable_or_missing_synced_at_is_not_synced(stamp: Any) -> None:
    entry = {**entry_of(healthy()), "synced_at": stamp}
    shown = evaluate(entry, NOW)
    assert (shown.blockers, shown.ready, shown.age_s, shown.state) == (
        ("not-synced",),
        False,
        None,
        "unknown",
    )


def test_a_timestamp_without_a_zone_is_utc() -> None:
    entry = {**entry_of(healthy()), "synced_at": "2026-11-03T11:00:00"}
    assert evaluate(entry, NOW).age_s == 3600


def test_no_entry_is_not_synced() -> None:
    shown = evaluate(None, NOW)
    assert (shown.blockers, shown.ready, shown.snapshot) == (("not-synced",), False, None)


def test_a_failed_sync_is_a_sync_error_with_its_code() -> None:
    shown = evaluate(make_entry(SyncError(NOT_FOUND), iso(1)), NOW)
    assert (shown.blockers, shown.error, shown.ready) == (("sync-error",), NOT_FOUND, False)


def test_a_corrupt_snapshot_without_an_error_is_not_synced() -> None:
    corrupt = {"snapshot": {"state": "?"}, "error": "", "synced_at": iso(1), "gen": 1}
    assert evaluate(corrupt, NOW).blockers == ("not-synced",)


# -- summary --------------------------------------------------------------------------------
def ev(
    state: str = "open",
    blockers: tuple[str, ...] = (),
    ready: bool = False,
    stale: bool = False,
) -> Evaluation:
    return Evaluation(state, blockers, ready, stale, 60)


def test_summary_of_thirty_pull_requests_is_exact() -> None:
    items = (
        [ev("merged")] * 4
        + [ev("closed", stale=True)]
        + [ev(ready=True)] * 17
        + [ev(blockers=("needs-approval",))] * 2
        + [ev(blockers=("3-open-threads",))] * 2
        + [ev(blockers=("ci-failed",))]
        + [ev(blockers=("waits-on-#4",))]
        + [ev(blockers=("unknown-ci",))]
        + [ev("unknown", ("not-synced",))]
    )
    assert len(items) == 30
    assert summarize(items) == (
        "PRs: 30 (4 merged, 1 closed) · 17 ready · 2 needs-approval · 2 open-threads · "
        f"1 ci-failed · 1 waits-on-base · 1 unknown · 1 not-synced · {SYNC_HINT}"
    )
    assert SYNC_HINT == "stale (taskflow pr sync)"


def test_summary_edges() -> None:
    assert summarize([]) == ""
    assert summarize([ev("merged")]) == "PRs: 1 (1 merged)"
    assert summarize([ev(stale=True)]) == f"PRs: 1 · 1 stale · {SYNC_HINT}"
    assert summarize([ev(blockers=("draft", "ci-failed"))]) == "PRs: 1 · 1 draft"


@pytest.mark.parametrize(
    ("blocked", "expected"),
    [
        (("draft",), "draft"),
        (("2+-open-threads",), "open-threads"),
        (("waits-on-#3",), "waits-on-base"),
        (("parent-closed-#3",), "waits-on-base"),
        (("ambiguous-parent",), "waits-on-base"),
        (("unknown-parent",), "unknown"),
        (("sync-error",), "sync-error"),
        ((), ""),
    ],
)
def test_buckets(blocked: tuple[str, ...], expected: str) -> None:
    assert bucket(blocked) == expected
