"""Pull request review: capture, reviewer and judge rounds, and the owner's summary.

Hermetic: GitHub is replaced by fakes (no ``gh``, no network), Orca by the fake CLI of
``orca_fakes``; the review source is a throwaway local repository.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.taskflow import review, review_publish, review_source, review_summary
from ai_governance.taskflow.config import load_config
from ai_governance.taskflow.control import DispatchError, UsageRefusal
from ai_governance.taskflow.dispatch import DispatchRequest, plan_dispatch
from ai_governance.taskflow.review_format import (
    Verdict,
    checked_verdicts,
    parse_findings,
    parse_threads,
    parse_verdicts,
    quote_found,
)
from ai_governance.taskflow.review_publish import commentable_lines
from ai_governance.taskflow.review_source import (
    PullRef,
    PullSnapshot,
    activity_since,
    open_threads,
    parse_pr_url,
    references_markdown,
)
from orca_fakes import TASK, OrcaWorld, _make_repo, flag, world

PR_ONE = "https://github.com/acme/shop/pull/7"
PR_TWO = "https://github.com/acme/shop/pull/8"
KEY_ONE = "acme-shop-7"
REVIEW = (
    "FINDING: 1 | major | bug | app.py:1 | x starts at the wrong value | read app.py\n"
    "FINDING: 2 | minor | compat | app.py:1 | x is exported | unknown consumer\n"
    "FINDING: 3 | nit | design | app.py:1 | rename x | taste\n"
    "POSITION: request-changes - one bug\n"
)
JUDGEMENT = (
    "VERDICT: 1 | confirmed | app.py:1 | x = 1 | the value is wrong\n"
    "VERDICT: 2 | confirmed | app.py:1 | y = 2 is exported | exported indeed\n"
    "THREAD: t1 | nitpick | style only\n"
    "POSITION: request-changes - fix finding 1\n"
)


# -- answer formats ----------------------------------------------------------------------------
def test_findings_keep_first_of_a_repeated_number_and_report_unreadable_lines() -> None:
    parsed = parse_findings(
        "- FINDING: 1 | major | bug | src/a.py:3 | off by one | read the loop\n"
        "`FINDING: 2 | nit | design | src/a.py:1 | name | taste`\n"
        "FINDING: 2 | nit | design | src/a.py:1 | again | taste\n"
        "FINDING: 4 | huge | bug | src/a.py:1 | bad severity | x\n"
        "FINDING: 5 | minor | bug | src/a.py | no line | x\n"
    )
    assert [(f.number, f.severity, f.path, f.line) for f in parsed.items] == [
        (1, "major", "src/a.py", 3),
        (2, "nit", "src/a.py", 1),
    ]
    assert len(parsed.malformed) == 3


def test_finding_none_is_neither_a_finding_nor_malformed() -> None:
    parsed = parse_findings("FINDING: none\nPOSITION: approve - clean\n")
    assert parsed.items == () and parsed.malformed == ()


def test_verdicts_and_threads_reject_unknown_outcomes() -> None:
    verdicts = parse_verdicts(
        "VERDICT: 1 | confirmed | a.py:2 | return x | it does\n"
        "VERDICT: 2 | maybe | a.py:2 | return x | unsure\n"
    )
    threads = parse_threads("THREAD: t1 | fix | real bug\nTHREAD: t2 | ignore | no\n")
    assert [(v.number, v.outcome) for v in verdicts.items] == [(1, "confirmed")]
    assert len(verdicts.malformed) == 1
    assert [(t.thread, t.action) for t in threads.items] == [("t1", "fix")]
    assert len(threads.malformed) == 1


def _verdict(path: str, line: int, quote: str, outcome: str = "confirmed") -> Verdict:
    return Verdict(1, outcome, path, line, quote, "reason")


@pytest.mark.parametrize(
    ("verdict", "found"),
    [
        pytest.param(_verdict("a.py", 2, "return   total"), True, id="quote_on_the_cited_line"),
        pytest.param(_verdict("a.py", 4, "return total"), True, id="quote_a_few_lines_away"),
        pytest.param(_verdict("a.py", 2, "return nothing"), False, id="quote_not_in_the_file"),
        pytest.param(_verdict("a.py", 2, "ret"), False, id="quote_too_short_to_mean_anything"),
        pytest.param(_verdict("missing.py", 1, "return total"), False, id="file_does_not_exist"),
        pytest.param(_verdict("../secret.py", 1, "return total"), False, id="path_leaves_source"),
    ],
)
def test_quote_lookup(tmp_path: Path, verdict: Verdict, found: bool) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.py").write_text("def f():\n    return total\n\n\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("return total\n", encoding="utf-8")
    assert quote_found(source, verdict) is found


def test_only_a_confirmed_verdict_without_its_quote_is_downgraded(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("return total\n", encoding="utf-8")
    checked = checked_verdicts(
        tmp_path,
        (
            _verdict("a.py", 1, "return total"),
            _verdict("a.py", 1, "something else"),
            _verdict("a.py", 1, "something else", outcome="rejected"),
        ),
    )
    assert [v.outcome for v in checked] == ["confirmed", "needs-human", "rejected"]
    assert checked[1].note == "quote not found in the source"


# -- capture -----------------------------------------------------------------------------------
def test_pr_url_is_parsed_into_owner_repo_and_number() -> None:
    ref = parse_pr_url("https://github.com/acme/shop/pull/7/files")
    assert (ref.slug, ref.number, ref.key, ref.url) == ("acme/shop", 7, KEY_ONE, PR_ONE)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://github.com/acme/shop/issues/7", id="an_issue_not_a_pull_request"),
        pytest.param("https://example.com/acme/shop/pull/7", id="another_host"),
        pytest.param("acme/shop#7", id="short_reference"),
    ],
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(DispatchError, match="not a GitHub pull request URL"):
        parse_pr_url(url)


def test_references_list_the_files_that_mention_a_changed_file(tmp_path: Path) -> None:
    _make_repo(tmp_path / "src")
    source = tmp_path / "src"
    (source / "billing.py").write_text("rate = 3\n", encoding="utf-8")
    (source / "checkout.py").write_text("import billing\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
    text = references_markdown(source, ["billing.py", "app.py"])
    assert "## billing.py\n- checkout.py" in text
    assert "## app.py\n- not searched (name too short or too generic)" in text


def _page(nodes: list[dict[str, object]], cursor: str = "") -> dict[str, object]:
    threads = {"nodes": nodes, "pageInfo": {"hasNextPage": bool(cursor), "endCursor": cursor}}
    return {"data": {"repository": {"pullRequest": {"reviewThreads": threads}}}}


def _thread(resolved: bool, author: str = "bot", at: str = "2026-01-01T00:00:00Z") -> dict:
    comment = {"author": {"login": author}, "body": "b", "url": "u", "createdAt": at}
    return {
        "id": "N",
        "isResolved": resolved,
        "path": "a.py",
        "line": 3,
        "comments": {"nodes": [comment]},
    }


def test_open_threads_follow_pages_and_keep_only_the_unresolved(monkeypatch) -> None:
    pages = iter([_page([_thread(True), _thread(False)], "next"), _page([_thread(False)])])
    monkeypatch.setattr(review_source, "_gh_json", lambda *args: next(pages))
    found = open_threads(PullRef("acme", "shop", 7))
    assert found["truncated"] is False
    assert [t["id"] for t in found["threads"]] == ["t1", "t2"]


def test_open_threads_say_when_the_listing_was_cut_short(monkeypatch) -> None:
    monkeypatch.setattr(review_source, "_gh_json", lambda *args: _page([_thread(False)], "more"))
    assert open_threads(PullRef("acme", "shop", 7))["truncated"] is True


def test_activity_counts_only_what_the_account_wrote_after_the_review_opened(monkeypatch) -> None:
    state = {
        "isDraft": False,
        "reviews": [
            {"author": {"login": "me"}, "submittedAt": "2026-03-02T10:00:00Z"},
            {"author": {"login": "me"}, "submittedAt": "2026-03-01T09:00:00Z"},
            {"author": {"login": "other"}, "submittedAt": "2026-03-02T10:00:00Z"},
        ],
        "comments": [],
    }
    threads = _page([_thread(False, author="me", at="2026-03-02T11:00:00Z")])
    answers = {"pr": state, "api": threads}
    monkeypatch.setattr(review_source, "_gh_json", lambda *args: answers[args[0]])
    found = activity_since(PullRef("acme", "shop", 7), "me", "2026-03-01T12:00:00+00:00", True)
    assert found == ["1 review(s) by me", "1 inline comment(s) by me", "draft state changed"]


# -- dispatch of a review round ----------------------------------------------------------------
def _request(source: Path, role: str = "validator") -> DispatchRequest:
    return DispatchRequest(
        role=role,
        phase="work",
        focus="pr",
        prompt="review it",
        agent={"agent": "claude", "model": ""},
        source=str(source),
    )


def test_review_round_is_bound_to_its_source_and_starts_where_the_coordinator_is(
    world: OrcaWorld, tmp_path: Path
) -> None:
    source = tmp_path / "pr-source"
    _make_repo(source)
    made = plan_dispatch(world.store, world.task(), load_config([world.repo]), _request(source))
    record = world.dispatch_json(made.n)
    assert [entry["path"] for entry in record["repos"]] == [str(source)]
    assert flag(made.argv, "--worktree") == f"path:{world.repo}"


def test_review_source_only_takes_reviewer_and_judge_roles(
    world: OrcaWorld, tmp_path: Path
) -> None:
    source = tmp_path / "pr-source"
    _make_repo(source)
    with pytest.raises(UsageRefusal, match="A review round runs as validator or judge"):
        plan_dispatch(
            world.store, world.task(), load_config([world.repo]), _request(source, "debater")
        )


def test_judge_without_a_review_source_is_still_refused(world: OrcaWorld) -> None:
    request = DispatchRequest("judge", "work", "", "judge it", {"agent": "codex", "model": ""})
    with pytest.raises(UsageRefusal, match="Judges are not dispatched"):
        plan_dispatch(world.store, world.task(), load_config([world.repo]), request)


def test_missing_review_source_is_refused(world: OrcaWorld, tmp_path: Path) -> None:
    with pytest.raises(DispatchError, match="review source not found"):
        plan_dispatch(
            world.store, world.task(), load_config([world.repo]), _request(tmp_path / "gone")
        )


# -- review lifecycle --------------------------------------------------------------------------
@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """GitHub replaced by fakes: a capture is a local repository, and the pull request's
    activity is whatever the test puts in the returned ``{"activity": [...]}``."""
    seen: dict[str, list[str]] = {"activity": []}

    def capture(url: str, directory: Path) -> PullSnapshot:
        ref = parse_pr_url(url)
        snapshot = PullSnapshot(ref, f"PR {ref.number}", "a" * 40, "main", False, directory)
        directory.mkdir(parents=True)
        _make_repo(snapshot.source)
        for path in (snapshot.meta_file, snapshot.diff_file, snapshot.references_file):
            path.write_text("{}\n", encoding="utf-8")
        snapshot.threads_file.write_text('{"truncated": false, "threads": []}\n', encoding="utf-8")
        return snapshot

    monkeypatch.setattr(review, "snapshot_pull_request", capture)
    monkeypatch.setattr(review, "viewer_login", lambda: "me")
    monkeypatch.setattr(review_summary, "current_head", lambda ref: "a" * 40)
    monkeypatch.setattr(review_summary, "activity_since", lambda *args: list(seen["activity"]))
    return seen


def _open(world: OrcaWorld, *urls: str) -> None:
    prs = [part for url in urls for part in ("--pr", url)]
    result = world.run("review", TASK, "open", *prs, "--agent", "claude")
    assert result.code == 0, result.text


def _settle(world: OrcaWorld, number: int, agent: str, answer: str) -> None:
    world.finish(number, f"D{number}", answer=answer, agent=agent)
    result = world.collect(number, f"D{number}")
    assert result.code == 0, result.text


def _summary(world: OrcaWorld) -> str:
    result = world.run("review", TASK, "close")
    assert result.code == 0, result.text
    return Path(result.out.strip()).read_text(encoding="utf-8")


def test_open_reserves_one_reviewer_round_per_pull_request(world: OrcaWorld, github) -> None:
    result = world.run("review", TASK, "open", "--pr", PR_ONE, "--pr", PR_TWO, "--agent", "claude")
    assert result.code == 0, result.text
    lines = result.out.strip().splitlines()
    assert len(lines) == 2 and all("worker-start" in line for line in lines)
    state = review.require_review(world.store, TASK)
    assert [entry["reviewer"]["round"] for entry in state["prs"]] == [1, 2]
    assert world.dispatch_json(1)["role"] == "validator"
    assert "Impact (mandatory)" in Path(world.dispatch_json(1)["spec"]).read_text(encoding="utf-8")


def test_a_second_review_is_refused_while_one_is_open(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    result = world.run("review", TASK, "open", "--pr", PR_TWO, "--agent", "claude")
    assert result.code != 0
    assert "already has an open review" in result.text


def test_judge_waits_for_every_reviewer_round(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    result = world.run("review", TASK, "judge")
    assert result.code != 0
    assert "reviewer round(s) still pending: 001" in result.text


def test_judge_defaults_to_an_agent_of_another_provider(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    _settle(world, 1, "claude", REVIEW)
    result = world.run("review", TASK, "judge")
    assert result.code == 0, result.text
    record = world.dispatch_json(2)
    assert (record["role"], record["provider"]) == ("judge", "codex")


def test_judge_of_the_reviewers_provider_is_refused(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    _settle(world, 1, "claude", REVIEW)
    result = world.run("review", TASK, "judge", "--agent", "claude")
    assert result.code != 0
    assert "the judge must be of another provider than the reviewer" in result.text


def test_reviewer_that_changed_the_source_is_not_judged(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE, PR_TWO)
    state = review.require_review(world.store, TASK)
    (Path(state["prs"][0]["dir"]) / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    world.finish(1, "D1", answer=REVIEW, agent="claude")
    assert "reader changed the tree" in world.collect(1, "D1").text
    _settle(world, 2, "claude", REVIEW)
    result = world.run("review", TASK, "judge")
    assert result.code == 0, result.text
    assert f"{KEY_ONE}: reviewer round is not valid" in result.err
    assert len(result.out.strip().splitlines()) == 1


def test_close_refuses_pending_rounds_unless_partial(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    result = world.run("review", TASK, "close")
    assert result.code != 0
    assert "cannot close the review, still pending" in result.text
    assert world.run("review", TASK, "close", "--partial").code == 0


def test_summary_sorts_findings_by_what_the_judge_could_prove(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    _settle(world, 1, "claude", REVIEW)
    assert world.run("review", TASK, "judge").code == 0
    _settle(world, 2, "codex", JUDGEMENT)
    text = _summary(world)
    confirmed, rest = text.split("### Needs your decision (2)")
    assert "### Confirmed by the judge (1)" in confirmed
    assert "x starts at the wrong value" in confirmed
    assert "x is exported" in rest and "(quote not found in the source)" in rest
    assert "the judge gave no verdict for this finding" in rest
    assert "`t1` **nitpick**: style only" in rest
    assert "**request changes (a confirmed blocker or major finding)**" in text
    assert "Nothing was written to the pull request by me during the review." in text
    assert review.require_review(world.store, TASK)["status"] == "closed"


def test_summary_reports_writes_made_during_the_review(world: OrcaWorld, github) -> None:
    github["activity"].append("1 review(s) by me")
    _open(world, PR_ONE)
    _settle(world, 1, "claude", "FINDING: none\nPOSITION: approve - clean\n")
    assert world.run("review", TASK, "judge").code == 0
    _settle(world, 2, "codex", "POSITION: approve - nothing to check\n")
    text = _summary(world)
    assert "Written to the pull request while the review ran: 1 review(s) by me." in text
    assert "**approve (no finding confirmed)**" in text


# -- publishing after the owner's OK -----------------------------------------------------------
DIFF = (
    "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
    "@@ -1,2 +1,3 @@\n x = 1\n+y = 2\n-z = 3\n w = 4\n"
    "diff --git a/old.py b/old.py\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
)


def test_only_lines_of_the_new_version_in_the_diff_take_inline_comments() -> None:
    assert commentable_lines(DIFF) == {"app.py": {1, 2, 3}}


def _reviewed(world: OrcaWorld, review_answer: str, judge_answer: str) -> Path:
    """A closed review of PR_ONE; returns the directory of its capture."""
    _open(world, PR_ONE)
    _settle(world, 1, "claude", review_answer)
    assert world.run("review", TASK, "judge").code == 0
    _settle(world, 2, "codex", judge_answer)
    _summary(world)
    directory = Path(review.require_review(world.store, TASK)["prs"][0]["dir"])
    (directory / "pr.diff").write_text(DIFF, encoding="utf-8")
    return directory


def test_payload_puts_confirmed_findings_inline_when_their_line_is_in_the_diff(
    world: OrcaWorld, github, monkeypatch
) -> None:
    monkeypatch.setattr(review_publish, "current_head", lambda ref: "a" * 40)
    review_answer = (
        "FINDING: 1 | major | bug | app.py:1 | [seen] wrong start (seen) | read it in pr.diff\n"
        "FINDING: 2 | minor | bug | app.py:9 | off the diff | read it\n"
        "FINDING: 3 | nit | design | app.py:1 | rename | taste\n"
    )
    judge_answer = (
        "VERDICT: 1 | confirmed | app.py:1 | x = 1 | yes\n"
        "VERDICT: 2 | confirmed | app.py:1 | x = 1 | yes\n"
        "VERDICT: 3 | rejected | app.py:1 | x = 1 | taste\n"
    )
    directory = _reviewed(world, review_answer, judge_answer)
    result = world.run("review", TASK, "payload", "--pr", KEY_ONE, "--event", "request-changes")
    assert result.code == 0, result.text
    assert result.out.split()[:4] == ["gh", "api", "--method", "POST"]
    payload = json.loads((directory / "publish.json").read_text(encoding="utf-8"))
    assert (payload["event"], payload["commit_id"]) == ("REQUEST_CHANGES", "a" * 40)
    assert payload["comments"] == [
        {"path": "app.py", "line": 1, "side": "RIGHT", "body": "wrong start\n\nread it in the diff"}
    ]
    assert "`app.py:9`" in payload["body"] and "rename" not in payload["body"]


def test_payload_is_refused_when_the_pull_request_moved(
    world: OrcaWorld, github, monkeypatch
) -> None:
    monkeypatch.setattr(review_publish, "current_head", lambda ref: "b" * 40)
    _reviewed(world, REVIEW, JUDGEMENT)
    result = world.run("review", TASK, "payload", "--pr", KEY_ONE, "--event", "comment")
    assert result.code != 0
    assert "moved since it was reviewed" in result.text


def test_payload_needs_a_closed_review(world: OrcaWorld, github) -> None:
    _open(world, PR_ONE)
    result = world.run("review", TASK, "payload", "--pr", KEY_ONE, "--event", "comment")
    assert result.code != 0
    assert "close the review first" in result.text
