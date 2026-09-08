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
from pathlib import Path

# ── Configuration & Profiles ──────────────────────────────────────────────────

EMAIL = os.environ.get("ATLASSIAN_EMAIL", "")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN", "")
BASE_URL = os.environ.get("ATLASSIAN_URL", "").rstrip("/")
ATLASSIAN_TIMEOUT = float(os.environ.get("ATLASSIAN_TIMEOUT", "30.0"))

_CURRENT_PROFILE: str | None = None
_PROFILE_OVERRIDES: dict[str, dict[str, str]] = {}


def set_profile(name: str | None) -> None:
    """Sets the active configuration profile for Jira operations."""
    global _CURRENT_PROFILE
    _CURRENT_PROFILE = name


def load_profile_config(profile_name: str | None = None) -> dict[str, str]:
    """Loads configuration for the requested profile from memory, config files, or environment."""
    target = profile_name or _CURRENT_PROFILE or os.environ.get("ATLASSIAN_PROFILE")
    if not target or target.lower() == "default":
        return {
            "email": os.environ.get("ATLASSIAN_EMAIL", EMAIL),
            "token": os.environ.get("ATLASSIAN_API_TOKEN", TOKEN),
            "url": os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/"),
        }

    # 1. Check in-memory overrides
    if target in _PROFILE_OVERRIDES:
        return dict(_PROFILE_OVERRIDES[target])

    # 2. Check profiles file
    profiles_paths = []
    if os.environ.get("ATLASSIAN_PROFILES_FILE"):
        profiles_paths.append(Path(os.environ["ATLASSIAN_PROFILES_FILE"]))
    profiles_paths.append(Path.home() / ".config" / "atlassian" / "profiles.json")
    profiles_paths.append(Path.home() / ".specops" / "atlassian.json")

    for p in profiles_paths:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if target in data and isinstance(data[target], dict):
                    prof = data[target]
                    return {
                        "email": prof.get("email", ""),
                        "token": prof.get("token", prof.get("api_token", "")),
                        "url": prof.get("url", "").rstrip("/"),
                    }
            except Exception:
                continue

    # 3. Check environment variables: ATLASSIAN_{PROFILE}_EMAIL, etc.
    p_upper = target.upper().replace("-", "_")
    email = os.environ.get(f"ATLASSIAN_{p_upper}_EMAIL") or os.environ.get(
        f"ATLASSIAN_EMAIL_{p_upper}"
    )
    token = os.environ.get(f"ATLASSIAN_{p_upper}_API_TOKEN") or os.environ.get(
        f"ATLASSIAN_API_TOKEN_{p_upper}"
    )
    url = os.environ.get(f"ATLASSIAN_{p_upper}_URL") or os.environ.get(f"ATLASSIAN_URL_{p_upper}")

    return {
        "email": email or os.environ.get("ATLASSIAN_EMAIL", EMAIL),
        "token": token or os.environ.get("ATLASSIAN_API_TOKEN", TOKEN),
        "url": (url or os.environ.get("ATLASSIAN_URL", BASE_URL)).rstrip("/"),
    }


def _get_base_url():
    cfg = load_profile_config()
    return cfg.get("url") or os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/")


def _get_api_url():
    return f"{_get_base_url()}/rest/api/3"


def _get_agile_url():
    return f"{_get_base_url()}/rest/agile/1.0"


def check_env():
    """Validates required environment variables or profile settings."""
    cfg = load_profile_config()
    missing = []
    if not cfg.get("email"):
        missing.append("ATLASSIAN_EMAIL")
    if not cfg.get("token"):
        missing.append("ATLASSIAN_API_TOKEN")
    if not cfg.get("url"):
        missing.append("ATLASSIAN_URL")
    if missing:
        print(
            "Error: Missing required environment variables or profile configuration:",
            file=sys.stderr,
        )
        for v in missing:
            print(f'  export {v}="..."', file=sys.stderr)
        sys.exit(1)


def _auth_header():
    cfg = load_profile_config()
    email = cfg.get("email") or os.environ.get("ATLASSIAN_EMAIL", EMAIL)
    token = cfg.get("token") or os.environ.get("ATLASSIAN_API_TOKEN", TOKEN)
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def sanitize_secrets(msg: str) -> str:
    """Sanitizes sensitive tokens, auth headers, and secrets from error messages."""
    cfg = load_profile_config()
    tokens = [
        cfg.get("token"),
        os.environ.get("ATLASSIAN_API_TOKEN"),
        TOKEN,
    ]
    for t in tokens:
        if t and len(t) >= 4:
            msg = msg.replace(t, "[REDACTED_TOKEN]")
    msg = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [REDACTED]", msg)
    msg = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", msg)
    return msg


def read_input_text(source: str) -> str:
    """Reads text from literal string, stdin ('-'), or file path ('@path' or path if exists)."""
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        path = Path(source[1:])
        if path.is_file():
            return path.read_text(encoding="utf-8")
    p = Path(source)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return source


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
        sanitized = sanitize_secrets(err)
        print(f"HTTP {e.code} Error calling {method} {path}:\n{sanitized}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        sanitized = sanitize_secrets(str(e.reason))
        print(f"Network error calling {method} {path}: {sanitized}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        sanitized = sanitize_secrets(str(e))
        print(f"Timeout error calling {method} {path}: {sanitized}", file=sys.stderr)
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


def cmd_issue(key, as_json=False):
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


def cmd_search(jql, start_at=0, max_results=30, as_json=False):
    """Searches issues using JQL with pagination support."""
    data = post(
        "/search/jql",
        {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["key", "summary", "status", "assignee", "priority", "issuetype"],
        },
    )
    if as_json:
        print(json.dumps(data, indent=2))
        return

    issues = data.get("issues", [])
    total = data.get("total", len(issues))
    start = data.get("startAt", start_at)
    if not issues:
        print("_No results found._")
        return

    print(f"## Results ({start + 1}-{start + len(issues)} of {total})\n")
    print("| Key | Type | Status | Assignee | Title |")
    print("|---|---|---|---|---|")
    for i in issues:
        f = i.get("fields", {})
        assignee = (f.get("assignee") or {}).get("displayName", "—")
        status = f.get("status", {}).get("name", "—")
        itype = f.get("issuetype", {}).get("name", "—")
        print(f"| {i['key']} | {itype} | {status} | {assignee} | {f.get('summary', '')} |")

    if total > start + len(issues):
        print(
            f"\n_More results exist ({start + len(issues)} of {total} shown). Use --start-at {start + len(issues)} to view next page._"
        )


def cmd_comments(key, as_json=False):
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
        desc_text = read_input_text(desc)
        fields["description"] = _md_to_adf(desc_text)
    data = post("/issue", {"fields": fields})
    key = data.get("key", "")
    print(f"✅ Issue created: **{key}** — {summary}")
    print(f"   {_get_base_url()}/browse/{key}")


def cmd_comment(key, text):
    """Adds a comment to an issue."""
    comment_text = read_input_text(text)
    data = post(f"/issue/{key}/comment", {"body": _md_to_adf(comment_text)})
    print(f"✅ Comment added to {key}")
    print(f"   id: {data.get('id', '')}")


def cmd_comment_edit(key, comment_id, text):
    """Replaces the body of an existing comment."""
    comment_text = read_input_text(text)
    put(f"/issue/{key}/comment/{comment_id}", {"body": _md_to_adf(comment_text)})
    print(f"✅ Comment {comment_id} edited on {key}")


def cmd_transition(key, state_name):
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


def cmd_assign(key, who):
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


def cmd_sprint(key, name):
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


def cmd_help():
    print(
        textwrap.dedent("""
        jira — Lightweight CLI for Jira REST API v3
        ===========================================

        READ:
          jira issue  <KEY> [--json]              Display issue in clean Markdown or JSON
          jira search "<JQL>" [--start-at <N>]    Search issues using JQL with pagination
            [--limit <N>] [--json]
          jira comments <KEY> [--json]            Display issue comments

        WRITE:
          jira create <PROJECT> "<Title>"         Create issue (default: Task)
            [--desc "<text>|@file|-"]             Description (supports Markdown)
            [--type Bug|Task|Story|Sub-task]
            [--parent <KEY>]                      Parent issue for Sub-task
          jira comment <KEY> "<text>|@file|-"     Add comment (supports Markdown)
          jira comment-edit <KEY> <ID> "<text>"   Replace body of an existing comment
          jira transition <KEY> "<Status>"        Move issue to status (strictly checked)
          jira assign <KEY> me|<email>            Assign issue (strictly checked)
          jira sprint <KEY> active|<name>         Move issue to sprint

        GLOBAL OPTIONS:
          --profile <NAME>                        Use named configuration profile
    """).strip()
    )


def main():
    raw_args = sys.argv[1:]
    if not raw_args or raw_args[0] in ("-h", "--help", "help"):
        cmd_help()
        return

    # Extract global flags
    args = []
    i = 0
    as_json = False
    start_at = 0
    max_results = 30
    file_input = None

    while i < len(raw_args):
        if raw_args[i] == "--profile" and i + 1 < len(raw_args):
            set_profile(raw_args[i + 1])
            i += 2
        elif raw_args[i] == "--json":
            as_json = True
            i += 1
        elif raw_args[i] == "--start-at" and i + 1 < len(raw_args):
            start_at = int(raw_args[i + 1])
            i += 2
        elif raw_args[i] in ("--limit", "--max-results") and i + 1 < len(raw_args):
            max_results = int(raw_args[i + 1])
            i += 2
        elif raw_args[i] == "--file" and i + 1 < len(raw_args):
            file_input = raw_args[i + 1]
            i += 2
        else:
            args.append(raw_args[i])
            i += 1

    if not args:
        cmd_help()
        return

    cmd = args[0]
    if cmd == "issue" and len(args) >= 2:
        cmd_issue(args[1], as_json=as_json)
    elif cmd == "search" and len(args) >= 2:
        cmd_search(args[1], start_at=start_at, max_results=max_results, as_json=as_json)
    elif cmd == "comments" and len(args) >= 2:
        cmd_comments(args[1], as_json=as_json)
    elif cmd == "create" and len(args) >= 3:
        desc = file_input or ""
        itype, parent = "Task", None
        j = 3
        while j < len(args):
            if args[j] == "--desc" and j + 1 < len(args):
                desc = args[j + 1]
                j += 2
            elif args[j] == "--type" and j + 1 < len(args):
                itype = args[j + 1]
                j += 2
            elif args[j] == "--parent" and j + 1 < len(args):
                parent = args[j + 1]
                j += 2
            else:
                j += 1
        cmd_create(args[1], args[2], desc=desc, issue_type=itype, parent=parent)
    elif cmd == "comment" and (len(args) >= 3 or file_input):
        text = file_input if file_input else args[2]
        cmd_comment(args[1], text)
    elif cmd == "comment-edit" and (len(args) >= 4 or file_input):
        text = file_input if file_input else args[3]
        cmd_comment_edit(args[1], args[2], text)
    elif cmd == "transition" and len(args) >= 3:
        cmd_transition(args[1], args[2])
    elif cmd == "assign" and len(args) >= 3:
        cmd_assign(args[1], args[2])
    elif cmd == "sprint" and len(args) >= 3:
        cmd_sprint(args[1], args[2])
    else:
        print(
            f"Unknown command or invalid arguments: {' '.join(args)}\nRun 'jira help'.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
