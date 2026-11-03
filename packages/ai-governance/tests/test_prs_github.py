"""The GitHub reader against a fake ``gh`` that replays the REAL captured response shapes."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from ai_governance.taskflow import prs
from ai_governance.taskflow.prs.cache import make_entry
from ai_governance.taskflow.prs.github import (
    PARENT_QUERY,
    PR_QUERY,
    Gh,
    check_argv,
)
from ai_governance.taskflow.prs.origin import infer_repo, parse_remote, ssh_hostname
from ai_governance.taskflow.prs.refs import PrRef
from ai_governance.taskflow.prs.snapshot import (
    GRAPHQL_ERRORS,
    NO_ACCESS,
    NO_GH,
    NOT_FOUND,
    RATE_LIMITED,
    TIMEOUT,
    UNEXPECTED,
    Snapshot,
    SyncError,
)
from ai_governance.taskflow.prs.status import classify
from gh_fakes import GhWorld, make_gh_world, normalized, spec_of
from prs_real_samples import (
    AUTH_STATUS_JSON,
    MERGED_47,
    OPEN_DRAFT_49,
    PARENT_FOUND,
    PARENT_NO_BRANCH,
    PR_NOT_FOUND,
    REPO,
    REPO_NOT_FOUND,
)

APP = "acme/app"


def setup_accounts(world: GhWorld) -> None:
    """Two logged-in accounts, as on the real machine: the first one is active."""
    world.account("EzeNube", active=True)
    world.account("EzeCuccorese")


def private_app(world: GhWorld, **spec: Any) -> None:
    """``acme/app`` is visible only to the NON-active account; PR #5 exists."""
    setup_accounts(world)
    world.repo(APP, ["EzeCuccorese"])
    world.pr(APP, 5, **spec)


def shared_app(world: GhWorld, **extra: Any) -> None:
    """``acme/app`` is visible to the active account (no token needed)."""
    setup_accounts(world)
    world.repo(APP, ["EzeNube"], **extra)


def snapshot_of(result: object) -> Snapshot:
    assert isinstance(result, Snapshot), result
    return result


def gql(world: GhWorld, query: str, *pairs: str, token: str) -> Any:
    argv = ["api", "graphql", "-f", f"query={query}"]
    for pair in pairs:
        argv += ["-F" if pair.startswith("number=") else "-f", pair]
    return json.loads(world.run_gh(*argv, token=token).stdout)


# -- the fake replays exactly what GitHub returned -------------------------------------------
def test_fake_gh_replays_the_real_samples(gh_world: GhWorld) -> None:
    setup_accounts(gh_world)
    heads = [{"number": 49, "state": "OPEN", "head": "feat-taskflow-pr-board", "head_repo": REPO}]
    gh_world.repo(REPO, ["EzeNube", "EzeCuccorese"], branches=["main", "x"], heads=heads)
    gh_world.scenario["repos"][REPO]["branches"].append("feat-taskflow-pr-board")
    gh_world.pr(REPO, 49, **spec_of(OPEN_DRAFT_49))
    gh_world.pr(REPO, 47, **spec_of(MERGED_47))
    gh_world.save()
    token = gh_world.tokens[1]
    owner, name = REPO.split("/")
    base = (f"owner={owner}", f"name={name}")

    def pr(number: int) -> Any:
        return gql(gh_world, PR_QUERY, *base, f"number={number}", token=token)

    assert normalized(pr(49)) == normalized(OPEN_DRAFT_49)
    assert normalized(pr(47)) == normalized(MERGED_47)
    assert normalized(pr(99999)) == normalized(PR_NOT_FOUND)
    found = gql(
        gh_world,
        PARENT_QUERY,
        *base,
        "base=feat-taskflow-pr-board",
        "qualified=refs/heads/feat-taskflow-pr-board",
        token=token,
    )
    assert normalized(found) == normalized(PARENT_FOUND)
    none = gql(
        gh_world,
        PARENT_QUERY,
        *base,
        "base=no-such-branch",
        "qualified=refs/heads/no-such-branch",
        token=token,
    )
    assert normalized(none) == normalized(PARENT_NO_BRANCH)
    missing = gql(
        gh_world, PR_QUERY, f"owner={owner}", "name=nope-no-such-repo-zz", "number=1", token=token
    )
    assert normalized(missing) == normalized(REPO_NOT_FOUND)
    status = json.loads(gh_world.run_gh("auth", "status", "--json", "hosts").stdout)
    assert status == AUTH_STATUS_JSON


def test_fake_gh_refuses_anything_it_does_not_implement(gh_world: GhWorld) -> None:
    setup_accounts(gh_world)
    for argv in (["pr", "merge", "1"], ["auth", "switch"], ["api", "repos/o/r"]):
        assert gh_world.run_gh(*argv).returncode == 3


# -- the real response through the reader ----------------------------------------------------
def test_fetch_reads_the_real_open_pr_shape(gh_world: GhWorld) -> None:
    setup_accounts(gh_world)
    gh_world.repo(REPO, ["EzeNube", "EzeCuccorese"])
    gh_world.pr(REPO, 49, **spec_of(OPEN_DRAFT_49))
    result = snapshot_of(gh_world.reader().fetch(PrRef(REPO, 49)))
    assert (result.state, result.is_draft, result.ci, result.threads_open) == (
        "OPEN",
        True,
        "running",
        0,
    )
    assert classify(result) == ("draft", "ci-running")
    assert len(gh_world.api_calls()) == 1
    gh_world.assert_read_only()


def test_merged_pr_costs_one_call_and_no_mergeable_retry(gh_world: GhWorld) -> None:
    setup_accounts(gh_world)
    gh_world.repo(REPO, ["EzeNube", "EzeCuccorese"])
    gh_world.pr(REPO, 47, **spec_of(MERGED_47))
    result = snapshot_of(gh_world.reader().fetch(PrRef(REPO, 47)))
    assert (result.state, result.mergeable) == ("MERGED", "unknown")
    assert len(gh_world.api_calls()) == 1
    assert gh_world.sleeps == []


# -- accounts: no switching, per-command token, nothing secret stored -------------------------
def test_other_account_repo_is_read_with_a_per_command_token_and_no_switch(
    gh_world: GhWorld,
) -> None:
    private_app(gh_world)
    reader = gh_world.reader()
    result = reader.fetch(PrRef(APP, 5))
    assert isinstance(result, Snapshot)
    assert [c["account"] for c in gh_world.api_calls()] == ["EzeNube", "EzeCuccorese"]
    assert len(gh_world.verbs("auth", "token")) == 1
    assert gh_world.verbs("auth", "switch") == []
    assert json.loads(gh_world.cache.accounts_path.read_text()) == {"acme": "EzeCuccorese"}
    gh_world.assert_read_only()
    gh_world.assert_no_secret(result, make_entry(result, "2026-01-01T00:00:00+00:00"))


def test_second_pr_of_the_same_owner_makes_no_further_token_call(gh_world: GhWorld) -> None:
    private_app(gh_world)
    gh_world.pr(APP, 6)
    reader = gh_world.reader()
    reader.fetch(PrRef(APP, 5))
    reader.fetch(PrRef(APP, 6))
    assert len(gh_world.verbs("auth", "token")) == 1  # the token is memoised in memory
    assert [c["account"] for c in gh_world.api_calls()][-1] == "EzeCuccorese"
    assert len(gh_world.api_calls()) == 3  # the learned account was tried first the second time


def test_a_new_process_starts_from_the_stored_owner_login(gh_world: GhWorld) -> None:
    private_app(gh_world)
    gh_world.reader().fetch(PrRef(APP, 5))
    before = len(gh_world.api_calls())
    snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))  # a fresh reader: tokens are not persisted
    later = gh_world.api_calls()[before:]
    assert [c["account"] for c in later] == ["EzeCuccorese"]
    assert len(gh_world.verbs("auth", "token")) == 2
    gh_world.assert_no_secret()


def test_active_account_needs_no_token_call(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5)
    snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert [c["account"] for c in gh_world.api_calls()] == ["EzeNube"]
    assert gh_world.verbs("auth", "token") == []


def test_a_repository_nobody_can_see_is_no_access_after_every_account(gh_world: GhWorld) -> None:
    setup_accounts(gh_world)
    result = gh_world.reader().fetch(PrRef("nobody/none", 1))
    assert result == SyncError(NO_ACCESS)
    assert [c["account"] for c in gh_world.api_calls()] == ["EzeNube", "EzeCuccorese"]


def test_missing_pr_in_a_visible_repo_is_not_found_after_one_call(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    assert gh_world.reader().fetch(PrRef(APP, 999)) == SyncError(NOT_FOUND)
    assert len(gh_world.api_calls()) == 1


def test_discovery_falls_back_to_the_plain_status_text(gh_world: GhWorld) -> None:
    private_app(gh_world)
    gh_world.set(status_json=False)
    snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert len(gh_world.verbs("auth", "status")) == 2  # the --json attempt, then the text
    assert [c["account"] for c in gh_world.api_calls()][-1] == "EzeCuccorese"


def test_gh_missing_is_a_sync_error_and_nothing_is_spawned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = make_gh_world(tmp_path, monkeypatch, capsys, with_gh=False)
    result = world.reader().fetch(PrRef(APP, 5))
    assert result == SyncError(NO_GH)
    assert world.calls == []
    assert make_entry(result, "2026-01-01T00:00:00+00:00")["error"] == "gh not found on PATH"
    world.assert_hermetic()


# -- B-e: clean credential environment, fixed error codes ------------------------------------
CONTAMINATION = {
    "GH_TOKEN": "gho_CONTAMINATEDTOKEN0000000000",
    "GITHUB_TOKEN": "ghp_CONTAMINATEDGITHUBTOKEN000",
    "GH_ENTERPRISE_TOKEN": "ghe_CONTAMINATEDENTERPRISE00000",  # gitleaks:allow (fake, test only)
    "GH_HOST": "evil.example.com",
}


def test_contaminated_environment_never_reaches_the_active_account_attempt(
    gh_world: GhWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5)
    for name, value in CONTAMINATION.items():
        monkeypatch.setenv(name, value)
    result = gh_world.reader().fetch(PrRef(APP, 5))
    assert isinstance(result, Snapshot)  # a leaked token would be a 401 from the fake
    assert all(call["gh_env"] == [] for call in gh_world.log())
    assert [c["account"] for c in gh_world.api_calls()] == ["EzeNube"]


def test_only_the_chosen_token_is_set_for_the_one_child_that_needs_it(
    gh_world: GhWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_app(gh_world)
    for name, value in CONTAMINATION.items():
        monkeypatch.setenv(name, value)
    result = gh_world.reader().fetch(PrRef(APP, 5))
    assert isinstance(result, Snapshot)
    by_account = {c["account"]: c["gh_env"] for c in gh_world.api_calls()}
    assert by_account == {"EzeNube": [], "EzeCuccorese": ["GH_TOKEN"]}
    assert all(call["gh_env"] == [] for call in gh_world.verbs("auth"))
    import os

    assert os.environ["GH_TOKEN"] == CONTAMINATION["GH_TOKEN"]  # the parent env is untouched


@pytest.mark.parametrize("output", ["", "not a token!!", "ghp_x\nline2", "short", "a" * 300])
def test_malformed_token_output_is_no_access_and_never_echoed(
    gh_world: GhWorld, output: str
) -> None:
    private_app(gh_world)
    gh_world.set(token_output={"EzeCuccorese": output})
    result = gh_world.reader().fetch(PrRef(APP, 5))
    assert result == SyncError(NO_ACCESS)
    assert output.strip() == "" or output.strip() not in repr(result)
    assert len(gh_world.api_calls()) == 1  # no api call was made with the bad token


def test_secret_looking_stderr_of_the_token_command_is_not_surfaced(gh_world: GhWorld) -> None:
    private_app(gh_world)
    leak = "ghp_SECRETSECRETSECRET1234567890"
    gh_world.set(token_fail={"EzeCuccorese": f"error: {leak} rejected"})
    result = gh_world.reader().fetch(PrRef(APP, 5))
    assert result == SyncError(NO_ACCESS)
    gh_world.assert_no_secret(result, make_entry(result, "2026-01-01T00:00:00+00:00"))
    assert leak not in repr(result) + gh_world.stored_text()


def test_rate_limit_stops_at_the_first_call(gh_world: GhWorld) -> None:
    private_app(gh_world)
    gh_world.set(rate_limited=True)
    assert gh_world.reader().fetch(PrRef(APP, 5)) == SyncError(RATE_LIMITED)
    assert len(gh_world.api_calls()) == 1


def test_a_hanging_gh_is_a_timeout(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5)
    gh_world.set(hang_api=3)
    assert gh_world.reader(timeout=0.5).fetch(PrRef(APP, 5)) == SyncError(TIMEOUT)


# -- malformed shapes fail closed -----------------------------------------------------------
OK_BUT_EMPTY = '{"data": {"repository": {"pullRequest": {"state": "WEIRD"}}}}'
RAW_CASES = {
    "not-json": ("not json", 0, UNEXPECTED),
    "array": ("[]", 0, UNEXPECTED),
    "null": ("null", 0, UNEXPECTED),
    "data-null": ('{"data": null}', 0, UNEXPECTED),
    "weird-state": (OK_BUT_EMPTY, 0, UNEXPECTED),
    "errors-with-partial-data": (
        '{"data": {"repository": {}}, "errors": [{"type": "FORBIDDEN"}]}',
        1,
        GRAPHQL_ERRORS,
    ),
    "rate-limited-body": ('{"errors": [{"type": "RATE_LIMITED"}]}', 0, RATE_LIMITED),
    "failure-without-body": ("oops", 1, NO_ACCESS),
}


@pytest.mark.parametrize("name", sorted(RAW_CASES))
def test_unexpected_output_fails_closed_with_a_fixed_code(gh_world: GhWorld, name: str) -> None:
    stdout, code, expected = RAW_CASES[name]
    shared_app(gh_world)
    gh_world.set(raw_api={"stdout": stdout, "code": code})
    assert gh_world.reader().fetch(PrRef(APP, 5)) == SyncError(expected)


def test_an_invalid_repository_name_never_reaches_gh(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    assert gh_world.reader().fetch(PrRef("bad repo/x;id", 1)) == SyncError(UNEXPECTED)
    assert gh_world.log() == []


# -- threads: pagination and caps -------------------------------------------------------------
def unresolved(total: int, open_at: list[int]) -> list[bool]:
    return [i not in open_at for i in range(total)]  # True = resolved


def test_threads_over_one_hundred_are_paged(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5, threads=unresolved(140, [3, 50, 120, 130]))
    result = snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert (result.threads_open, result.threads_incomplete) == (4, False)
    calls = gh_world.api_calls()
    assert len(calls) == 2
    assert not any(a.startswith("cursor=") for a in calls[0]["argv"])
    assert "cursor=cur:100" in calls[1]["argv"]


def test_twenty_pages_is_the_cap_and_exactly_twenty_is_complete(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5, threads=unresolved(2500, [p * 100 for p in range(25)]))
    gh_world.pr(APP, 6, threads=unresolved(2000, [p * 100 for p in range(20)]))
    capped = snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert (capped.threads_open, capped.threads_incomplete) == (20, True)
    assert classify(capped) == ("20+-open-threads",)
    assert len(gh_world.api_calls()) == 20
    exact = snapshot_of(gh_world.reader().fetch(PrRef(APP, 6)))
    assert (exact.threads_open, exact.threads_incomplete) == (20, False)
    assert len(gh_world.api_calls()) == 40


def test_a_failed_thread_page_makes_the_count_incomplete(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.set(fail_offsets=[100])
    gh_world.pr(APP, 5, threads=unresolved(140, [5]))
    gh_world.pr(APP, 6, threads=unresolved(140, []))
    partial = snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert (partial.threads_open, partial.threads_incomplete) == (1, True)
    assert classify(partial) == ("1+-open-threads",)
    nothing = snapshot_of(gh_world.reader().fetch(PrRef(APP, 6)))
    assert (nothing.threads_open, nothing.threads_incomplete) == (None, True)
    assert classify(nothing) == ("unknown-threads",)


# -- call budget, mergeable retry, parents ---------------------------------------------------
def test_call_budget_of_a_stacked_pr_with_many_threads_and_a_flaky_mergeable(
    gh_world: GhWorld,
) -> None:
    heads = [{"number": 8, "state": "OPEN", "head": "stack-1", "head_repo": APP}]
    shared_app(gh_world, heads=heads, branches=["main", "stack-1"])
    gh_world.pr(
        APP,
        9,
        base="stack-1",
        head="feat",
        mergeable=["UNKNOWN", "MERGEABLE"],
        threads=[True] * 140,
    )
    result = snapshot_of(gh_world.reader().fetch(PrRef(APP, 9)))
    calls = gh_world.api_calls()
    assert len(calls) == 4  # main, mergeable retry, thread page 2, parent lookup
    assert gh_world.sleeps == [1.0]
    assert "pullRequests(headRefName" in calls[3]["argv"][3]
    assert "cursor=cur:100" in calls[2]["argv"]
    assert len(gh_world.verbs("auth", "status")) == 1
    assert gh_world.verbs("auth", "token") == []
    assert result.mergeable == "ok"
    assert classify(result) == ("waits-on-#8",)
    gh_world.assert_read_only()


def test_mergeable_that_stays_unknown_is_shown_never_invented(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5, mergeable=["UNKNOWN", "UNKNOWN"])
    result = snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))
    assert classify(result) == ("unknown-mergeable",)
    assert len(gh_world.api_calls()) == 2
    assert gh_world.sleeps == [1.0]


def test_mergeable_resolves_to_a_conflict_after_the_retry(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5, mergeable=["UNKNOWN", "CONFLICTING"])
    assert classify(snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))) == ("conflict",)


def test_closed_stacked_pr_skips_the_parent_lookup(gh_world: GhWorld) -> None:
    shared_app(gh_world)
    gh_world.pr(APP, 5, state="CLOSED", base="stack-1")
    assert snapshot_of(gh_world.reader().fetch(PrRef(APP, 5))).state == "CLOSED"
    assert len(gh_world.api_calls()) == 1


def test_renamed_parent_branch_is_unknown_not_silently_unstacked(gh_world: GhWorld) -> None:
    shared_app(gh_world, branches=["main"])  # the base branch no longer exists
    gh_world.pr(APP, 5, base="old-parent")
    assert classify(snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))) == ("unknown-parent",)


def test_long_lived_base_without_a_pr_is_not_stacked(gh_world: GhWorld) -> None:
    shared_app(gh_world, branches=["main", "release/1.0"])
    gh_world.pr(APP, 5, base="release/1.0")
    assert classify(snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))) == ()


def test_fork_with_the_same_branch_name_is_not_the_parent(gh_world: GhWorld) -> None:
    heads = [{"number": 2, "state": "OPEN", "head": "stack-1", "head_repo": "someone/app"}]
    shared_app(gh_world, heads=heads, branches=["main", "stack-1"])
    gh_world.pr(APP, 5, base="stack-1")
    assert classify(snapshot_of(gh_world.reader().fetch(PrRef(APP, 5)))) == ()


# -- allow-list: this module can only read ---------------------------------------------------
GOOD = [
    ["auth", "status"],
    ["auth", "status", "--json", "hosts"],
    ["auth", "token", "--hostname", "github.com", "--user", "EzeCuccorese", "--no-refresh"],
    ["api", "graphql", "-f", f"query={PR_QUERY}", "-f", "owner=o", "-F", "number=1"],
    [
        "api",
        "graphql",
        "-f",
        f"query={PARENT_QUERY}",
        "-f",
        "base=b",
        "-f",
        "qualified=refs/heads/b",
    ],
]
BAD = [
    ["auth", "switch"],
    ["auth", "login"],
    ["pr", "merge", "1"],
    ["pr", "review", "1", "--approve"],
    ["pr", "comment", "1"],
    ["repo", "view"],
    ["api", "repos/o/r"],
    ["api", "graphql"],
    ["api", "graphql", "-X", "POST"],
    ["api", "graphql", "-f", "query=mutation { x }"],
    ["api", "graphql", "-f", "query=query { a } mutation { b }"],
    ["api", "graphql", "-f", "query=subscription { a }"],
    ["api", "graphql", "-f", "query=query { a }", "-f", "query=query { b }"],
    ["api", "graphql", "-f", "query=query { a }", "-f", "Owner=x"],
    ["auth", "token", "--user", "a b"],
    ["auth", "token", "--hostname", "evil.com"],
    ["auth", "status", "--show-token"],
    [],
]


@pytest.mark.parametrize("argv", GOOD)
def test_allow_list_accepts_the_read_only_calls(argv: list[str]) -> None:
    check_argv(argv)


@pytest.mark.parametrize("argv", BAD)
def test_allow_list_refuses_everything_else(argv: list[str]) -> None:
    with pytest.raises(ValueError, match=r"."):
        check_argv(argv)


def test_non_list_argv_is_refused() -> None:
    with pytest.raises(ValueError, match="list of strings"):
        check_argv("auth status")  # type: ignore[arg-type]


def test_a_refused_call_spawns_nothing(gh_world: GhWorld) -> None:
    with pytest.raises(ValueError, match="read-only"):
        Gh().run(["pr", "merge", "1"])
    assert gh_world.calls == []


def test_the_query_constants_are_read_only() -> None:
    for query in (PR_QUERY, PARENT_QUERY):
        assert query.lstrip().startswith("query")
        assert not re.search(r"\b(mutation|subscription)\b", query, re.I)


def test_only_the_reader_module_names_gh() -> None:
    package = Path(prs.__file__).parent
    for source in package.glob("*.py"):
        if source.name != "github.py":
            assert '"gh"' not in source.read_text(), source.name


# -- B-h: origin inference through ssh -G -----------------------------------------------------
def test_ssh_alias_is_github_only_when_ssh_dash_g_says_so(gh_world: GhWorld) -> None:
    gh_world.ssh_hosts = {"github-cucco": "github.com", "gl": "gitlab.example.com"}
    gh_world.save()
    assert parse_remote("git@github-cucco:EzeCuccorese/foo.git") == "EzeCuccorese/foo"
    assert parse_remote("git@gl:o/r.git") is None
    assert gh_world.ssh_log() == [["-G", "github-cucco"], ["-G", "gl"]]


def test_hostile_ssh_aliases_never_reach_ssh(gh_world: GhWorld) -> None:
    for alias in ("-oProxyCommand=evil", "a b", "x;id", "", "$(id)"):
        assert ssh_hostname(alias) is None
    assert parse_remote("git@-oProxyCommand=evil:o/r.git") is None
    assert gh_world.ssh_log() == []


def test_missing_ssh_binary_means_not_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = make_gh_world(tmp_path, monkeypatch, capsys, with_ssh=False)
    assert parse_remote("git@github-cucco:o/r.git") is None
    assert parse_remote("https://github.com/o/r.git") == "o/r"  # a direct URL needs no ssh
    world.assert_hermetic()


def checkout(path: Path, url: str | None) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    if url:
        subprocess.run(
            ["git", "remote", "add", "origin", url], cwd=path, check=True, capture_output=True
        )
    return path


def test_infer_repo_from_bound_checkouts(gh_world: GhWorld, tmp_path: Path) -> None:
    gh_world.ssh_hosts = {"github-cucco": "github.com", "gl": "gitlab.example.com"}
    gh_world.save()
    one = checkout(tmp_path / "one", "git@github-cucco:EzeCuccorese/foo.git")
    same = checkout(tmp_path / "same", "https://github.com/ezecuccorese/FOO.git")
    other = checkout(tmp_path / "other", "https://github.com/acme/bar.git")
    elsewhere = checkout(tmp_path / "elsewhere", "git@gl:acme/baz.git")
    bare = checkout(tmp_path / "bare", None)
    assert infer_repo([one, same, elsewhere, bare]) == "EzeCuccorese/foo"
    assert infer_repo([elsewhere, other]) == "acme/bar"  # non-GitHub hosts are ignored
    with pytest.raises(
        ValueError,
        match=r"ambiguous.*EzeCuccorese/foo.*acme/bar|ambiguous.*acme/bar.*EzeCuccorese/foo",
    ):
        infer_repo([one, other])
    with pytest.raises(ValueError, match="no GitHub origin"):
        infer_repo([elsewhere, bare])
