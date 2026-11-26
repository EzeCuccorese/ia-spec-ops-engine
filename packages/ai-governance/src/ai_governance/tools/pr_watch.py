"""Read-only GitHub PR watcher (uses local ``gh`` CLI, zero third-party servers).

Detects new state transitions on open pull requests authored by a user:
  - ``ready_to_merge``: approved, mergeable, non-draft, and CI checks passing
  - ``new_comment``:    new review / issue / inline comment from someone else
  - ``ci_failed``:      new failing check or status on the latest commit
  - ``merge_conflict``: PR transitioned to ``CONFLICTING``

Exit codes for ``check``:
  0 = at least one new event detected (writes ``<state-dir>/pending-events.json``)
  1 = no new events (ready for scheduler prechecks)
  2 = error (auth, network, invalid args)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "pr-watch"

GRAPHQL_QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 30) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        isDraft
        mergeable
        reviewDecision
        repository { nameWithOwner }
        commits(last: 1) {
          nodes {
            commit {
              oid
              statusCheckRollup {
                state
                contexts(first: 50) {
                  nodes {
                    __typename
                    ... on CheckRun {
                      name
                      status
                      conclusion
                      detailsUrl
                    }
                    ... on StatusContext {
                      context
                      state
                      targetUrl
                    }
                  }
                }
              }
            }
          }
        }
        comments(last: 15) {
          nodes {
            id
            url
            createdAt
            body
            author { login }
          }
        }
        reviews(last: 15) {
          nodes {
            id
            url
            state
            submittedAt
            body
            author { login }
          }
        }
        reviewThreads(last: 25) {
          nodes {
            comments(last: 5) {
              nodes {
                id
                url
                createdAt
                body
                path
                author { login }
              }
            }
          }
        }
      }
    }
  }
}
"""

FAIL_CONCLUSIONS = frozenset(
    {
        "FAILURE",
        "ERROR",
        "TIMED_OUT",
        "CANCELLED",
        "ACTION_REQUIRED",
        "STARTUP_FAILURE",
    }
)


def _gh_env(gh_user: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    if gh_user:
        token = subprocess.check_output(
            ["gh", "auth", "token", "--user", gh_user],
            env=env,
            text=True,
        ).strip()
        if not token:
            raise RuntimeError(f"No GitHub token available for user {gh_user}")
        env["GH_TOKEN"] = token
    return env


def _resolve_author(author: str | None, env: dict[str, str]) -> str:
    if author:
        return author
    return subprocess.check_output(
        ["gh", "api", "user", "--jq", ".login"], env=env, text=True
    ).strip()


def _fetch_open_prs(author: str, org: str | None, env: dict[str, str]) -> list[dict[str, Any]]:
    query = f"is:pr is:open author:{author}"
    if org:
        query += f" org:{org}"
    raw = subprocess.check_output(
        ["gh", "api", "graphql", "-f", f"query={GRAPHQL_QUERY}", "-f", f"q={query}"],
        env=env,
        text=True,
    )
    data = json.loads(raw)
    nodes = data.get("data", {}).get("search", {}).get("nodes", [])
    return [n for n in nodes if isinstance(n, dict) and n.get("number")]


def summarize_pr(pr: dict[str, Any], author: str) -> dict[str, Any]:
    """Normalize a GitHub GraphQL PullRequest node into a compact state record."""
    repo = pr["repository"]["nameWithOwner"]
    key = f"{repo}#{pr['number']}"
    commit_nodes = (pr.get("commits") or {}).get("nodes") or []
    commit = commit_nodes[0]["commit"] if commit_nodes else {}
    head_sha = commit.get("oid", "")
    rollup = commit.get("statusCheckRollup") or {}
    ci_state = rollup.get("state") or "NONE"

    failing_checks: list[dict[str, str]] = []
    for ctx in (rollup.get("contexts") or {}).get("nodes") or []:
        if not isinstance(ctx, dict):
            continue
        typename = ctx.get("__typename")
        if typename == "CheckRun":
            conc = (ctx.get("conclusion") or "").upper()
            if conc in FAIL_CONCLUSIONS:
                failing_checks.append(
                    {
                        "name": ctx.get("name", "check"),
                        "result": conc,
                        "url": ctx.get("detailsUrl") or pr["url"],
                    }
                )
        elif typename == "StatusContext":
            st = (ctx.get("state") or "").upper()
            if st in FAIL_CONCLUSIONS:
                failing_checks.append(
                    {
                        "name": ctx.get("context", "status"),
                        "result": st,
                        "url": ctx.get("targetUrl") or pr["url"],
                    }
                )

    failing_checks.sort(key=lambda c: c["name"])

    interactions: dict[str, dict[str, str]] = {}

    def _add(
        item_id: str | None,
        who: str | None,
        kind: str,
        body: str,
        url: str,
        when: str,
        path: str = "",
    ) -> None:
        if not item_id or not who or who.lower() == author.lower():
            return
        snippet = " ".join((body or "").split())[:220]
        interactions[item_id] = {
            "id": item_id,
            "author": who,
            "kind": kind,
            "snippet": snippet,
            "url": url or pr["url"],
            "at": when or "",
            "path": path,
        }

    for comment in (pr.get("comments") or {}).get("nodes") or []:
        if not isinstance(comment, dict):
            continue
        _add(
            comment.get("id"),
            (comment.get("author") or {}).get("login"),
            "comment",
            comment.get("body") or "",
            comment.get("url") or pr["url"],
            comment.get("createdAt") or "",
        )

    for review in (pr.get("reviews") or {}).get("nodes") or []:
        if not isinstance(review, dict):
            continue
        state = (review.get("state") or "").upper()
        body = (review.get("body") or "").strip()
        if state == "COMMENTED" and not body:
            continue
        if state in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}:
            _add(
                review.get("id"),
                (review.get("author") or {}).get("login"),
                f"review:{state.lower()}",
                body or state.replace("_", " ").lower(),
                review.get("url") or pr["url"],
                review.get("submittedAt") or "",
            )

    for thread in (pr.get("reviewThreads") or {}).get("nodes") or []:
        if not isinstance(thread, dict):
            continue
        for rc in (thread.get("comments") or {}).get("nodes") or []:
            if not isinstance(rc, dict):
                continue
            _add(
                rc.get("id"),
                (rc.get("author") or {}).get("login"),
                "inline_comment",
                rc.get("body") or "",
                rc.get("url") or pr["url"],
                rc.get("createdAt") or "",
                path=rc.get("path") or "",
            )

    mergeable = pr.get("mergeable") or "UNKNOWN"
    review_decision = pr.get("reviewDecision") or "NONE"
    ready_to_merge = (
        not pr.get("isDraft", False)
        and review_decision == "APPROVED"
        and mergeable == "MERGEABLE"
        and ci_state in {"SUCCESS", "NONE"}
        and not failing_checks
    )

    return {
        "key": key,
        "repo": repo,
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "is_draft": bool(pr.get("isDraft", False)),
        "mergeable": mergeable,
        "review_decision": review_decision,
        "head_sha": head_sha,
        "ci_state": ci_state,
        "failing_checks": failing_checks,
        "ready_to_merge": ready_to_merge,
        "interactions": interactions,
    }


def diff_events(
    current: dict[str, dict[str, Any]], previous: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only newly occurred PR transitions compared against ``previous``."""
    prev_prs = previous.get("prs", {})
    events: list[dict[str, Any]] = []

    for key, pr in sorted(current.items()):
        old = prev_prs.get(key)
        is_new_pr = old is None

        if pr["ready_to_merge"] and (is_new_pr or not old.get("ready_to_merge")):
            events.append(
                {
                    "type": "ready_to_merge",
                    "pr": key,
                    "title": pr["title"],
                    "url": pr["url"],
                    "detail": "Approved, mergeable, and CI passing.",
                }
            )

        if pr["mergeable"] == "CONFLICTING" and (
            is_new_pr or old.get("mergeable") != "CONFLICTING"
        ):
            events.append(
                {
                    "type": "merge_conflict",
                    "pr": key,
                    "title": pr["title"],
                    "url": pr["url"],
                    "detail": "PR has merge conflicts with its base branch.",
                }
            )

        old_sha = (old or {}).get("head_sha")
        old_failed = (
            set((old or {}).get("failing_check_names", []))
            if old_sha == pr["head_sha"]
            else set()
        )
        new_failed = [c for c in pr["failing_checks"] if c["name"] not in old_failed]
        if new_failed:
            events.append(
                {
                    "type": "ci_failed",
                    "pr": key,
                    "title": pr["title"],
                    "url": pr["url"],
                    "checks": new_failed,
                    "detail": "Failing checks: " + ", ".join(c["name"] for c in new_failed),
                }
            )

        seen_ids = set((old or {}).get("seen_interaction_ids", []))
        new_items = [item for iid, item in pr["interactions"].items() if iid not in seen_ids]
        if new_items:
            new_items.sort(key=lambda x: x.get("at", ""))
            events.append(
                {
                    "type": "new_comment",
                    "pr": key,
                    "title": pr["title"],
                    "url": pr["url"],
                    "items": new_items,
                    "detail": f"{len(new_items)} new comment(s)/review(s)",
                }
            )

    return events


def serialize_state(current: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "prs": {
            key: {
                "mergeable": pr["mergeable"],
                "review_decision": pr["review_decision"],
                "head_sha": pr["head_sha"],
                "ci_state": pr["ci_state"],
                "failing_check_names": [c["name"] for c in pr["failing_checks"]],
                "ready_to_merge": pr["ready_to_merge"],
                "seen_interaction_ids": sorted(pr["interactions"].keys()),
            }
            for key, pr in current.items()
        },
    }


def format_instant_alert(events: list[dict[str, Any]], footer: str | None = None) -> str:
    labels = {
        "ready_to_merge": ":white_check_mark: **Ready to merge**",
        "merge_conflict": ":warning: **Merge conflict**",
        "ci_failed": ":x: **CI failed**",
        "new_comment": ":speech_balloon: **New comment / review**",
    }
    lines = ["**[PRs - Instant alert]**", ""]
    for ev in events:
        tag = labels.get(ev["type"], ev["type"])
        lines.append(f"- {tag} · [{ev['pr']}]({ev['url']}) — {ev['title']}")
        if ev["type"] == "new_comment":
            for it in ev.get("items", [])[:3]:
                who = it["author"]
                kind = it["kind"].replace("review:", "")
                snip = it["snippet"]
                lines.append(f"  - `@{who}` ({kind}): {snip}")
        else:
            lines.append(f"  - {ev['detail']}")
    if footer:
        lines.extend(["", f"_{footer}_"])
    return "\n".join(lines) + "\n"


def _run_notify(notify_cmd: str, markdown: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(markdown)
        tmp_path = tmp.name
    try:
        cmd = shlex.split(notify_cmd) + [tmp_path]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance pr-watch",
        description="Read-only GitHub PR watcher using the local gh CLI.",
    )
    parser.add_argument("action", choices=["status", "check"])
    parser.add_argument("--author", help="PR author GitHub login (default: current gh user)")
    parser.add_argument("--org", help="Optional GitHub organization filter")
    parser.add_argument("--gh-user", help="Optional gh CLI account name for scoped GH_TOKEN")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument(
        "--notify-cmd",
        help="Command prefix receiving a temporary Markdown file path when events occur",
    )
    parser.add_argument("--footer", help="Optional italic footer line appended to instant alerts")
    parser.add_argument(
        "--init", action="store_true", help="Initialize baseline state without alerting"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        env = _gh_env(args.gh_user or None)
        author = _resolve_author(args.author, env)
        raw_prs = _fetch_open_prs(author, args.org or None, env)
    except Exception as exc:
        print(f"pr-watch error: {exc}", file=sys.stderr)
        return 2

    current = {s["key"]: s for s in (summarize_pr(pr, author) for pr in raw_prs)}

    if args.action == "status":
        print(f"Open PRs for {author} (org={args.org or 'any'}): {len(current)}")
        for key, pr in sorted(current.items()):
            flags: list[str] = []
            if pr["is_draft"]:
                flags.append("DRAFT")
            if pr["ready_to_merge"]:
                flags.append("READY_TO_MERGE")
            if pr["mergeable"] == "CONFLICTING":
                flags.append("CONFLICT")
            if pr["failing_checks"]:
                flags.append(f"CI_FAIL({len(pr['failing_checks'])})")
            else:
                flags.append(f"CI:{pr['ci_state']}")
            flags.append(f"REV:{pr['review_decision']}")
            print(f"  - {key} [{', '.join(flags)}] {pr['title']}")
        return 0

    args.state_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.state_dir / "state.json"
    pending_file = args.state_dir / "pending-events.json"

    first_run = not state_file.exists() or args.init
    previous = {} if first_run else json.loads(state_file.read_text(encoding="utf-8"))

    if first_run:
        state_file.write_text(json.dumps(serialize_state(current), indent=2), encoding="utf-8")
        print(f"pr-watch baseline initialized ({len(current)} open PRs).")
        return 1

    events = diff_events(current, previous)
    state_file.write_text(json.dumps(serialize_state(current), indent=2), encoding="utf-8")

    if not events:
        return 1

    payload = {
        "detected_at": datetime.now(UTC).isoformat(),
        "author": author,
        "events": events,
    }
    pending_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.notify_cmd:
        try:
            _run_notify(args.notify_cmd, format_instant_alert(events, footer=args.footer))
        except Exception as exc:
            print(f"pr-watch notify warning: {exc}", file=sys.stderr)

    print(json.dumps(payload, ensure_ascii=False))
    return 0
