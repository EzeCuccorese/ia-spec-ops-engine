"""Hermetic tests for ``ai-governance pr-ready`` (no network, no real gh)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from ai_governance import cli
from ai_governance.tools import pr_ready

URL = "https://github.com/acme/widgets/pull/7"
HEAD = "a" * 40
OTHER_HEAD = "b" * 40
TIP = "c" * 40
UNSET: Any = object()
MISSING: Any = object()


def run_node(
    name: str,
    status: Any = "COMPLETED",
    conclusion: Any = "SUCCESS",
    app_id: int | None = 100,
    suite: Any = UNSET,
) -> dict:
    node = {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "checkSuite": {"app": {"name": "ci-app", "databaseId": app_id}},
    }
    if suite is not UNSET:
        node["checkSuite"] = suite
    return node


def status_node(context: str, state: Any = "SUCCESS") -> dict:
    return {"__typename": "StatusContext", "context": context, "state": state}


def thread_node(thread_id: str, resolved: bool = False, outdated: bool = False) -> dict:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": {"nodes": [{"author": {"login": "reviewer"}}]},
    }


def container(nodes: Any, next_cursor: str | None = None) -> dict:
    return {
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
        "nodes": nodes,
    }


def classic(context: str, app_id: int | None = None, pinned: bool = False) -> dict:
    app = {"databaseId": app_id} if pinned else None
    return {"context": context, "app": app}


def ruleset(*entries: dict) -> dict:
    return {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": list(entries)},
    }


def branch_body(*contexts: str, checks: list[dict] | None = None) -> dict:
    required = {"contexts": list(contexts), "checks": checks or []}
    protection = {"required_status_checks": required}
    return {"protected": True, "protection": protection, "commit": {"sha": TIP}}


@dataclass
class Scenario:
    mergeable: str = "MERGEABLE"
    review_decision: str | None = "APPROVED"
    draft: bool = False
    classic_checks: Any = field(default_factory=lambda: [classic("build")])
    classic_rule: Any = UNSET
    pull_patch: dict = field(default_factory=dict)
    patch_after: dict = field(default_factory=dict)
    head_after: str = HEAD
    base_after: str = "main"
    tip_after: str = TIP
    branch: Any = field(default_factory=lambda: {"protected": False, "commit": {"sha": TIP}})
    branch_error: bool = False
    rules_pages: list[Any] = field(default_factory=lambda: [[]])
    rules_error: bool = False
    check_pages: list[list[dict]] = field(default_factory=lambda: [[run_node("build")]])
    check_containers: list[Any] | None = None
    rollup_missing: bool = False
    rollup_null_from_page: int | None = None
    check_oids: list[str] = field(default_factory=lambda: [HEAD, HEAD])
    thread_pages: list[list[dict]] = field(default_factory=lambda: [[]])
    threads_container: Any = UNSET
    endless_threads: bool = False
    errors_on: frozenset = frozenset()


class FakeGh:
    """Serves canned replies and rejects calls that do not pin the host or skip a cursor."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.calls: list[list[str]] = []
        self.counts: dict[str, int] = {}

    def __call__(self, args: list[str], env: dict[str, str]) -> str:
        assert args[:3] == ["api", "--hostname", pr_ready.HOST], args
        self.calls.append(args)
        if args[3] != "graphql":
            return self._rest(args)
        query = next(a for a in args if a.startswith("query="))
        cursor = next((a[6:] for a in args if a.startswith("after=")), None)
        if "headRefOid" in query:
            kind, pull = "meta", self._meta()
        elif "statusCheckRollup" in query:
            kind, pull = "checks", self._checks(cursor)
        else:
            kind, pull = "threads", {"reviewThreads": self._threads(cursor)}
        body: dict = {"data": {"repository": {"pullRequest": pull}}}
        if (kind, self.counts[kind]) in self.scenario.errors_on:
            body["errors"] = [{"message": "partial"}]
        return json.dumps(body)

    def _count(self, kind: str) -> int:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return self.counts[kind]

    def _meta(self) -> dict:
        s = self.scenario
        read = self._count("meta")
        rule = s.classic_rule
        if rule is UNSET:
            rule = {"requiredStatusChecks": s.classic_checks}
        base_ref: dict = {
            "name": "main" if read == 1 else s.base_after,
            "target": {"oid": TIP if read == 1 else s.tip_after},
        }
        if rule is not MISSING:
            base_ref["branchProtectionRule"] = rule
        pull = {
            "isDraft": s.draft,
            "mergeable": s.mergeable,
            "reviewDecision": s.review_decision,
            "headRefOid": HEAD if read == 1 else s.head_after,
            "baseRef": base_ref,
        }
        for key, value in {**s.pull_patch, **(s.patch_after if read > 1 else {})}.items():
            if value is MISSING:
                pull.pop(key, None)
            else:
                pull[key] = value
        return pull

    def _checks(self, cursor: str | None) -> dict:
        s = self.scenario
        self._count("checks")
        index = int(cursor) if cursor else 0
        pages = s.check_containers or s.check_pages
        if s.check_containers is None:
            next_cursor = str(index + 1) if index + 1 < len(pages) else None
            body: Any = container(pages[index], next_cursor)
        else:
            body = pages[index]
        null_rollup = s.rollup_missing or (
            s.rollup_null_from_page is not None and index >= s.rollup_null_from_page
        )
        rollup = None if null_rollup else {"contexts": body}
        oid = s.check_oids[min(index, len(s.check_oids) - 1)]
        return {"commits": {"nodes": [{"commit": {"oid": oid, "statusCheckRollup": rollup}}]}}

    def _threads(self, cursor: str | None) -> Any:
        s = self.scenario
        self._count("threads")
        if s.threads_container is not UNSET:
            return s.threads_container
        if s.endless_threads:
            return container([thread_node("t")], "more")
        index = int(cursor) if cursor else 0
        next_cursor = str(index + 1) if index + 1 < len(s.thread_pages) else None
        return container(s.thread_pages[index], next_cursor)

    def _rest(self, args: list[str]) -> str:
        s = self.scenario
        route = args[-1].partition("?")[0]
        if route == "repos/acme/widgets/branches/main":
            if s.branch_error:
                raise pr_ready.PrReadError("gh api failed: 404")
            return json.dumps(s.branch)
        assert route == "repos/acme/widgets/rules/branches/main", route
        assert "--paginate" in args and "--slurp" in args, args
        if s.rules_error:
            raise pr_ready.PrReadError("gh api failed: 403")
        return json.dumps(s.rules_pages)


@dataclass(frozen=True)
class Outcome:
    code: int
    report: dict
    err: str
    gh: FakeGh


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Callable:
    def invoke(scenario: Scenario, *extra: str) -> Outcome:
        fake = FakeGh(scenario)
        monkeypatch.setattr(pr_ready, "_gh", fake)
        code = pr_ready.main([URL, "--json", *extra])
        captured = capsys.readouterr()
        report = json.loads(captured.out) if captured.out.strip() else {}
        return Outcome(code, report, captured.err, fake)

    return invoke


def verdict(out: Outcome) -> tuple[int, bool, bool, list[str]]:
    report = out.report
    return out.code, report["settled"], report["ready"], report["blockers"]


def test_all_green_is_settled_and_ready(run: Callable) -> None:
    out = run(Scenario())
    assert verdict(out) == (0, True, True, [])
    assert out.report["checks"] == [{"name": "build", "source": "ci-app", "state": "pass"}]
    assert out.report["head"] == HEAD


def test_draft_is_reported_but_does_not_block(run: Callable) -> None:
    out = run(Scenario(draft=True))
    assert verdict(out) == (0, True, True, [])
    assert out.report["draft"] is True


def test_pending_check_is_not_settled(run: Callable) -> None:
    pending = run_node("build", status="IN_PROGRESS", conclusion=None)
    out = run(Scenario(check_pages=[[pending]]))
    assert verdict(out) == (1, False, False, ["check_pending:build"])


def test_failed_check_is_settled_but_not_ready(run: Callable) -> None:
    out = run(Scenario(check_pages=[[run_node("build", conclusion="FAILURE")]]))
    assert verdict(out) == (1, True, False, ["check_failed:build"])


def test_required_check_not_reported_is_not_settled(run: Callable) -> None:
    out = run(Scenario(classic_checks=[classic("build"), classic("deploy")]))
    assert verdict(out) == (1, False, False, ["required_check_missing:deploy"])


def test_duplicate_findings_are_listed_once_and_sorted(run: Callable) -> None:
    nodes = [run_node("z", conclusion="FAILURE"), run_node("a", conclusion="FAILURE")]
    nodes += [run_node("z", conclusion="FAILURE"), run_node("build")]
    out = run(Scenario(check_pages=[nodes]))
    assert out.report["blockers"] == ["check_failed:a", "check_failed:z"]


def test_no_reported_checks_is_not_settled(run: Callable) -> None:
    out = run(Scenario(rollup_missing=True, classic_checks=[]))
    assert verdict(out) == (1, False, False, ["no_checks_reported"])


def test_no_reported_checks_accepted_with_explicit_flag(run: Callable) -> None:
    out = run(Scenario(rollup_missing=True, classic_checks=[]), "--allow-no-checks")
    assert verdict(out) == (0, True, True, [])


def test_allow_no_checks_does_not_hide_a_missing_required_check(run: Callable) -> None:
    out = run(Scenario(rollup_missing=True), "--allow-no-checks")
    assert verdict(out) == (1, False, False, ["required_check_missing:build"])


def test_required_check_on_second_rules_page_is_not_lost(run: Callable) -> None:
    other = {"type": "pull_request", "parameters": {}}
    pages = [[other, other], [ruleset({"context": "lint"})]]
    out = run(Scenario(rules_pages=pages))
    assert verdict(out) == (1, False, False, ["required_check_missing:lint"])


def test_rules_are_read_following_the_link_header(run: Callable) -> None:
    out = run(Scenario())
    rules_call = next(c for c in out.gh.calls if "rules/branches" in c[-1])
    assert rules_call[3:5] == ["--paginate", "--slurp"]


def test_rules_listing_beyond_the_page_cap_is_incomplete(
    run: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pr_ready, "MAX_PAGES", 2)
    out = run(Scenario(rules_pages=[[], [], [], []]))
    assert verdict(out) == (1, False, False, ["incomplete_listing"])


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(Scenario(rules_error=True), id="rules-api-denied-classic-readable"),
        pytest.param(Scenario(branch_error=True), id="branch-endpoint-unreadable"),
        pytest.param(Scenario(branch={"message": "Not Found"}), id="branch-without-protected-flag"),
        pytest.param(Scenario(branch={"protected": True}), id="protected-without-protection"),
        pytest.param(
            Scenario(branch={"protected": True, "protection": {}}), id="protection-without-checks"
        ),
        pytest.param(Scenario(classic_rule={"requiredStatusChecks": None}), id="classic-null-list"),
        pytest.param(Scenario(rules_pages=[{"message": "oops"}]), id="rules-not-a-list"),
        pytest.param(
            Scenario(rules_pages=[[{"type": "required_status_checks"}]]), id="rule-no-params"
        ),
        pytest.param(
            Scenario(
                rules_pages=[[{"parameters": {"required_status_checks": [{"context": "x"}]}}]]
            ),
            id="rule-without-type",
        ),
        pytest.param(Scenario(rules_pages=[[None]]), id="rule-null-element"),
        pytest.param(Scenario(classic_checks=[{"context": None}]), id="classic-nameless-entry"),
        pytest.param(Scenario(classic_rule=MISSING), id="classic-rule-key-missing"),
    ],
)
def test_unreadable_required_checks_are_unknown(run: Callable, scenario: Scenario) -> None:
    out = run(scenario)
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


def test_graphql_null_rule_alone_proves_nothing_without_the_branch_read(run: Callable) -> None:
    out = run(Scenario(classic_rule=None, branch_error=True))
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


def test_unprotected_branch_proves_there_is_no_classic_protection(run: Callable) -> None:
    branch = {"protected": False, "commit": {"sha": TIP}}
    out = run(Scenario(classic_rule=None, branch=branch))
    assert verdict(out) == (0, True, True, [])


def test_protected_branch_required_checks_come_from_the_branch_endpoint(run: Callable) -> None:
    scenario = Scenario(classic_rule=None, branch=branch_body("build", "deploy"))
    out = run(scenario)
    assert verdict(out) == (1, False, False, ["required_check_missing:deploy"])


def test_protected_branch_without_required_checks_has_none(run: Callable) -> None:
    protection = {"required_status_checks": None}
    body = {"protected": True, "protection": protection, "commit": {"sha": TIP}}
    out = run(Scenario(classic_rule=None, branch=body))
    assert verdict(out) == (0, True, True, [])


def test_branch_endpoint_app_id_of_the_wrong_type_is_not_any_source(run: Callable) -> None:
    body = branch_body(checks=[{"context": "build", "app_id": "999"}])
    out = run(Scenario(classic_rule=None, branch=body))
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


@pytest.mark.parametrize(
    ("app_id", "ready"),
    [pytest.param(None, True, id="null-means-any-source"), pytest.param(-1, True, id="negative")],
)
def test_branch_endpoint_app_id_without_a_pin_means_any_source(
    run: Callable, app_id: int | None, ready: bool
) -> None:
    body = branch_body(checks=[{"context": "build", "app_id": app_id}])
    out = run(Scenario(classic_rule=None, branch=body))
    assert verdict(out) == (0, ready, ready, [])


def test_branch_endpoint_without_the_checks_key_is_unknown(run: Callable) -> None:
    body = branch_body("build")
    del body["protection"]["required_status_checks"]["checks"]
    out = run(Scenario(classic_rule=None, branch=body))
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


def test_slurped_rules_result_with_no_page_is_unknown(run: Callable) -> None:
    out = run(Scenario(rules_pages=[]))
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


def test_required_workflows_ruleset_is_unknown(run: Callable) -> None:
    workflows = {"type": "workflows", "parameters": {"workflows": []}}
    out = run(Scenario(rules_pages=[[workflows]]))
    assert verdict(out) == (1, False, False, ["required_checks_unknown"])


@pytest.mark.parametrize(
    "commit",
    [
        pytest.param({"sha": OTHER_HEAD}, id="different-tip"),
        pytest.param({}, id="sha-missing"),
        pytest.param(None, id="commit-missing"),
    ],
)
def test_branch_endpoint_tip_must_match_the_metadata_tip(run: Callable, commit: Any) -> None:
    body: dict = {"protected": False}
    if commit is not None:
        body["commit"] = commit
    out = run(Scenario(branch=body))
    assert verdict(out) == (1, False, False, ["head_moved"])


@pytest.mark.parametrize(
    "patch",
    [
        pytest.param({"headRefOid": "not-a-sha"}, id="head-not-hex"),
        pytest.param({"headRefOid": "A" * 40}, id="head-uppercase"),
        pytest.param({"headRefOid": "a" * 39}, id="head-too-short"),
        pytest.param(
            {
                "baseRef": {
                    "name": "main",
                    "target": {"oid": "zz"},
                    "branchProtectionRule": {"requiredStatusChecks": []},
                }
            },
            id="base-tip-not-hex",
        ),
    ],
)
def test_commit_ids_must_be_hex_of_a_known_length(run: Callable, patch: dict) -> None:
    out = run(Scenario(pull_patch=patch))
    assert out.code == 1
    assert out.report["settled"] is False
    assert out.report["ready"] is False
    assert "incomplete_listing" in out.report["blockers"]


def test_sha256_commit_ids_are_accepted(run: Callable) -> None:
    long_head = "d" * 64
    scenario = Scenario(
        pull_patch={"headRefOid": long_head}, check_oids=[long_head], head_after=long_head
    )
    assert verdict(run(scenario)) == (0, True, True, [])


def test_required_review_does_not_block_ready_and_is_reported(run: Callable) -> None:
    out = run(Scenario(review_decision="REVIEW_REQUIRED"))
    assert verdict(out) == (0, True, True, [])
    assert out.report["review_decision"] == "REVIEW_REQUIRED"


def test_branch_endpoint_pins_required_checks_to_an_app(run: Callable) -> None:
    body = branch_body(checks=[{"context": "build", "app_id": 999}])
    out = run(Scenario(classic_rule=None, branch=body))
    assert verdict(out) == (1, False, False, ["required_check_missing:build"])


@pytest.mark.parametrize(
    ("required", "check", "satisfied"),
    [
        pytest.param(
            classic("build", 123, True), run_node("build", app_id=123), True, id="same-app"
        ),
        pytest.param(
            classic("build", 123, True), run_node("build", app_id=456), False, id="other-app"
        ),
        pytest.param(
            classic("build", 123, True),
            run_node("build", app_id=None),
            False,
            id="check-app-unknown",
        ),
        pytest.param(
            classic("build", None, True), run_node("build", app_id=123), False, id="pin-id-unknown"
        ),
        pytest.param(
            classic("build", 123, True), status_node("build"), False, id="status-has-no-app"
        ),
        pytest.param(classic("build"), run_node("build", app_id=456), True, id="unpinned-any-app"),
    ],
)
def test_classic_requirement_pinned_to_an_app(
    run: Callable, required: dict, check: dict, satisfied: bool
) -> None:
    out = run(Scenario(classic_checks=[required], check_pages=[[check]]))
    expected = [] if satisfied else ["required_check_missing:build"]
    assert verdict(out) == (0 if satisfied else 1, satisfied, satisfied, expected)


@pytest.mark.parametrize(
    ("integration_id", "check_app", "satisfied"),
    [
        pytest.param(123, 123, True, id="same-app"),
        pytest.param(123, 456, False, id="other-app"),
        pytest.param(123, None, False, id="check-app-unknown"),
        pytest.param("junk", 123, False, id="pin-not-comparable"),
    ],
)
def test_ruleset_requirement_pinned_to_an_integration(
    run: Callable, integration_id: object, check_app: int | None, satisfied: bool
) -> None:
    rules = [[ruleset({"context": "lint", "integration_id": integration_id})]]
    nodes = [run_node("build"), run_node("lint", app_id=check_app)]
    out = run(Scenario(rules_pages=rules, check_pages=[nodes]))
    expected = [] if satisfied else ["required_check_missing:lint"]
    assert verdict(out) == (0 if satisfied else 1, satisfied, satisfied, expected)


def test_mergeable_unknown_is_not_settled(run: Callable) -> None:
    out = run(Scenario(mergeable="UNKNOWN"))
    assert verdict(out) == (1, False, False, ["mergeable_unknown"])


def test_conflict_blocks_but_is_settled(run: Callable) -> None:
    out = run(Scenario(mergeable="CONFLICTING"))
    assert verdict(out) == (1, True, False, ["conflict"])


def test_changes_requested_blocks(run: Callable) -> None:
    out = run(Scenario(review_decision="CHANGES_REQUESTED"))
    assert verdict(out) == (1, True, False, ["changes_requested"])


@pytest.mark.parametrize(
    ("threads", "extra", "expected_blockers", "expected_ids"),
    [
        pytest.param([thread_node("T1")], (), ["threads_unresolved:1"], ["T1"], id="unresolved"),
        pytest.param([thread_node("T1")], ("--ignore-threads", "T1"), [], [], id="ignored"),
        pytest.param([thread_node("T1", resolved=True)], (), [], [], id="resolved"),
        pytest.param(
            [thread_node("T1"), thread_node("T2", outdated=True)],
            ("--ignore-threads", "T1, X"),
            ["threads_unresolved:1"],
            ["T2"],
            id="partly-ignored-outdated",
        ),
    ],
)
def test_review_threads(
    run: Callable,
    threads: list[dict],
    extra: tuple[str, ...],
    expected_blockers: list[str],
    expected_ids: list[str],
) -> None:
    out = run(Scenario(thread_pages=[threads]), *extra)
    assert verdict(out) == (
        1 if expected_blockers else 0,
        True,
        not expected_blockers,
        expected_blockers,
    )
    assert [t["id"] for t in out.report["unresolved_threads"]] == expected_ids


def test_unresolved_thread_reports_author_and_outdated(run: Callable) -> None:
    out = run(Scenario(thread_pages=[[thread_node("T1", outdated=True)]]))
    assert out.report["unresolved_threads"] == [
        {"id": "T1", "author": "reviewer", "outdated": True}
    ]


@pytest.mark.parametrize(
    ("scenario", "args", "blocked"),
    [
        pytest.param(Scenario(), (), False, id="no-expectation"),
        pytest.param(Scenario(), ("--head", HEAD), False, id="matches"),
        pytest.param(Scenario(), ("--head", HEAD[:7]), False, id="short-sha-prefix"),
        pytest.param(Scenario(), ("--head", OTHER_HEAD), True, id="caller-head-is-stale"),
        pytest.param(Scenario(check_oids=[OTHER_HEAD]), (), True, id="checks-read-another-head"),
        pytest.param(
            Scenario(
                check_pages=[[run_node("build")], [run_node("lint")]], check_oids=[HEAD, OTHER_HEAD]
            ),
            (),
            True,
            id="head-changed-between-check-pages",
        ),
        pytest.param(Scenario(head_after=OTHER_HEAD), (), True, id="push-after-last-read"),
        pytest.param(
            Scenario(pull_patch={"headRefOid": None}, head_after=""), (), True, id="no-head-sha"
        ),
        pytest.param(
            Scenario(pull_patch={"headRefOid": ""}, check_oids=[""], head_after=""),
            (),
            True,
            id="empty-heads-never-match",
        ),
    ],
)
def test_head_moved_is_never_settled(
    run: Callable, scenario: Scenario, args: tuple[str, ...], blocked: bool
) -> None:
    out = run(scenario, *args)
    assert ("head_moved" in out.report["blockers"]) is blocked
    assert out.code == (1 if blocked else 0)
    assert out.report["settled"] is not blocked
    assert out.report["ready"] is not blocked


def test_base_branch_change_during_the_read_is_head_moved(run: Callable) -> None:
    out = run(Scenario(base_after="develop"))
    assert verdict(out) == (1, False, False, ["head_moved"])


def test_base_branch_tip_moving_during_the_read_is_head_moved(run: Callable) -> None:
    out = run(Scenario(tip_after=OTHER_HEAD))
    assert verdict(out) == (1, False, False, ["head_moved"])


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        pytest.param({"reviewDecision": "CHANGES_REQUESTED"}, ["changes_requested"], id="review"),
        pytest.param({"mergeable": "CONFLICTING"}, ["conflict"], id="conflict"),
        pytest.param({"mergeable": "UNKNOWN"}, ["mergeable_unknown"], id="mergeable-unknown"),
    ],
)
def test_verdict_uses_the_last_metadata_read(
    run: Callable, patch: dict, expected: list[str]
) -> None:
    out = run(Scenario(patch_after=patch))
    assert out.code == 1
    assert out.report["blockers"] == expected
    assert out.report["ready"] is False


def test_no_review_required_is_a_valid_explicit_null(run: Callable) -> None:
    assert verdict(run(Scenario(review_decision=None))) == (0, True, True, [])


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(Scenario(threads_container=None), id="null-threads-connection"),
        pytest.param(
            Scenario(threads_container={"pageInfo": {"hasNextPage": False}}), id="null-nodes"
        ),
        pytest.param(Scenario(threads_container={"nodes": []}), id="missing-page-info"),
        pytest.param(
            Scenario(threads_container={"pageInfo": {}, "nodes": []}), id="missing-has-next-page"
        ),
        pytest.param(
            Scenario(threads_container=container([thread_node("T1"), None])), id="null-element"
        ),
        pytest.param(
            Scenario(threads_container=container([{"id": "T1", "isResolved": "no"}])),
            id="thread-without-flags",
        ),
        pytest.param(
            Scenario(threads_container=container([thread_node("T1")], "")), id="next-page-no-cursor"
        ),
        pytest.param(Scenario(check_containers=[None]), id="null-checks-connection"),
        pytest.param(
            Scenario(check_containers=[container([run_node("build"), 5])]), id="check-not-object"
        ),
        pytest.param(Scenario(check_pages=[[run_node("")]]), id="nameless-check"),
        pytest.param(Scenario(errors_on=frozenset({("meta", 1)})), id="errors-first-metadata"),
        pytest.param(Scenario(errors_on=frozenset({("meta", 2)})), id="errors-only-final-reread"),
        pytest.param(
            Scenario(
                thread_pages=[[], [], []],
                errors_on=frozenset({("threads", 2)}),
            ),
            id="errors-only-middle-thread-page",
        ),
        pytest.param(
            Scenario(
                check_pages=[[run_node("build")], [run_node("a")], [run_node("b")]],
                errors_on=frozenset({("checks", 2)}),
            ),
            id="errors-only-middle-check-page",
        ),
        pytest.param(Scenario(patch_after={"isDraft": MISSING}), id="final-reread-field-absent"),
        pytest.param(
            Scenario(
                check_pages=[[run_node("build")], [run_node("lint")]], rollup_null_from_page=1
            ),
            id="rollup-vanishes-on-continuation-page",
        ),
        pytest.param(
            Scenario(check_pages=[[run_node("build", suite={})]]), id="check-app-key-absent"
        ),
        pytest.param(
            Scenario(check_pages=[[run_node("build", suite={"app": {"name": "x"}})]]),
            id="check-app-id-key-absent",
        ),
        pytest.param(Scenario(pull_patch={"reviewDecision": MISSING}), id="review-decision-absent"),
        pytest.param(
            Scenario(pull_patch={"reviewDecision": ["APPROVED"]}), id="review-decision-list"
        ),
        pytest.param(
            Scenario(pull_patch={"reviewDecision": "SOMETHING_NEW"}), id="review-decision-unknown"
        ),
        pytest.param(
            Scenario(pull_patch={"mergeable": "SOMETHING_NEW"}), id="mergeable-unknown-enum"
        ),
        pytest.param(Scenario(pull_patch={"isDraft": MISSING}), id="is-draft-absent"),
        pytest.param(
            Scenario(check_pages=[[run_node("build", conclusion=["x"])]]), id="conclusion-list"
        ),
        pytest.param(
            Scenario(check_pages=[[run_node("build", conclusion="WEIRD")]]), id="conclusion-unknown"
        ),
        pytest.param(
            Scenario(check_pages=[[run_node("build", status={"a": 1})]]), id="status-object"
        ),
        pytest.param(Scenario(check_pages=[[status_node("build", ["SUCCESS"])]]), id="state-list"),
        pytest.param(Scenario(endless_threads=True), id="threads-beyond-page-cap"),
    ],
)
def test_malformed_or_truncated_listings_are_incomplete(run: Callable, scenario: Scenario) -> None:
    out = run(scenario)
    assert out.code == 1
    assert out.report["settled"] is False
    assert out.report["ready"] is False
    assert "incomplete_listing" in out.report["blockers"]
    assert not any(b.endswith(":") or b.endswith(":None") for b in out.report["blockers"])


def test_missing_head_sha_is_incomplete(run: Callable) -> None:
    out = run(Scenario(pull_patch={"headRefOid": None}, head_after=""))
    assert out.report["settled"] is False
    assert {"incomplete_listing", "head_moved"} <= set(out.report["blockers"])


def test_checks_and_threads_are_paginated_across_two_pages(run: Callable) -> None:
    pages = [[run_node("build")], [status_node("ci/deploy", "PENDING")]]
    threads = [[thread_node("T1", resolved=True)], [thread_node("T2")]]
    scenario = Scenario(
        check_pages=pages, thread_pages=threads, classic_checks=[classic("ci/deploy")]
    )
    out = run(scenario)
    assert verdict(out) == (1, False, False, ["check_pending:ci/deploy", "threads_unresolved:1"])
    assert out.report["checks"][1] == {"name": "ci/deploy", "source": "ci", "state": "pending"}
    cursors = [a for call in out.gh.calls for a in call if a.startswith("after=")]
    assert cursors == ["after=1", "after=1"]


@pytest.mark.parametrize(
    ("node", "state"),
    [
        pytest.param(run_node("n", conclusion="SKIPPED"), "pass", id="skipped-run"),
        pytest.param(run_node("n", conclusion="TIMED_OUT"), "fail", id="timed-out-run"),
        pytest.param(run_node("n", conclusion="STALE"), "pending", id="unknown-conclusion"),
        pytest.param(run_node("n", status="QUEUED", conclusion=None), "pending", id="queued-run"),
        pytest.param(status_node("n", "ERROR"), "fail", id="error-status"),
        pytest.param(status_node("n", "EXPECTED"), "pending", id="expected-status"),
    ],
)
def test_check_states(node: dict, state: str) -> None:
    check = pr_ready.parse_check(node)
    assert check is not None
    assert check.state == state


def test_every_gh_call_pins_the_host_even_when_gh_host_is_set(
    run: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_HOST", "evil.example.com")
    out = run(Scenario())
    assert out.code == 0
    assert out.gh.calls
    assert all(call[:3] == ["api", "--hostname", "github.com"] for call in out.gh.calls)


def test_bad_url_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pr_ready, "_gh", FakeGh(Scenario()))
    assert pr_ready.main(["https://example.com/not-a-pr"]) == 2
    assert "not a pull request URL" in capsys.readouterr().err


def test_gh_failure_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(args: list[str], env: dict[str, str]) -> str:
        raise pr_ready.PrReadError("gh api failed: boom")

    monkeypatch.setattr(pr_ready, "_gh", broken)
    assert pr_ready.main([URL]) == 2
    assert "boom" in capsys.readouterr().err


def test_missing_pull_request_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pr_ready, "_gh", lambda args, env: json.dumps({"data": {}}))
    assert pr_ready.main([URL]) == 2
    assert "not found" in capsys.readouterr().err


def test_text_output_lists_verdict_and_blockers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pr_ready, "_gh", FakeGh(Scenario(mergeable="CONFLICTING")))
    assert pr_ready.main([URL]) == 1
    out = capsys.readouterr().out
    assert "not ready" in out
    assert "blocker: conflict" in out


def test_public_dispatcher_runs_pr_ready(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pr_ready, "_gh", FakeGh(Scenario()))
    assert "pr-ready" in cli.COMMANDS
    assert cli.main(["pr-ready", URL, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    monkeypatch.setattr(pr_ready, "_gh", FakeGh(Scenario(mergeable="CONFLICTING")))
    assert cli.main(["pr-ready", URL, "--json"]) == 1


def test_gh_user_is_passed_to_the_credential_lookup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str | None] = []

    def fake_env(user: str | None) -> dict[str, str]:
        seen.append(user)
        return {"GH_TOKEN": "token-for-" + (user or "default")}

    tokens: list[str] = []

    def fake_gh(args: list[str], env: dict[str, str]) -> str:
        tokens.append(env["GH_TOKEN"])
        return FakeGh(Scenario())(args, env)

    monkeypatch.setattr(pr_ready, "_gh_env", fake_env)
    monkeypatch.setattr(pr_ready, "_gh", fake_gh)
    assert pr_ready.main([URL, "--gh-user", "bot", "--json"]) == 0
    capsys.readouterr()
    assert seen == ["bot"]
    assert set(tokens) == {"token-for-bot"}
