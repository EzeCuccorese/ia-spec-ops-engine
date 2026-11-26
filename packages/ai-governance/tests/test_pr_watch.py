"""Unit tests for the agnostic GitHub PR watcher (ai-governance pr-watch)."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_detects_ready_to_merge_conflict_ci_failure_and_external_comments() -> None:
    prev_summary = pr_watch.summarize_pr(
        _sample_pr(
            comments=[
                {
                    "id": "c-old",
                    "url": "https://github.com/acme/repo/pull/42#c-old",
                    "createdAt": "2026-11-24T10:00:00Z",
                    "body": "Old comment",
                    "author": {"login": "bob"},
                }
            ]
        ),
        author="alice",
    )
    previous = pr_watch.serialize_state({"acme/repo#42": prev_summary})

    # Transition: approved + mergeable + CI green + new comment from bob (own comment from alice ignored)
    curr_summary = pr_watch.summarize_pr(
        _sample_pr(
            review_decision="APPROVED",
            mergeable="MERGEABLE",
            ci_state="SUCCESS",
            comments=[
                {
                    "id": "c-old",
                    "url": "https://github.com/acme/repo/pull/42#c-old",
                    "createdAt": "2026-11-24T10:00:00Z",
                    "body": "Old comment",
                    "author": {"login": "bob"},
                },
                {
                    "id": "c-own",
                    "url": "https://github.com/acme/repo/pull/42#c-own",
                    "createdAt": "2026-11-25T10:00:00Z",
                    "body": "Self reply",
                    "author": {"login": "alice"},
                },
                {
                    "id": "c-new",
                    "url": "https://github.com/acme/repo/pull/42#c-new",
                    "createdAt": "2026-11-25T10:05:00Z",
                    "body": "Looks great!",
                    "author": {"login": "bob"},
                },
            ],
        ),
        author="alice",
    )
    events = pr_watch.diff_events({"acme/repo#42": curr_summary}, previous)
    types = [ev["type"] for ev in events]
    assert types == ["ready_to_merge", "new_comment"]
    assert [it["id"] for it in events[1]["items"]] == ["c-new"]

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
    state_after_green = pr_watch.serialize_state({"acme/repo#42": curr_summary})
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
