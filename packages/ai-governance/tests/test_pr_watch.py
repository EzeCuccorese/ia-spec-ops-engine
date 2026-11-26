"""Unit tests for the agnostic GitHub PR watcher (ai-governance pr-watch)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.tools import pr_watch


def _sample_pr(
    *,
    number: int = 42,
    is_draft: bool = False,
    mergeable: str = "MERGEABLE",
    review_decision: str = "REVIEW_REQUIRED",
    sha: str = "abc123",
    ci_state: str = "SUCCESS",
    contexts: list[dict] | None = None,
    comments: list[dict] | None = None,
    reviews: list[dict] | None = None,
    threads: list[dict] | None = None,
) -> dict:
    return {
        "number": number,
        "title": "feat: add widget",
        "url": f"https://github.com/acme/repo/pull/{number}",
        "isDraft": is_draft,
        "mergeable": mergeable,
        "reviewDecision": review_decision,
        "repository": {"nameWithOwner": "acme/repo"},
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": sha,
                        "statusCheckRollup": {
                            "state": ci_state,
                            "contexts": {"nodes": contexts or []},
                        },
                    }
                }
            ]
        },
        "comments": {"nodes": comments or []},
        "reviews": {"nodes": reviews or []},
        "reviewThreads": {"nodes": threads or []},
    }


def _comment(item_id: str, author: str, body: str, created_at: str) -> dict:
    return {
        "id": item_id,
        "url": f"https://github.com/acme/repo/pull/42#{item_id}",
        "createdAt": created_at,
        "body": body,
        "author": {"login": author},
    }


def test_detects_ready_to_merge_and_external_comments() -> None:
    old_comment = _comment("c-old", "bob", "Old comment", "2026-11-24T10:00:00Z")
    prev_summary = pr_watch.summarize_pr(_sample_pr(comments=[old_comment]), author="alice")
    previous = pr_watch.serialize_state({"acme/repo#42": prev_summary})

    # Transition: approved + mergeable + CI green + new comment from bob (own comment ignored)
    curr_summary = pr_watch.summarize_pr(
        _sample_pr(
            review_decision="APPROVED",
            mergeable="MERGEABLE",
            ci_state="SUCCESS",
            comments=[
                old_comment,
                _comment("c-own", "alice", "Self reply", "2026-11-25T10:00:00Z"),
                _comment("c-new", "bob", "Looks great!", "2026-11-25T10:05:00Z"),
            ],
        ),
        author="alice",
    )
    events = pr_watch.diff_events({"acme/repo#42": curr_summary}, previous)
    assert [ev["type"] for ev in events] == ["ready_to_merge", "new_comment"]
    assert [it["id"] for it in events[1]["items"]] == ["c-new"]


def test_detects_conflict_ci_failure_and_deduplicates_alerts() -> None:
    green_summary = pr_watch.summarize_pr(
        _sample_pr(review_decision="APPROVED", mergeable="MERGEABLE", ci_state="SUCCESS"),
        author="alice",
    )
    state_after_green = pr_watch.serialize_state({"acme/repo#42": green_summary})

    # Transition: conflict + CI failure on same SHA -> fires once, not twice
    broken_summary = pr_watch.summarize_pr(
        _sample_pr(
            mergeable="CONFLICTING",
            ci_state="FAILURE",
            contexts=[
                {
                    "__typename": "CheckRun",
                    "name": "pytest",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://ci.example/1",
                }
            ],
        ),
        author="alice",
    )
    broken_events = pr_watch.diff_events({"acme/repo#42": broken_summary}, state_after_green)
    assert [ev["type"] for ev in broken_events] == ["merge_conflict", "ci_failed"]
    assert broken_events[1]["checks"][0]["name"] == "pytest"

    # Re-checking identical broken state produces zero duplicate alerts
    state_after_broken = pr_watch.serialize_state({"acme/repo#42": broken_summary})
    assert pr_watch.diff_events({"acme/repo#42": broken_summary}, state_after_broken) == []


def test_main_check_initializes_baseline_then_exits_0_only_on_new_event(
    monkeypatch, tmp_path: Path
) -> None:
    prs = [_sample_pr(review_decision="REVIEW_REQUIRED")]
    monkeypatch.setattr(pr_watch, "_gh_env", lambda _u: {})
    monkeypatch.setattr(pr_watch, "_resolve_author", lambda _a, _e: "alice")
    monkeypatch.setattr(pr_watch, "_fetch_open_prs", lambda _a, _o, _e: list(prs))

    # First run builds baseline and exits 1 (no spam)
    assert pr_watch.main(["check", "--state-dir", str(tmp_path)]) == 1
    assert (tmp_path / "state.json").is_file()

    # No changes -> exit 1
    assert pr_watch.main(["check", "--state-dir", str(tmp_path)]) == 1

    # PR becomes approved -> exit 0 and writes pending-events.json
    prs[0] = _sample_pr(review_decision="APPROVED", mergeable="MERGEABLE", ci_state="SUCCESS")
    assert pr_watch.main(["check", "--state-dir", str(tmp_path)]) == 0
    pending = json.loads((tmp_path / "pending-events.json").read_text(encoding="utf-8"))
    assert pending["events"][0]["type"] == "ready_to_merge"


def test_format_instant_alert_respects_optional_footer() -> None:
    md = pr_watch.format_instant_alert(
        [
            {
                "type": "ready_to_merge",
                "pr": "acme/repo#42",
                "title": "feat: add widget",
                "url": "https://github.com/acme/repo/pull/42",
                "detail": "Approved, mergeable, and CI passing.",
            }
        ],
        footer="Summary coming shortly.",
    )
    assert md.startswith("**[PRs - Instant alert]**\n")
    assert "_Summary coming shortly._" in md


def test_gh_helpers_and_graphql_error_validation(monkeypatch) -> None:
    monkeypatch.setattr(pr_watch.subprocess, "check_output", lambda *_a, **_k: "tok-1\n")
    assert pr_watch._gh_env("alice")["GH_TOKEN"] == "tok-1"
    assert pr_watch._resolve_author(None, {}) == "tok-1"

    monkeypatch.setattr(pr_watch.subprocess, "check_output", lambda *_a, **_k: "  ")
    with pytest.raises(RuntimeError, match="No GitHub token"):
        pr_watch._gh_env("alice")

    monkeypatch.setattr(
        pr_watch.subprocess,
        "check_output",
        lambda *_a, **_k: json.dumps({"errors": [{"message": "rate limit"}]}),
    )
    with pytest.raises(RuntimeError, match="GraphQL query failed"):
        pr_watch._fetch_open_prs("alice", "acme", {})

    monkeypatch.setattr(
        pr_watch.subprocess,
        "check_output",
        lambda *_a, **_k: json.dumps({"data": {"search": {"nodes": [{"number": 7}]}}}),
    )
    assert pr_watch._fetch_open_prs("alice", "acme", {}) == [{"number": 7}]


def test_reviews_inline_comments_and_status(capsys) -> None:
    pr = _sample_pr(
        is_draft=True,
        mergeable="CONFLICTING",
        contexts=[{"__typename": "StatusContext", "context": "lint", "state": "FAILURE"}],
    )
    pr["reviews"] = {
        "nodes": [
            {"id": "r1", "state": "COMMENTED", "body": "  ", "author": {"login": "bob"}},
            {"id": "r2", "state": "DISMISSED", "body": "old", "author": {"login": "bob"}},
            {"id": "r3", "state": "APPROVED", "body": "", "author": {"login": "bob"}},
        ]
    }
    pr["reviewThreads"] = {
        "nodes": [
            {
                "comments": {
                    "nodes": [
                        {"id": "i1", "body": "nit", "path": "a.py", "author": {"login": "bob"}}
                    ]
                }
            }
        ]
    }
    summary = pr_watch.summarize_pr(pr, author="alice")
    assert set(summary["interactions"]) == {"r3", "i1"}
    assert "DRAFT" in pr_watch._format_status_flags(summary)
    assert pr_watch._run_status({"acme/repo#42": summary}, "alice", None) == 0
    assert "CI_FAIL(1)" in capsys.readouterr().out


def test_format_comment_alert_and_notify(monkeypatch) -> None:
    md = pr_watch.format_instant_alert(
        [
            {
                "type": "new_comment",
                "pr": "acme/repo#42",
                "title": "T",
                "url": "https://x",
                "items": [{"author": "bob", "kind": "review:approved", "snippet": "LGTM"}],
            }
        ]
    )
    assert "`@bob` (approved): LGTM" in md

    seen_files: list[bool] = []
    monkeypatch.setattr(
        pr_watch.subprocess,
        "run",
        lambda cmd, **_k: (
            seen_files.append(Path(cmd[-1]).is_file()) or subprocess.CompletedProcess(cmd, 0)
        ),
    )
    pr_watch._run_notify("echo", md)
    assert seen_files == [True]


def test_corrupt_state_and_notify_failure_warning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pr_watch, "_gh_env", lambda _u: {})
    monkeypatch.setattr(pr_watch, "_resolve_author", lambda _a, _e: "alice")
    monkeypatch.setattr(
        pr_watch,
        "_fetch_open_prs",
        lambda _a, _o, _e: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert pr_watch.main(["status"]) == 2

    (tmp_path / "state.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(pr_watch, "_fetch_open_prs", lambda _a, _o, _e: [_sample_pr()])
    assert pr_watch.main(["check", "--state-dir", str(tmp_path)]) == 2

    (tmp_path / "state.json").unlink()
    assert pr_watch.main(["check", "--state-dir", str(tmp_path)]) == 1
    monkeypatch.setattr(
        pr_watch,
        "_fetch_open_prs",
        lambda _a, _o, _e: [
            _sample_pr(review_decision="APPROVED", mergeable="MERGEABLE", ci_state="SUCCESS")
        ],
    )
    monkeypatch.setattr(
        pr_watch, "_run_notify", lambda *_a: (_ for _ in ()).throw(RuntimeError("fail"))
    )
    assert pr_watch.main(["check", "--state-dir", str(tmp_path), "--notify-cmd", "true"]) == 0


def test_pr_watch_edge_cases_and_atomic_write_error(monkeypatch, tmp_path: Path) -> None:
    assert pr_watch._resolve_author("alice", {}) == "alice"
    assert pr_watch._gh_env(None)["PATH"].startswith("/opt/homebrew/bin:")

    pr = _sample_pr(
        review_decision="APPROVED",
        mergeable="MERGEABLE",
        ci_state="SUCCESS",
        comments=["not-a-dict"],
        contexts=[
            "not-a-dict",
            {"__typename": "Other"},
            {"__typename": "StatusContext", "state": "SUCCESS"},
        ],
    )
    summary = pr_watch.summarize_pr(pr, author="alice")
    flags = pr_watch._format_status_flags(summary)
    assert "READY_TO_MERGE" in flags and "CI:SUCCESS" in flags

    monkeypatch.setattr(
        pr_watch.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError, match="disk full"):
        pr_watch._atomic_write_text(tmp_path / "fail.json", "{}")


def test_pr_watch_handles_null_graphql_shapes(monkeypatch) -> None:
    monkeypatch.setattr(
        pr_watch.subprocess,
        "check_output",
        lambda *_a, **_k: json.dumps({"data": {"search": None}}),
    )
    assert pr_watch._fetch_open_prs("alice", None, {}) == []
    null_pr = {
        "number": 9,
        "title": "Nulls",
        "url": "https://x/9",
        "repository": None,
        "commits": {"nodes": [{"commit": None}]},
    }
    assert pr_watch.summarize_pr(null_pr, "alice")["repo"] == ""
    ctx = {"__typename": "CheckRun", "name": None, "conclusion": "FAILURE"}
    failed = pr_watch._failing_check_from_context(ctx, "https://x")
    assert failed is not None and failed["name"] == "check"
