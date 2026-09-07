#!/usr/bin/env python3
"""
confluence — Lightweight CLI for Confluence REST API v1
========================================================

Reads and writes to Confluence via REST API v1, returning clean Markdown.
Ideal for Antigravity, Claude Code, and terminal agents with zero token overhead.

Requirements (environment variables in ~/.zshrc):
    ATLASSIAN_EMAIL      your-email@company.com
    ATLASSIAN_API_TOKEN  token generated at id.atlassian.com
    ATLASSIAN_URL        https://company.atlassian.net

Usage:
    confluence read <PAGE-ID>                         Display page in clean Markdown
    confluence search "<query>" [--space <KEY>]       Search pages
    confluence spaces                                 List available spaces
    confluence create <SPACE-KEY> "<Title>" "<body>"  Create a new page
      --parent <PAGE-ID>                              (optional) Parent page ID
    confluence update <PAGE-ID> "<new body>"          Update entire page body
    confluence append <PAGE-ID> "<text>"              Append paragraph to existing page
    confluence comment <PAGE-ID> "<text>"             Add inline/footer comment to page
    confluence help                                   Display this help message
"""

import base64
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────────────

EMAIL = os.environ.get("ATLASSIAN_EMAIL", "")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN", "")
BASE_URL = os.environ.get("ATLASSIAN_URL", "").rstrip("/")


def _get_base_url():
    return os.environ.get("ATLASSIAN_URL", BASE_URL).rstrip("/")


def _get_api_url():
    return f"{_get_base_url()}/wiki/rest/api"


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


def _request(method, url, payload=None):
    check_env()
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=_auth_header(), method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            msg = json.loads(err)
            err = json.dumps(msg, indent=2)
        except Exception:
            pass
        print(f"HTTP {e.code} Error calling {method} {url}:\n{err}", file=sys.stderr)
        sys.exit(1)


def get(path):
    return _request("GET", f"{_get_api_url()}{path}")


def post(path, payload):
    return _request("POST", f"{_get_api_url()}{path}", payload)


def put(path, payload):
    return _request("PUT", f"{_get_api_url()}{path}", payload)


def html_to_md(html_str):
    """Converts Confluence storage format (XHTML) to clean Markdown."""
    if not html_str:
        return ""
    text = html_str

    for level in range(6, 0, -1):
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            rf"\n{'#' * level} \1\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    text = re.sub(
        r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
        r"\n```\n\1\n```\n",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<s[^>]*>(.*?)</s>", r"~~\1~~", text, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(
        r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?[uo]l[^>]*>", "\n", text, flags=re.IGNORECASE)

    def convert_table(match):
        table_html = match.group(0)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
        if not rows:
            return ""
        md_rows = []
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.DOTALL | re.IGNORECASE)
            clean_cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            md_rows.append("| " + " | ".join(clean_cells) + " |")
        if len(md_rows) > 1:
            first_cells = re.findall(
                r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.DOTALL | re.IGNORECASE
            )
            sep = "| " + " | ".join(["---"] * len(first_cells)) + " |"
            md_rows.insert(1, sep)
        return "\n" + "\n".join(md_rows) + "\n"

    text = re.sub(r"<table[^>]*>.*?</table>", convert_table, text, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(
        r"<blockquote[^>]*>(.*?)</blockquote>", r"\n> \1\n", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)

    text = re.sub(r"<ac:[^>]*>.*?</ac:[^>]*>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _md_inline(text):
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def md_to_storage(md):
    """Converts basic Markdown to Confluence storage format (XHTML)."""
    blocks = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_text = html.escape("\n".join(code_lines))
            blocks.append(f"<pre><code>{code_text}</code></pre>")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            lvl = len(m.group(1))
            blocks.append(f"<h{lvl}>{_md_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if line.startswith("- ") or line.startswith("* "):
            items = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("* ")):
                items.append(f"<li>{_md_inline(lines[i][2:].strip())}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue

        if line.strip() == "---":
            blocks.append("<hr/>")
            i += 1
            continue

        if line.strip():
            blocks.append(f"<p>{_md_inline(line.strip())}</p>")

        i += 1

    return "".join(blocks)


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_read(page_id):
    """Displays page in clean Markdown."""
    data = get(f"/content/{page_id}?expand=body.storage,version,space")
    title = data.get("title", "")
    space = data.get("space", {}).get("name", "")
    ver = data.get("version", {}).get("number", 1)
    body_html = data.get("body", {}).get("storage", {}).get("value", "")
    md = html_to_md(body_html)

    print(f"# {title}\n")
    print(f"**Space**: {space}  |  **Version**: {ver}  |  **ID**: {page_id}")
    print(
        f"**URL**: {_get_base_url()}/wiki/spaces/{data.get('space', {}).get('key', '')}/pages/{page_id}\n"
    )
    print("---\n")
    print(md)


def cmd_search(query, space_key=None):
    """Searches pages by text query."""
    cql = f'text ~ "{query}" AND type = page'
    if space_key:
        cql += f' AND space = "{space_key}"'
    data = get(f"/content/search?cql={urllib.parse.quote(cql)}&limit=15&expand=space,version")
    results = data.get("results", [])
    total = data.get("totalSize", len(results))

    if not results:
        print("_No results found._")
        return

    print(f'## Results for "{query}" ({len(results)} of {total})\n')
    print("| ID | Space | Title |")
    print("|---|---|---|")
    for r in results:
        space = r.get("space", {}).get("key", "—")
        print(f"| {r['id']} | {space} | {r.get('title', '')} |")


def cmd_spaces():
    """Lists available spaces."""
    data = get("/space?limit=50&type=global&status=current")
    results = data.get("results", [])

    if not results:
        print("_No spaces found._")
        return

    print(f"## Available Spaces ({len(results)})\n")
    print("| Key | Name |")
    print("|---|---|")
    for s in sorted(results, key=lambda x: x.get("name", "")):
        print(f"| {s.get('key', '')} | {s.get('name', '')} |")


def cmd_create(space_key, title, body_md, parent_id=None):
    """Creates a new page in Confluence."""
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": md_to_storage(body_md), "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": str(parent_id)}]

    data = post("/content", payload)
    pid = data.get("id", "")
    print(f"✅ Page created: **{title}** (id: {pid})")
    print(f"   {_get_base_url()}/wiki/spaces/{space_key}/pages/{pid}")


def cmd_update(page_id, body_md):
    """Updates page body (increments version)."""
    current = get(f"/content/{page_id}?expand=version,space")
    title = current.get("title", "")
    space = current.get("space", {}).get("key", "")
    ver = current.get("version", {}).get("number", 1)

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": md_to_storage(body_md), "representation": "storage"}},
        "version": {"number": ver + 1},
    }
    put(f"/content/{page_id}", payload)
    print(f"✅ Page updated: **{title}** (v{ver + 1})")


def cmd_append(page_id, text):
    """Appends content to the end of a page."""
    current = get(f"/content/{page_id}?expand=body.storage,version,space")
    title = current.get("title", "")
    space = current.get("space", {}).get("key", "")
    ver = current.get("version", {}).get("number", 1)
    old_body = current.get("body", {}).get("storage", {}).get("value", "")

    new_content = md_to_storage(text)
    combined = old_body + new_content

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": combined, "representation": "storage"}},
        "version": {"number": ver + 1},
    }
    put(f"/content/{page_id}", payload)
    print(f"✅ Content appended to **{title}** (v{ver + 1})")


def cmd_comment(page_id, text):
    """Adds comment to a page."""
    payload = {
        "type": "comment",
        "container": {"id": str(page_id), "type": "page"},
        "body": {"storage": {"value": md_to_storage(text), "representation": "storage"}},
    }
    post("/content", payload)
    print(f"✅ Comment added to page {page_id}")


def cmd_help():
    print(
        textwrap.dedent("""
        confluence — Lightweight CLI for Confluence REST API v1
        ========================================================

        READ:
          confluence read <PAGE-ID>                   Display page in clean Markdown
          confluence search "<query>"                 Search pages across all spaces
          confluence search "<query>" --space <KEY>   Search pages within space
          confluence spaces                           List all available spaces

        WRITE:
          confluence create <SPACE> "<Title>" "<body>" Create a new page
            [--parent <PAGE-ID>]                      (optional) Parent page
          confluence update <PAGE-ID> "<new body>"    Update entire page body
          confluence append <PAGE-ID> "<text>"        Append text to bottom of page
          confluence comment <PAGE-ID> "<text>"       Add comment to page

        EXAMPLES:
          confluence read 1548025858
          confluence search "design system" --space DS
          confluence create DS "Architecture Decisions" "## ADR-001\n\nDecision details."
          confluence append 1548025858 "Additional notes added from CLI"
          confluence comment 1548025858 "Approved ✅"
    """).strip()
    )


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        cmd_help()
        return

    cmd = args[0]
    if cmd == "read" and len(args) >= 2:
        cmd_read(args[1])
    elif cmd == "search" and len(args) >= 2:
        space = None
        if "--space" in args:
            idx = args.index("--space")
            if idx + 1 < len(args):
                space = args[idx + 1]
        cmd_search(args[1], space_key=space)
    elif cmd == "spaces":
        cmd_spaces()
    elif cmd == "create" and len(args) >= 4:
        parent = None
        if "--parent" in args:
            idx = args.index("--parent")
            if idx + 1 < len(args):
                parent = args[idx + 1]
        cmd_create(args[1], args[2], args[3], parent_id=parent)
    elif cmd == "update" and len(args) >= 3:
        cmd_update(args[1], args[2])
    elif cmd == "append" and len(args) >= 3:
        cmd_append(args[1], args[2])
    elif cmd == "comment" and len(args) >= 3:
        cmd_comment(args[1], args[2])
    else:
        print(f"Unknown command or invalid arguments: {' '.join(args)}\nRun 'confluence help'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
