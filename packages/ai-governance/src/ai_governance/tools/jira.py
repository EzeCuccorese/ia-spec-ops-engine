#!/usr/bin/env python3
"""
jira — Lightweight CLI for Jira REST API v3
===========================================

Reads and writes to Jira via REST API v3, returning clean Markdown without bloated JSON.
Designed for Antigravity, Claude Code, and terminal agents with zero token overhead.

Requirements (environment variables in ~/.zshrc):
    ATLASSIAN_EMAIL      your-email@company.com
    ATLASSIAN_API_TOKEN  token generated at id.atlassian.com
    ATLASSIAN_URL        https://company.atlassian.net

Usage:
    jira issue  <ISSUE-KEY>                          Display issue in clean Markdown
    jira search "<JQL>"                              Search issues using JQL
    jira comments <ISSUE-KEY>                        Display all comments on an issue
    jira create <PROJECT-KEY> "<Title>" [--desc "<text>"] [--type Bug|Task|Story|Sub-task] [--parent <KEY>]
    jira comment <ISSUE-KEY> "<text>"               Add comment (supports Markdown, see 'jira help')
    jira comment-edit <ISSUE-KEY> <ID> "<text>"     Replace body of an existing comment
    jira edit <ISSUE-KEY> [--desc ...] [--title ...]  Replace description and/or title
    jira transition <ISSUE-KEY> "<Status>"           Move issue to target status
    jira assign <ISSUE-KEY> [me|<email>]             Assign issue to user
    jira sprint <ISSUE-KEY> <name|active>            Move issue to a sprint (Agile API)
    jira help                                        Display this help message
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime
from typing import Any

from ai_governance.tools.atlassian_common import (
    ATLASSIAN_TIMEOUT,
    auth_header,
    execute_request,
    get_base_url,
    read_input_text,
    set_profile,
)
from ai_governance.tools.atlassian_common import (
    check_env as check_env,
)
from ai_governance.tools.atlassian_common import (
    load_profile_config as load_profile_config,
)
from ai_governance.tools.atlassian_common import (
    sanitize_secrets as sanitize_secrets,
)

# ── Configuration & Profiles (Shared with Atlassian Common) ─────────────────
from ai_governance.tools.md_adf import md_to_adf

_auth_header = auth_header
_get_base_url = get_base_url


def _get_api_url() -> str:
    return f"{_get_base_url()}/rest/api/3"


def _get_agile_url() -> str:
    return f"{_get_base_url()}/rest/agile/1.0"


def _request(
    method: str, path: str, payload: dict[str, Any] | None = None, base: str | None = None
) -> Any:
    base_endpoint = base if base is not None else _get_api_url()
    url = f"{base_endpoint}{path}"
    return execute_request(method, url, payload=payload, timeout=ATLASSIAN_TIMEOUT)


def get(path: str) -> Any:
    return _request("GET", path)


def post(path: str, payload: dict[str, Any]) -> Any:
    return _request("POST", path, payload)


def put(path: str, payload: dict[str, Any]) -> Any:
    return _request("PUT", path, payload)


def agile_get(path: str) -> Any:
    return _request("GET", path, base=_get_agile_url())


def agile_post(path: str, payload: dict[str, Any]) -> Any:
    return _request("POST", path, payload, base=_get_agile_url())


def _adf_to_md(node: Any) -> str:
    """Converts Atlassian Document Format (ADF) to clean Markdown."""
    if not node or not isinstance(node, dict):
        return ""
    ntype = node.get("type", "")
    content = node.get("content", [])

    if ntype == "text":
        text = node.get("text", "")
        for m in node.get("marks", []):
            mtype = m.get("type")
            if mtype == "strong":
                text = f"**{text}**"
            elif mtype == "em":
                text = f"*{text}*"
            elif mtype == "code":
                text = f"`{text}`"
            elif mtype == "strike":
                text = f"~~{text}~~"
            elif mtype == "link":
                text = f"[{text}]({m.get('attrs', {}).get('href', '')})"
        return text

    inner = "".join(_adf_to_md(c) for c in content)

    if ntype == "paragraph":
        return f"{inner}\n\n"
    elif ntype == "heading":
        level = node.get("attrs", {}).get("level", 2)
        return f"{'#' * level} {inner}\n\n"
    elif ntype == "bulletList":
        return "".join(f"- {_adf_to_md(item).strip()}\n" for item in content) + "\n"
    elif ntype == "orderedList":
        return (
            "".join(f"{i + 1}. {_adf_to_md(item).strip()}\n" for i, item in enumerate(content))
            + "\n"
        )
    elif ntype == "listItem":
        return inner.strip()
    elif ntype == "taskList":
        return "".join(f"- {_adf_to_md(item).strip()}\n" for item in content) + "\n"
    elif ntype == "taskItem":
        done = node.get("attrs", {}).get("state") == "DONE"
        return f"[{'x' if done else ' '}] {inner.strip()}"
    elif ntype == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        return f"```{lang}\n{inner.rstrip()}\n```\n\n"
    elif ntype == "blockquote":
        return f"> {inner.strip()}\n\n"
    elif ntype == "rule":
        return "---\n\n"
    elif ntype == "table":
        rows = []
        for row in content:
            cells = [_adf_to_md(cell).strip().replace("\n", " ") for cell in row.get("content", [])]
            rows.append("| " + " | ".join(cells) + " |")
        if len(rows) > 1:
            n_cols = len(content[0].get("content", []))
            sep = "| " + " | ".join(["---"] * n_cols) + " |"
            rows.insert(1, sep)
        return "\n".join(rows) + "\n\n"
    elif ntype in ("tableRow", "tableCell", "tableHeader"):
        return inner
    return inner


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16]


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_issue(key: str, as_json: bool = False) -> None:
    """Displays issue in clean Markdown or JSON."""
    data = get(
        f"/issue/{key}?fields=summary,status,assignee,reporter,priority,issuetype,description,created,updated,labels,comment"
    )
    if as_json:
        print(json.dumps(data, indent=2))
        return

    f = data.get("fields", {})
    assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
    reporter = (f.get("reporter") or {}).get("displayName", "—")
    status = f.get("status", {}).get("name", "—")
    priority = (f.get("priority") or {}).get("name", "—")
    itype = f.get("issuetype", {}).get("name", "—")
    labels = ", ".join(f.get("labels", [])) or "—"
    desc_raw = f.get("description")
    desc_md = _adf_to_md(desc_raw).strip() if desc_raw else "_No description_"

    print(f"# [{key}] {f.get('summary', '')}")
    print(f"\n**Type**: {itype}  |  **Status**: {status}  |  **Priority**: {priority}")
    print(f"**Assignee**: {assignee}  |  **Reporter**: {reporter}")
    print(f"**Labels**: {labels}")
    print(
        f"**Created**: {_fmt_date(f.get('created', ''))}  |  **Updated**: {_fmt_date(f.get('updated', ''))}"
    )
    print(f"\n## Description\n\n{desc_md}")

    comments = f.get("comment", {}).get("comments", [])
    if comments:
        print(f"\n## Recent Comments ({len(comments)} total)\n")
        for c in comments[-3:]:
            author = c.get("author", {}).get("displayName", "—")
            date = _fmt_date(c.get("created", ""))
            body = _adf_to_md(c.get("body")).strip()
            print(f"**{author}** — {date}\n{body}\n")


def cmd_search(
    jql: str, page_token: str | None = None, max_results: int = 30, as_json: bool = False
) -> None:
    """Searches issues using JQL. Jira pages with an opaque token, not with offsets."""
    payload: dict[str, Any] = {
        "jql": jql,
        "maxResults": max_results,
        "fields": ["key", "summary", "status", "assignee", "priority", "issuetype"],
    }
    if page_token:
        payload["nextPageToken"] = page_token
    data = post("/search/jql", payload)
    if as_json:
        print(json.dumps(data, indent=2))
        return

    issues = data.get("issues", [])
    if not issues:
        print("_No results found._")
        return

    print(f"## Results ({len(issues)} shown)\n")
    print("| Key | Type | Status | Assignee | Title |")
    print("|---|---|---|---|---|")
    for i in issues:
        f = i.get("fields", {})
        assignee = (f.get("assignee") or {}).get("displayName", "—")
        status = f.get("status", {}).get("name", "—")
        itype = f.get("issuetype", {}).get("name", "—")
        print(f"| {i['key']} | {itype} | {status} | {assignee} | {f.get('summary', '')} |")

    next_token = data.get("nextPageToken")
    if next_token:
        print(f"\n_More results exist. Use --page-token {next_token} to view the next page._")


def cmd_comments(key: str, as_json: bool = False) -> None:
    """Displays all comments on an issue."""
    data = get(f"/issue/{key}/comment?orderBy=created")
    if as_json:
        print(json.dumps(data, indent=2))
        return

    comments = data.get("comments", [])
    if not comments:
        print("_No comments._")
        return

    summary = get(f"/issue/{key}?fields=summary").get("fields", {}).get("summary", "")
    print(f"# Comments on {key}: {summary}\n")
    for c in comments:
        author = c.get("author", {}).get("displayName", "—")
        date = _fmt_date(c.get("created", ""))
        body = _adf_to_md(c.get("body")).strip()
        print(f"---\n**{author}** — {date} — id: {c.get('id', '—')}\n\n{body}\n")


def cmd_create(
    project: str,
    summary: str,
    desc: str = "",
    issue_type: str = "Task",
    parent: str | None = None,
) -> None:
    """Creates a new issue in Jira. With --parent, creates a sub-task."""
    fields = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if parent:
        fields["parent"] = {"key": parent}
    if desc:
        desc_text = read_input_text(desc)
        fields["description"] = md_to_adf(desc_text)
    data = post("/issue", {"fields": fields})
    key = data.get("key", "")
    print(f"✅ Issue created: **{key}** — {summary}")
    print(f"   {_get_base_url()}/browse/{key}")


def cmd_comment(key: str, text: str) -> None:
    """Adds a comment to an issue."""
    comment_text = read_input_text(text)
    data = post(f"/issue/{key}/comment", {"body": md_to_adf(comment_text)})
    print(f"✅ Comment added to {key}")
    print(f"   id: {data.get('id', '')}")


def cmd_comment_edit(key: str, comment_id: str, text: str) -> None:
    """Replaces the body of an existing comment."""
    comment_text = read_input_text(text)
    put(f"/issue/{key}/comment/{comment_id}", {"body": md_to_adf(comment_text)})
    print(f"✅ Comment {comment_id} edited on {key}")


def cmd_edit(key: str, desc: str | None = None, title: str | None = None) -> None:
    """Replaces the description and/or the title of an existing issue."""
    fields: dict[str, Any] = {}
    if desc is not None:
        fields["description"] = md_to_adf(read_input_text(desc))
    if title:
        fields["summary"] = title
    if not fields:
        print("❌ Nothing to edit: pass --desc and/or --title.", file=sys.stderr)
        sys.exit(1)
    put(f"/issue/{key}", {"fields": fields})
    print(f"✅ Issue {key} updated ({', '.join(sorted(fields))})")


def cmd_transition(key: str, state_name: str) -> None:
    """Moves an issue to target status with strict ambiguous match protection."""
    data = get(f"/issue/{key}/transitions")
    transitions = data.get("transitions", [])

    # 1. Exact case-insensitive match takes precedence
    exact_matches = [
        t for t in transitions if state_name.strip().lower() == t.get("name", "").strip().lower()
    ]
    if len(exact_matches) == 1:
        match = exact_matches[0]
    else:
        # 2. Substring matching
        matches = [
            t
            for t in transitions
            if state_name.strip().lower() in t.get("name", "").strip().lower()
        ]
        if not matches:
            available = [t.get("name", "") for t in transitions]
            print(f"❌ Status '{state_name}' not found.", file=sys.stderr)
            print(f"   Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        elif len(matches) > 1:
            available = [t.get("name", "") for t in matches]
            print(
                f"❌ Ambiguous status '{state_name}': multiple transitions match.", file=sys.stderr
            )
            print(f"   Available choices: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        else:
            match = matches[0]

    post(f"/issue/{key}/transitions", {"transition": {"id": match["id"]}})
    print(f"✅ {key} → {match['name']}")


def cmd_assign(key: str, who: str) -> None:
    """Assigns an issue. Use 'me' to assign to yourself. Strictly rejects ambiguous user matches."""
    if who == "me":
        me = get("/myself")
        account_id = me.get("accountId")
    else:
        results = get(f"/user/search?query={who}")
        if not results:
            print(f"❌ User '{who}' not found.", file=sys.stderr)
            sys.exit(1)

        # Exact match on email or displayName
        exact_matches = [
            u
            for u in results
            if who.strip().lower()
            in (
                u.get("emailAddress", "").strip().lower(),
                u.get("displayName", "").strip().lower(),
            )
        ]
        if len(exact_matches) == 1:
            account_id = exact_matches[0].get("accountId")
        elif len(results) > 1:
            choices = [
                f"{u.get('displayName', 'Unknown')} ({u.get('emailAddress', 'no email')})"
                for u in results
            ]
            print(f"❌ Ambiguous user '{who}': multiple matches found.", file=sys.stderr)
            print(f"   Available choices: {', '.join(choices)}", file=sys.stderr)
            sys.exit(1)
        else:
            account_id = results[0].get("accountId")

    put(f"/issue/{key}/assignee", {"accountId": account_id})
    print(f"✅ {key} assigned to {'you' if who == 'me' else who}")


def cmd_sprint(key: str, name: str) -> None:
    """Moves an issue to a sprint."""
    project = key.split("-")[0]
    boards = agile_get(f"/board?projectKeyOrId={project}").get("values", [])
    if not boards:
        print(f"❌ Project '{project}' has no boards.", file=sys.stderr)
        sys.exit(1)
    board_id = boards[0]["id"]

    sprints = agile_get(f"/board/{board_id}/sprint").get("values", [])

    if name.lower() == "active":
        match = next((s for s in sprints if s.get("state") == "active"), None)
        if not match:
            print(f"❌ No active sprint found on board {board_id}.", file=sys.stderr)
            sys.exit(1)
    else:
        matches = [s for s in sprints if name.lower() in s.get("name", "").lower()]
        if not matches:
            available = [f"'{s['name']}' ({s.get('state')})" for s in sprints]
            print(f"❌ Sprint '{name}' not found on board {board_id}.", file=sys.stderr)
            print(f"   Available sprints: {', '.join(available) or 'none'}", file=sys.stderr)
            sys.exit(1)
        elif len(matches) > 1:
            available = [f"'{s['name']}' (id: {s.get('id')})" for s in matches]
            print(f"❌ Ambiguous sprint '{name}': multiple sprints match.", file=sys.stderr)
            print(f"   Available choices: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        else:
            match = matches[0]

    sprint_id = match["id"]
    sprint_name = match["name"]

    agile_post(f"/sprint/{sprint_id}/issue", {"issues": [key]})
    print(f"✅ {key} moved to sprint **{sprint_name}** (id: {sprint_id})")


def cmd_help() -> None:
    print(
        textwrap.dedent("""
        jira — Lightweight CLI for Jira REST API v3
        ===========================================

        READ:
          jira issue  <KEY> [--json]              Display issue in clean Markdown or JSON
          jira search "<JQL>" [--page-token <T>]   Search issues using JQL with pagination
            [--limit <N>] [--json]
          jira comments <KEY> [--json]            Display issue comments

        WRITE:
          jira create <PROJECT> "<Title>"         Create issue (default: Task)
            [--desc "<text>|@file|-"]             Description (supports Markdown)
            [--type Bug|Task|Story|Sub-task]
            [--parent <KEY>]                      Parent issue for Sub-task
          jira comment <KEY> "<text>|@file|-"     Add comment (supports Markdown)
          jira comment-edit <KEY> <ID> "<text>"   Replace body of an existing comment
          jira edit <KEY> [--desc "<text>|@file|-"]  Replace the description (Markdown)
            [--title "<Title>"]                   and/or the title
          jira transition <KEY> "<Status>"        Move issue to status (strictly checked)
          jira assign <KEY> me|<email>            Assign issue (strictly checked)
          jira sprint <KEY> active|<name>         Move issue to sprint

        GLOBAL OPTIONS:
          --profile <NAME>                        Use named configuration profile
    """).strip()
    )


# name -> (help, positionals). Every subcommand also takes the common flags below.
COMMANDS: dict[str, tuple[str, tuple[tuple[str, dict[str, Any]], ...]]] = {
    "issue": ("Display an issue in Markdown or JSON", (("key", {"help": "Issue key"}),)),
    "search": ("Search issues with JQL", (("jql", {"help": "JQL query"}),)),
    "comments": ("Display the comments of an issue", (("key", {"help": "Issue key"}),)),
    "create": (
        "Create an issue (default type: Task)",
        (("project", {"help": "Project key"}), ("title", {"help": "Issue title"})),
    ),
    "comment": (
        "Add a comment (Markdown; text, @file or -)",
        (("key", {"help": "Issue key"}), ("text", {"nargs": "?", "help": "Comment text"})),
    ),
    "comment-edit": (
        "Replace the body of an existing comment",
        (
            ("key", {"help": "Issue key"}),
            ("comment_id", {"help": "Comment id"}),
            ("text", {"nargs": "?", "help": "New comment text"}),
        ),
    ),
    "edit": (
        "Replace the description and/or title of an issue",
        (("key", {"help": "Issue key"}),),
    ),
    "transition": (
        "Move an issue to a status (strictly checked)",
        (("key", {"help": "Issue key"}), ("status", {"help": "Target status name"})),
    ),
    "assign": (
        "Assign an issue to me or an email",
        (("key", {"help": "Issue key"}), ("assignee", {"help": "me or an email"})),
    ),
    "sprint": (
        "Move an issue to the active sprint or a named one",
        (("key", {"help": "Issue key"}), ("sprint", {"help": "active or a sprint name"})),
    ),
}


def _common_flags(parser: argparse.ArgumentParser, *, root: bool) -> None:
    """Flags accepted before and after the subcommand (`jira --json issue X` and
    `jira issue X --json`). Subcommands leave them unset so the root value survives."""
    unset: dict[str, Any] = {} if root else {"default": argparse.SUPPRESS}
    parser.add_argument("--profile", help="Use a named configuration profile", **unset)
    parser.add_argument("--json", action="store_true", help="Print the raw JSON", **unset)
    parser.add_argument("--file", help="Read the text from this file", **unset)


def _paging_flags(parser: argparse.ArgumentParser, *, root: bool) -> None:
    token: Any = None if root else argparse.SUPPRESS
    limit: Any = 30 if root else argparse.SUPPRESS
    parser.add_argument("--page-token", default=token, help="Token of the next page (from search)")
    parser.add_argument(
        "--limit", "--max-results", dest="max_results", type=int, default=limit, help="Page size"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jira", add_help=False)
    parser.add_argument(
        "-h", "--help", action="store_true", dest="show_help", help="Show the command overview"
    )
    _common_flags(parser, root=True)
    _paging_flags(parser, root=True)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("help", help="Show the command overview")
    for name, (help_text, positionals) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        for dest, options in positionals:
            command.add_argument(dest, **options)
        _common_flags(command, root=False)
    _paging_flags(sub.choices["search"], root=False)
    edit = sub.choices["edit"]
    edit.add_argument("--desc", help="New description: Markdown text, @file or -")
    edit.add_argument("--title", help="New title")
    create = sub.choices["create"]
    create.add_argument("--desc", help="Description: Markdown text, @file or -")
    create.add_argument("--type", default="Task", help="Bug, Task, Story or Sub-task")
    create.add_argument("--parent", help="Parent issue (for a Sub-task)")
    return parser


def _text(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    text = args.file or args.text
    if not text:
        parser.error(f"{args.command} needs a text or --file")
    return str(text)


HANDLERS: dict[str, Any] = {
    "issue": lambda a, _p: cmd_issue(a.key, as_json=a.json),
    "search": lambda a, _p: cmd_search(
        a.jql, page_token=a.page_token, max_results=a.max_results, as_json=a.json
    ),
    "comments": lambda a, _p: cmd_comments(a.key, as_json=a.json),
    "create": lambda a, _p: cmd_create(
        a.project,
        a.title,
        desc=a.desc if a.desc is not None else (a.file or ""),
        issue_type=a.type,
        parent=a.parent,
    ),
    "comment": lambda a, p: cmd_comment(a.key, _text(a, p)),
    "comment-edit": lambda a, p: cmd_comment_edit(a.key, a.comment_id, _text(a, p)),
    "edit": lambda a, _p: cmd_edit(
        a.key, desc=a.desc if a.desc is not None else a.file, title=a.title
    ),
    "transition": lambda a, _p: cmd_transition(a.key, a.status),
    "assign": lambda a, _p: cmd_assign(a.key, a.assignee),
    "sprint": lambda a, _p: cmd_sprint(a.key, a.sprint),
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.show_help or args.command in (None, "help"):
        cmd_help()
        return
    if args.profile:
        set_profile(args.profile)
    HANDLERS[args.command](args, parser)


if __name__ == "__main__":
    main()
