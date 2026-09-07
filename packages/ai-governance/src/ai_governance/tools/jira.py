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
    jira transition <ISSUE-KEY> "<Status>"           Move issue to target status
    jira assign <ISSUE-KEY> [me|<email>]             Assign issue to user
    jira sprint <ISSUE-KEY> <name|active>            Move issue to a sprint (Agile API)
    jira help                                        Display this help message
"""

import base64
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

EMAIL = os.environ.get("ATLASSIAN_EMAIL", "")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN", "")
BASE_URL = os.environ.get("ATLASSIAN_URL", "").rstrip("/")
ATLASSIAN_TIMEOUT = float(os.environ.get("ATLASSIAN_TIMEOUT", "30.0"))


def _get_base_url():
    return os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/")


def _get_api_url():
    return f"{_get_base_url()}/rest/api/3"


def _get_agile_url():
    return f"{_get_base_url()}/rest/agile/1.0"


def check_env():
    """Validates required environment variables."""
    missing = [
        v
        for v in ["ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "ATLASSIAN_URL"]
        if not os.environ.get(v)
    ]
    if missing:
        print("Error: Missing required environment variables:")
        for v in missing:
            print(f'  export {v}="..."')
        print("\nTo configure them in ~/.zshrc:")
        print('  export ATLASSIAN_EMAIL="your-email@company.com"')
        print('  export ATLASSIAN_URL="https://company.atlassian.net"')
        print(
            '  ATLASSIAN_API_TOKEN="$(security find-generic-password -s atlassian-api-token -w 2>/dev/null)"'
        )
        print("  export ATLASSIAN_API_TOKEN")
        sys.exit(1)


def _auth_header():
    email = os.environ.get("ATLASSIAN_EMAIL", EMAIL)
    token = os.environ.get("ATLASSIAN_API_TOKEN", TOKEN)
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method, path, payload=None, base=None):
    check_env()
    base_endpoint = base if base is not None else _get_api_url()
    url = f"{base_endpoint}{path}"
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=_auth_header(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=ATLASSIAN_TIMEOUT) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            msg = json.loads(err)
            err = json.dumps(msg, indent=2)
        except Exception:
            pass
        print(f"HTTP {e.code} Error calling {method} {path}:\n{err}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error calling {method} {path}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def get(path):
    return _request("GET", path)


def post(path, payload):
    return _request("POST", path, payload)


def put(path, payload):
    return _request("PUT", path, payload)


def agile_get(path):
    return _request("GET", path, base=_get_agile_url())


def agile_post(path, payload):
    return _request("POST", path, payload, base=_get_agile_url())


def _adf_to_md(node):
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


def _fmt_date(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _inline_to_adf(text):
    nodes = []
    tokens = re.split(r"(\*\*.*?\*\*|`.*?`)", text)
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) >= 4:
            nodes.append({"type": "text", "text": token[2:-2], "marks": [{"type": "strong"}]})
        elif token.startswith("`") and token.endswith("`") and len(token) >= 2:
            nodes.append({"type": "text", "text": token[1:-1], "marks": [{"type": "code"}]})
        else:
            nodes.append({"type": "text", "text": token})
    return nodes


def _is_table_separator(line):
    line = line.strip()
    return bool(
        line.startswith("|") and line.endswith("|") and re.match(r"^\|(\s*:?-+:?\s*\|)+$", line)
    )


def _parse_table_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _table_to_adf(lines):
    rows = []
    for i, line in enumerate(lines):
        cell_type = "tableHeader" if i == 0 else "tableCell"
        row_content = []
        for cell_text in _parse_table_row(line):
            row_content.append(
                {
                    "type": cell_type,
                    "content": [{"type": "paragraph", "content": _inline_to_adf(cell_text)}],
                }
            )
        rows.append({"type": "tableRow", "content": row_content})
    return {"type": "table", "content": rows}


def _md_to_adf(text):
    content = []
    bullet_accum = []
    table_accum = []

    def flush_bullets():
        if bullet_accum:
            content.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": _inline_to_adf(item)}],
                        }
                        for item in bullet_accum
                    ],
                }
            )
            bullet_accum.clear()

    def flush_table():
        if table_accum:
            data_rows = [r for r in table_accum if not _is_table_separator(r)]
            if len(data_rows) >= 2:
                content.append(_table_to_adf(data_rows))
            else:
                for r in table_accum:
                    content.append({"type": "paragraph", "content": _inline_to_adf(r)})
            table_accum.clear()

    for line in text.split("\n"):
        if line.strip().startswith("|") and line.strip().endswith("|"):
            flush_bullets()
            table_accum.append(line)
            continue
        else:
            flush_table()

        if line.startswith("- "):
            bullet_accum.append(line[2:].strip())
        elif line.strip() == "":
            flush_bullets()
        else:
            flush_bullets()
            content.append({"type": "paragraph", "content": _inline_to_adf(line)})

    flush_bullets()
    flush_table()
    return {"version": 1, "type": "doc", "content": content}


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_issue(key):
    """Displays issue in clean Markdown."""
    data = get(
        f"/issue/{key}?fields=summary,status,assignee,reporter,priority,issuetype,description,created,updated,labels,comment"
    )
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


def cmd_search(jql):
    """Searches issues using JQL."""
    data = post(
        "/search/jql",
        {
            "jql": jql,
            "maxResults": 30,
            "fields": ["key", "summary", "status", "assignee", "priority", "issuetype"],
        },
    )
    issues = data.get("issues", [])
    total = data.get("total", 0)
    if not issues:
        print("_No results found._")
        return

    print(f"## Results ({len(issues)} of {total})\n")
    print("| Key | Type | Status | Assignee | Title |")
    print("|---|---|---|---|---|")
    for i in issues:
        f = i.get("fields", {})
        assignee = (f.get("assignee") or {}).get("displayName", "—")
        status = f.get("status", {}).get("name", "—")
        itype = f.get("issuetype", {}).get("name", "—")
        print(f"| {i['key']} | {itype} | {status} | {assignee} | {f.get('summary', '')} |")


def cmd_comments(key):
    """Displays all comments on an issue."""
    data = get(f"/issue/{key}/comment?orderBy=created")
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


def cmd_create(project, summary, desc="", issue_type="Task", parent=None):
    """Creates a new issue in Jira. With --parent, creates a sub-task."""
    fields = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if parent:
        fields["parent"] = {"key": parent}
    if desc:
        fields["description"] = _md_to_adf(desc)
    data = post("/issue", {"fields": fields})
    key = data.get("key", "")
    print(f"✅ Issue created: **{key}** — {summary}")
    print(f"   {_get_base_url()}/browse/{key}")


def cmd_comment(key, text):
    """Adds a comment to an issue."""
    data = post(f"/issue/{key}/comment", {"body": _md_to_adf(text)})
    print(f"✅ Comment added to {key}")
    print(f"   id: {data.get('id', '')}")


def cmd_comment_edit(key, comment_id, text):
    """Replaces the body of an existing comment."""
    put(f"/issue/{key}/comment/{comment_id}", {"body": _md_to_adf(text)})
    print(f"✅ Comment {comment_id} edited on {key}")


def cmd_transition(key, state_name):
    """Moves an issue to target status."""
    data = get(f"/issue/{key}/transitions")
    transitions = data.get("transitions", [])
    match = next((t for t in transitions if state_name.lower() in t["name"].lower()), None)
    if not match:
        available = [t["name"] for t in transitions]
        print(f"❌ Status '{state_name}' not found.")
        print(f"   Available: {', '.join(available)}")
        sys.exit(1)
    post(f"/issue/{key}/transitions", {"transition": {"id": match["id"]}})
    print(f"✅ {key} → {match['name']}")


def cmd_assign(key, who):
    """Assigns an issue. Use 'me' to assign to yourself."""
    if who == "me":
        me = get("/myself")
        account_id = me.get("accountId")
    else:
        results = get(f"/user/search?query={who}")
        if not results:
            print(f"❌ User '{who}' not found.")
            sys.exit(1)
        account_id = results[0].get("accountId")
    put(f"/issue/{key}/assignee", {"accountId": account_id})
    print(f"✅ {key} assigned to {'you' if who == 'me' else who}")


def cmd_sprint(key, name):
    """Moves an issue to a sprint."""
    project = key.split("-")[0]
    boards = agile_get(f"/board?projectKeyOrId={project}").get("values", [])
    if not boards:
        print(f"❌ Project '{project}' has no boards.")
        sys.exit(1)
    board_id = boards[0]["id"]

    sprints = agile_get(f"/board/{board_id}/sprint").get("values", [])

    if name.lower() == "active":
        match = next((s for s in sprints if s.get("state") == "active"), None)
        if not match:
            print(f"❌ No active sprint found on board {board_id}.")
            sys.exit(1)
    else:
        match = next((s for s in sprints if name.lower() in s.get("name", "").lower()), None)
        if not match:
            available = [f"'{s['name']}' ({s.get('state')})" for s in sprints]
            print(f"❌ Sprint '{name}' not found on board {board_id}.")
            print(f"   Available sprints: {', '.join(available) or 'none'}")
            sys.exit(1)

    sprint_id = match["id"]
    sprint_name = match["name"]

    agile_post(f"/sprint/{sprint_id}/issue", {"issues": [key]})
    print(f"✅ {key} moved to sprint **{sprint_name}** (id: {sprint_id})")


def cmd_help():
    print(
        textwrap.dedent("""
        jira — Lightweight CLI for Jira REST API v3
        ===========================================

        READ:
          jira issue  <KEY>                       Display issue in clean Markdown
          jira search "<JQL>"                     Search issues using JQL
          jira comments <KEY>                     Display issue comments

        WRITE:
          jira create <PROJECT> "<Title>"         Create issue (default: Task)
            [--desc "<text>"]                     Description (supports basic Markdown)
            [--type Bug|Task|Story|Sub-task]
            [--parent <KEY>]                      Parent issue for Sub-task
          jira comment <KEY> "<text>"             Add comment (supports basic Markdown)
          jira comment-edit <KEY> <ID> "<text>"   Replace body of an existing comment
          jira transition <KEY> "<Status>"        Move issue to status
          jira assign <KEY> me|<email>            Assign issue
          jira sprint <KEY> active|<name>         Move issue to active sprint or by name

        EXAMPLES:
          jira issue ONB-1125
          jira search "project=ONB AND sprint in openSprints()"
          jira create ONB "Title of bug" --type Bug --desc "Steps to reproduce"
          jira create ONB "Sub-task X" --type Sub-task --parent ONB-1154
          jira comment ONB-1125 "Investigated code, root cause identified"
          jira transition ONB-1125 "In Progress"
          jira assign ONB-1125 me
          jira sprint ONB-1230 active
    """).strip()
    )


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        cmd_help()
        return

    cmd = args[0]
    if cmd == "issue" and len(args) >= 2:
        cmd_issue(args[1])
    elif cmd == "search" and len(args) >= 2:
        cmd_search(args[1])
    elif cmd == "comments" and len(args) >= 2:
        cmd_comments(args[1])
    elif cmd == "create" and len(args) >= 3:
        desc, itype, parent = "", "Task", None
        i = 3
        while i < len(args):
            if args[i] == "--desc" and i + 1 < len(args):
                desc = args[i + 1]
                i += 2
            elif args[i] == "--type" and i + 1 < len(args):
                itype = args[i + 1]
                i += 2
            elif args[i] == "--parent" and i + 1 < len(args):
                parent = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_create(args[1], args[2], desc=desc, issue_type=itype, parent=parent)
    elif cmd == "comment" and len(args) >= 3:
        cmd_comment(args[1], args[2])
    elif cmd == "comment-edit" and len(args) >= 4:
        cmd_comment_edit(args[1], args[2], args[3])
    elif cmd == "transition" and len(args) >= 3:
        cmd_transition(args[1], args[2])
    elif cmd == "assign" and len(args) >= 3:
        cmd_assign(args[1], args[2])
    elif cmd == "sprint" and len(args) >= 3:
        cmd_sprint(args[1], args[2])
    else:
        print(f"Unknown command or invalid arguments: {' '.join(args)}\nRun 'jira help'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
