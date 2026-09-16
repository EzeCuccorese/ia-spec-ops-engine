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

from __future__ import annotations

import html
import json
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ── Configuration & Profiles (Shared with Atlassian Common) ─────────────────
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

_auth_header = auth_header
_get_base_url = get_base_url


def _get_api_url() -> str:
    return f"{_get_base_url()}/wiki/rest/api"


def _request(method: str, url: str, payload: dict[str, Any] | list[Any] | None = None) -> Any:
    return execute_request(method, url, payload=payload, timeout=ATLASSIAN_TIMEOUT)


def get(path: str) -> Any:
    return _request("GET", f"{_get_api_url()}{path}")


def post(path: str, payload: dict[str, Any]) -> Any:
    return _request("POST", f"{_get_api_url()}{path}", payload)


def put(path: str, payload: dict[str, Any]) -> Any:
    return _request("PUT", f"{_get_api_url()}{path}", payload)


def html_to_md(html_str: str) -> str:
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

    def convert_table(match: re.Match[str]) -> str:
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

    text = re.sub(
        r"<ac:rich-text-body>(.*?)</ac:rich-text-body>",
        r"\1",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<ac:[^>]*>.*?</ac:[^>]*>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _md_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def md_to_storage(md: str) -> str:
    """Converts basic Markdown to Confluence storage format (XHTML), preserving raw XML macros/tables."""
    blocks = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if (
            stripped.startswith("<ac:")
            or stripped.startswith("</ac:")
            or stripped.startswith("<table")
            or stripped.startswith("</table")
            or stripped.startswith("<tr")
            or stripped.startswith("</tr")
            or stripped.startswith("<td")
            or stripped.startswith("</td")
            or stripped.startswith("<th")
            or stripped.startswith("</th")
            or stripped.startswith("<p>")
            or stripped.startswith("</p>")
        ):
            blocks.append(line)
            i += 1
            continue

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


def cmd_read(page_id: str, as_json: bool = False) -> None:
    """Displays page in clean Markdown or JSON."""
    data = get(f"/content/{page_id}?expand=body.storage,version,space")
    if as_json:
        print(json.dumps(data, indent=2))
        return

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


def escape_cql_literal(text: str) -> str:
    """Safely escape backslashes and double quotes for CQL literal strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def cmd_search(
    query: str,
    space_key: str | None = None,
    start: int = 0,
    limit: int = 15,
    as_json: bool = False,
) -> None:
    """Searches pages by text query with pagination support."""
    safe_query = escape_cql_literal(query)
    cql = f'text ~ "{safe_query}" AND type = page'
    if space_key:
        safe_space = escape_cql_literal(space_key)
        cql += f' AND space = "{safe_space}"'
    data = get(
        f"/content/search?cql={urllib.parse.quote(cql)}&start={start}&limit={limit}&expand=space,version"
    )
    if as_json:
        print(json.dumps(data, indent=2))
        return

    results = data.get("results", [])
    total = data.get("totalSize", len(results))

    if not results:
        print("_No results found._")
        return

    print(f'## Results for "{query}" ({start + 1}-{start + len(results)} of {total})\n')
    print("| ID | Space | Title |")
    print("|---|---|---|")
    for r in results:
        space = r.get("space", {}).get("key", "—")
        print(f"| {r['id']} | {space} | {r.get('title', '')} |")

    if total > start + len(results):
        print(
            f"\n_More results exist ({start + len(results)} of {total} shown). Use --start {start + len(results)} to view next page._"
        )


def cmd_spaces(as_json: bool = False) -> None:
    """Lists available spaces."""
    data = get("/space?limit=50&type=global&status=current")
    if as_json:
        print(json.dumps(data, indent=2))
        return

    results = data.get("results", [])
    if not results:
        print("_No spaces found._")
        return

    print(f"## Available Spaces ({len(results)})\n")
    print("| Key | Name |")
    print("|---|---|")
    for s in sorted(results, key=lambda x: x.get("name", "")):
        print(f"| {s.get('key', '')} | {s.get('name', '')} |")


def cmd_create(space_key: str, title: str, body_md: str, parent_id: str | None = None) -> None:
    """Creates a new page in Confluence."""
    content_text = read_input_text(body_md)
    payload: dict[str, Any] = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": md_to_storage(content_text), "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": str(parent_id)}]

    data = post("/content", payload)
    pid = data.get("id", "")
    print(f"✅ Page created: **{title}** (id: {pid})")
    print(f"   {_get_base_url()}/wiki/spaces/{space_key}/pages/{pid}")


def cmd_update(page_id: str, body_md: str, expected_version: int | None = None) -> None:
    """Updates page body with version conflict checking."""
    current = get(f"/content/{page_id}?expand=version,space")
    title = current.get("title", "")
    space = current.get("space", {}).get("key", "")
    ver = current.get("version", {}).get("number", 1)

    if expected_version is not None and int(expected_version) != ver:
        print(
            f"❌ Version conflict: page {page_id} is at version {ver}, expected {expected_version}.",
            file=sys.stderr,
        )
        sys.exit(1)

    content_text = read_input_text(body_md)
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": md_to_storage(content_text), "representation": "storage"}},
        "version": {"number": ver + 1},
    }
    put(f"/content/{page_id}", payload)
    print(f"✅ Page updated: **{title}** (v{ver + 1})")


def cmd_append(page_id: str, text: str, expected_version: int | None = None) -> None:
    """Appends content to the end of a page with version conflict checking."""
    current = get(f"/content/{page_id}?expand=body.storage,version,space")
    title = current.get("title", "")
    space = current.get("space", {}).get("key", "")
    ver = current.get("version", {}).get("number", 1)

    if expected_version is not None and int(expected_version) != ver:
        print(
            f"❌ Version conflict: page {page_id} is at version {ver}, expected {expected_version}.",
            file=sys.stderr,
        )
        sys.exit(1)

    old_body = current.get("body", {}).get("storage", {}).get("value", "")
    append_text = read_input_text(text)
    new_content = md_to_storage(append_text)
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


def cmd_comment(page_id: str, text: str) -> None:
    """Adds comment to a page."""
    comment_text = read_input_text(text)
    payload = {
        "type": "comment",
        "container": {"id": str(page_id), "type": "page"},
        "body": {"storage": {"value": md_to_storage(comment_text), "representation": "storage"}},
    }
    post("/content", payload)
    print(f"✅ Comment added to page {page_id}")


def cmd_help() -> None:
    print(
        textwrap.dedent("""
        confluence — Lightweight CLI for Confluence REST API v1
        ========================================================

        READ:
          confluence read <PAGE-ID> [--json]          Display page in clean Markdown or JSON
          confluence search "<query>" [--start <N>]   Search pages across all spaces
            [--limit <N>] [--space <KEY>] [--json]
          confluence spaces [--json]                  List all available spaces

        WRITE:
          confluence create <SPACE> "<Title>" "<body>|@file|-" Create a new page
            [--parent <PAGE-ID>]                      (optional) Parent page
          confluence update <PAGE-ID> "<body>|@file|-" Update entire page body
            [--version <EXPECTED-VER>]                Guard against version conflicts
          confluence append <PAGE-ID> "<text>|@file|-" Append text to bottom of page
            [--version <EXPECTED-VER>]
          confluence comment <PAGE-ID> "<text>|@file|-" Add comment to page

        GLOBAL OPTIONS:
          --profile <NAME>                            Use named configuration profile
    """).strip()
    )


def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else list(argv)
    if not raw_args or raw_args[0] in ("-h", "--help", "help"):
        cmd_help()
        return

    # Extract global flags
    args = []
    i = 0
    as_json = False
    start = 0
    limit = 15
    version_arg = None
    file_input = None

    while i < len(raw_args):
        if raw_args[i] == "--profile" and i + 1 < len(raw_args):
            set_profile(raw_args[i + 1])
            i += 2
        elif raw_args[i] == "--json":
            as_json = True
            i += 1
        elif raw_args[i] == "--start" and i + 1 < len(raw_args):
            start = int(raw_args[i + 1])
            i += 2
        elif raw_args[i] == "--limit" and i + 1 < len(raw_args):
            limit = int(raw_args[i + 1])
            i += 2
        elif raw_args[i] in ("--version", "--ver") and i + 1 < len(raw_args):
            version_arg = int(raw_args[i + 1])
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
    if cmd == "read" and len(args) >= 2:
        cmd_read(args[1], as_json=as_json)
    elif cmd == "search" and len(args) >= 2:
        space = None
        if "--space" in args:
            idx = args.index("--space")
            if idx + 1 < len(args):
                space = args[idx + 1]
        cmd_search(args[1], space_key=space, start=start, limit=limit, as_json=as_json)
    elif cmd == "spaces":
        cmd_spaces(as_json=as_json)
    elif cmd == "create" and (len(args) >= 4 or (len(args) >= 3 and file_input)):
        parent = None
        if "--parent" in args:
            idx = args.index("--parent")
            if idx + 1 < len(args):
                parent = args[idx + 1]
        body = file_input if file_input else args[3]
        cmd_create(args[1], args[2], body, parent_id=parent)
    elif cmd == "update" and (len(args) >= 3 or (len(args) >= 2 and file_input)):
        body = file_input if file_input else args[2]
        cmd_update(args[1], body, expected_version=version_arg)
    elif cmd == "append" and (len(args) >= 3 or (len(args) >= 2 and file_input)):
        body = file_input if file_input else args[2]
        cmd_append(args[1], body, expected_version=version_arg)
    elif cmd == "comment" and (len(args) >= 3 or (len(args) >= 2 and file_input)):
        body = file_input if file_input else args[2]
        cmd_comment(args[1], body)
    else:
        print(
            f"Unknown command or invalid arguments: {' '.join(args)}\nRun 'confluence help'.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
