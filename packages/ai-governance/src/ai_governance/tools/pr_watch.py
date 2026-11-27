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
from dataclasses import dataclass
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
            author { __typename login }
          }
        }
        reviews(last: 15) {
          nodes {
            id
            url
            state
            submittedAt
            body
            author { __typename login }
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
                author { __typename login }
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
            timeout=30,
        ).strip()
        if not token:
            raise RuntimeError(f"No GitHub token available for user {gh_user}")
        env["GH_TOKEN"] = token
    return env


def _resolve_author(author: str | None, env: dict[str, str]) -> str:
    if author:
        return author
    return subprocess.check_output(
        ["gh", "api", "user", "--jq", ".login"], env=env, text=True, timeout=30
    ).strip()


def _parse_graphql_prs(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
        err_detail = data.get("errors") if isinstance(data, dict) else data
        raise RuntimeError(f"GitHub GraphQL query failed: {err_detail}")
    search = data["data"].get("search")
    nodes = search.get("nodes") if isinstance(search, dict) else None
    return [n for n in (nodes or []) if isinstance(n, dict) and n.get("number")]


def _fetch_open_prs(author: str, org: str | None, env: dict[str, str]) -> list[dict[str, Any]]:
    query = f"is:pr is:open author:{author}"
    if org:
        query += f" org:{org}"
    raw = subprocess.check_output(
        ["gh", "api", "graphql", "-f", f"query={GRAPHQL_QUERY}", "-f", f"q={query}"],
        env=env,
        text=True,
        timeout=30,
    )
    return _parse_graphql_prs(raw)


@dataclass(frozen=True)
class _Interaction:
    item_id: str | None
    who: str | None
    kind: str
    body: str
    url: str
    when: str
    path: str = ""
    is_bot: bool = False


def _extract_head_commit(pr: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    commit_nodes = (pr.get("commits") or {}).get("nodes") or []
    first_node = commit_nodes[0] if commit_nodes and isinstance(commit_nodes[0], dict) else {}
    raw_commit = first_node.get("commit")
    commit = raw_commit if isinstance(raw_commit, dict) else {}
    return commit.get("oid") or "", commit.get("statusCheckRollup") or {}


_CONTEXT_FIELDS: dict[str, tuple[str, str, str, str]] = {
    "CheckRun": ("name", "conclusion", "detailsUrl", "check"),
    "StatusContext": ("context", "state", "targetUrl", "status"),
}


def _failing_check_from_context(ctx: dict[str, Any], fallback_url: str) -> dict[str, str] | None:
    spec = _CONTEXT_FIELDS.get(str(ctx.get("__typename") or ""))
    if spec is None:
        return None
    name_key, state_key, url_key, default_name = spec
    state = (ctx.get(state_key) or "").upper()
    if state not in FAIL_CONCLUSIONS:
        return None
    return {
        "name": ctx.get(name_key) or default_name,
        "result": state,
        "url": ctx.get(url_key) or fallback_url,
    }


def _extract_failing_checks(rollup: dict[str, Any], fallback_url: str) -> list[dict[str, str]]:
    failing: list[dict[str, str]] = []
    for ctx in (rollup.get("contexts") or {}).get("nodes") or []:
        if not isinstance(ctx, dict):
            continue
        item = _failing_check_from_context(ctx, fallback_url)
        if item is not None:
            failing.append(item)
    failing.sort(key=lambda c: c["name"])
    return failing


def _normalize_login(login: str) -> str:
    cleaned = login.strip().lower()
    return cleaned[:-5] if cleaned.endswith("[bot]") else cleaned


def _parse_ignored_authors(values: list[str] | None) -> frozenset[str]:
    ignored: set[str] = set()
    for raw in values or []:
        for part in raw.split(","):
            norm = _normalize_login(part)
            if norm:
                ignored.add(norm)
    return frozenset(ignored)


def _record_interaction(
    interactions: dict[str, dict[str, Any]],
    author: str,
    fallback_url: str,
    item: _Interaction,
) -> None:
    if not item.item_id or not item.who or item.who.lower() == author.lower():
        return
    snippet = " ".join((item.body or "").split())[:220]
    interactions[item.item_id] = {
        "id": item.item_id,
        "author": item.who,
        "is_bot": item.is_bot,
        "kind": item.kind,
        "snippet": snippet,
        "url": item.url or fallback_url,
        "at": item.when or "",
        "path": item.path,
    }


def _collect_issue_comments(
    pr: dict[str, Any], interactions: dict[str, dict[str, Any]], author: str
) -> None:
    for comment in (pr.get("comments") or {}).get("nodes") or []:
        if not isinstance(comment, dict):
            continue
        _record_interaction(
            interactions,
            author,
            pr["url"],
            _Interaction(
                item_id=comment.get("id"),
                who=_author_login(comment),
                kind="comment",
                body=comment.get("body") or "",
                url=comment.get("url") or pr["url"],
                when=comment.get("createdAt") or "",
                is_bot=_is_bot_actor(comment),
            ),
        )


def _dict_nodes(container: dict[str, Any], key: str) -> list[dict[str, Any]]:
    nodes = (container.get(key) or {}).get("nodes") or []
    return [n for n in nodes if isinstance(n, dict)]


def _author_login(node: dict[str, Any]) -> str | None:
    return (node.get("author") or {}).get("login")


def _is_bot_actor(node: dict[str, Any]) -> bool:
    author_obj = node.get("author") or {}
    typename = str(author_obj.get("__typename") or "")
    login = str(author_obj.get("login") or "").lower()
    return typename == "Bot" or login.endswith("[bot]")


def _review_to_interaction(review: dict[str, Any], fallback_url: str) -> _Interaction | None:
    state = (review.get("state") or "").upper()
    body = (review.get("body") or "").strip()
    if state == "COMMENTED" and not body:
        return None
    if state not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}:
        return None
    return _Interaction(
        item_id=review.get("id"),
        who=_author_login(review),
        kind=f"review:{state.lower()}",
        body=body or state.replace("_", " ").lower(),
        url=review.get("url") or fallback_url,
        when=review.get("submittedAt") or "",
        is_bot=_is_bot_actor(review),
    )


def _collect_reviews(
    pr: dict[str, Any], interactions: dict[str, dict[str, Any]], author: str
) -> None:
    for review in _dict_nodes(pr, "reviews"):
        item = _review_to_interaction(review, pr["url"])
        if item is not None:
            _record_interaction(interactions, author, pr["url"], item)


def _inline_to_interaction(rc: dict[str, Any], fallback_url: str) -> _Interaction:
    return _Interaction(
        item_id=rc.get("id"),
        who=_author_login(rc),
        kind="inline_comment",
        body=rc.get("body") or "",
        url=rc.get("url") or fallback_url,
        when=rc.get("createdAt") or "",
        path=rc.get("path") or "",
        is_bot=_is_bot_actor(rc),
    )


def _collect_inline_comments(
    pr: dict[str, Any], interactions: dict[str, dict[str, Any]], author: str
) -> None:
    for thread in _dict_nodes(pr, "reviewThreads"):
        for rc in _dict_nodes(thread, "comments"):
            _record_interaction(
                interactions, author, pr["url"], _inline_to_interaction(rc, pr["url"])
            )


def _collect_interactions(pr: dict[str, Any], author: str) -> dict[str, dict[str, Any]]:
    interactions: dict[str, dict[str, Any]] = {}
    _collect_issue_comments(pr, interactions, author)
    _collect_reviews(pr, interactions, author)
    _collect_inline_comments(pr, interactions, author)
    return interactions


def _is_ready_to_merge(
    pr: dict[str, Any], ci_state: str, failing_checks: list[dict[str, str]]
) -> bool:
    return (
        not bool(pr.get("isDraft", False))
        and (pr.get("reviewDecision") or "NONE") == "APPROVED"
        and (pr.get("mergeable") or "UNKNOWN") == "MERGEABLE"
        and ci_state in {"SUCCESS", "NONE"}
        and not failing_checks
    )


def summarize_pr(pr: dict[str, Any], author: str) -> dict[str, Any]:
    """Normalize a GitHub GraphQL PullRequest node into a compact state record."""
    repo = (pr.get("repository") or {}).get("nameWithOwner") or ""
    head_sha, rollup = _extract_head_commit(pr)
    ci_state = rollup.get("state") or "NONE"
    failing_checks = _extract_failing_checks(rollup, pr["url"])
    interactions = _collect_interactions(pr, author)
    is_draft = bool(pr.get("isDraft", False))
    mergeable = pr.get("mergeable") or "UNKNOWN"
    review_decision = pr.get("reviewDecision") or "NONE"

    return {
        "key": f"{repo}#{pr['number']}",
        "repo": repo,
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "is_draft": is_draft,
        "mergeable": mergeable,
        "review_decision": review_decision,
        "head_sha": head_sha,
        "ci_state": ci_state,
        "failing_checks": failing_checks,
        "ready_to_merge": _is_ready_to_merge(pr, ci_state, failing_checks),
        "interactions": interactions,
    }


def _base_event(event_type: str, key: str, pr: dict[str, Any], detail: str) -> dict[str, Any]:
    return {
        "type": event_type,
        "pr": key,
        "title": pr["title"],
        "url": pr["url"],
        "detail": detail,
    }


def _state_transition_events(
    key: str, pr: dict[str, Any], old: dict[str, Any] | None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if pr["ready_to_merge"] and (old is None or not old.get("ready_to_merge")):
        events.append(
            _base_event("ready_to_merge", key, pr, "Approved, mergeable, and CI passing.")
        )
    if pr["mergeable"] == "CONFLICTING" and (old is None or old.get("mergeable") != "CONFLICTING"):
        events.append(
            _base_event("merge_conflict", key, pr, "PR has merge conflicts with its base branch.")
        )
    return events


def _ci_failure_event(
    key: str, pr: dict[str, Any], old: dict[str, Any] | None
) -> dict[str, Any] | None:
    old_sha = (old or {}).get("head_sha")
    old_failed = (
        set((old or {}).get("failing_check_names", [])) if old_sha == pr["head_sha"] else set()
    )
    new_failed = [c for c in pr["failing_checks"] if c["name"] not in old_failed]
    if not new_failed:
        return None
    event = _base_event(
        "ci_failed",
        key,
        pr,
        "Failing checks: " + ", ".join(c["name"] for c in new_failed),
    )
    event["checks"] = new_failed
    return event


def _is_ignored_interaction(
    item: dict[str, Any],
    is_draft: bool,
    ignore_authors: frozenset[str],
    ignore_draft_bots: bool,
) -> bool:
    author_norm = _normalize_login(str(item.get("author") or ""))
    if author_norm and author_norm in ignore_authors:
        return True
    return bool(ignore_draft_bots and is_draft and item.get("is_bot"))


def _new_comment_event(
    key: str,
    pr: dict[str, Any],
    old: dict[str, Any] | None,
    *,
    ignore_authors: frozenset[str] = frozenset(),
    ignore_draft_bots: bool = False,
) -> dict[str, Any] | None:
    seen_ids = set((old or {}).get("seen_interaction_ids", []))
    is_draft = bool(pr.get("is_draft", False))
    new_items = [
        item
        for iid, item in pr["interactions"].items()
        if iid not in seen_ids
        and not _is_ignored_interaction(item, is_draft, ignore_authors, ignore_draft_bots)
    ]
    if not new_items:
        return None
    new_items.sort(key=lambda x: x.get("at", ""))
    event = _base_event("new_comment", key, pr, f"{len(new_items)} new comment(s)/review(s)")
    event["items"] = new_items
    return event


def diff_events(
    current: dict[str, dict[str, Any]],
    previous: dict[str, Any],
    *,
    ignore_authors: frozenset[str] = frozenset(),
    ignore_draft_bots: bool = False,
) -> list[dict[str, Any]]:
    """Return only newly occurred PR transitions compared against ``previous``."""
    prev_prs = previous.get("prs", {})
    events: list[dict[str, Any]] = []

    for key, pr in sorted(current.items()):
        old = prev_prs.get(key)
        events.extend(_state_transition_events(key, pr, old))
        ci_event = _ci_failure_event(key, pr, old)
        if ci_event is not None:
            events.append(ci_event)
        comment_event = _new_comment_event(
            key,
            pr,
            old,
            ignore_authors=ignore_authors,
            ignore_draft_bots=ignore_draft_bots,
        )
        if comment_event is not None:
            events.append(comment_event)

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


def _atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    try:
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _run_notify(notify_cmd: str, markdown: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(markdown)
        tmp_path = tmp.name
    try:
        cmd = shlex.split(notify_cmd) + [tmp_path]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, timeout=30)
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
        "--ignore-authors",
        action="append",
        default=[],
        help="Author logins to ignore for new_comment alerts (repeatable or comma-separated)",
    )
    parser.add_argument(
        "--ignore-draft-bots",
        action="store_true",
        help="Ignore new_comment alerts from bot accounts while a PR is in draft",
    )
    parser.add_argument(
        "--init", action="store_true", help="Initialize baseline state without alerting"
    )
    return parser


def _format_status_flags(pr: dict[str, Any]) -> list[str]:
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
    return flags


def _run_status(current: dict[str, dict[str, Any]], author: str, org: str | None) -> int:
    print(f"Open PRs for {author} (org={org or 'any'}): {len(current)}")
    for key, pr in sorted(current.items()):
        flags = _format_status_flags(pr)
        print(f"  - {key} [{', '.join(flags)}] {pr['title']}")
    return 0


def _run_check(args: argparse.Namespace, current: dict[str, dict[str, Any]], author: str) -> int:
    args.state_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.state_dir / "state.json"
    pending_file = args.state_dir / "pending-events.json"

    first_run = not state_file.exists() or args.init
    if first_run:
        _atomic_write_text(state_file, json.dumps(serialize_state(current), indent=2))
        print(f"pr-watch baseline initialized ({len(current)} open PRs).")
        return 1

    try:
        previous = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"pr-watch error: corrupt state file {state_file}: {exc}", file=sys.stderr)
        return 2

    events = diff_events(
        current,
        previous,
        ignore_authors=_parse_ignored_authors(args.ignore_authors),
        ignore_draft_bots=bool(args.ignore_draft_bots),
    )
    if not events:
        _atomic_write_text(state_file, json.dumps(serialize_state(current), indent=2))
        return 1

    payload = {
        "detected_at": datetime.now(UTC).isoformat(),
        "author": author,
        "events": events,
    }
    _atomic_write_text(pending_file, json.dumps(payload, indent=2, ensure_ascii=False))
    _atomic_write_text(state_file, json.dumps(serialize_state(current), indent=2))

    if args.notify_cmd:
        try:
            _run_notify(args.notify_cmd, format_instant_alert(events, footer=args.footer))
        except Exception as exc:
            print(f"pr-watch notify warning: {exc}", file=sys.stderr)

    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        env = _gh_env(args.gh_user or None)
        author = _resolve_author(args.author, env)
        raw_prs = _fetch_open_prs(author, args.org or None, env)
    except Exception as exc:
        print(f"pr-watch error: {exc}", file=sys.stderr)
        return 2

    current = {s["key"]: s for s in (summarize_pr(pr, author) for pr in raw_prs)}
    if args.action == "status":
        return _run_status(current, author, args.org or None)
    return _run_check(args, current, author)
