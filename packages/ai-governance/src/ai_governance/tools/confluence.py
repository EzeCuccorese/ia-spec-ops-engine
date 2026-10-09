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

import argparse
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
from ai_governance.tools.md_adf import md_to_adf

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


# Lines that start like this are raw Confluence storage XML/HTML and go through untouched.
_RAW_STORAGE_PREFIXES = (
    "<ac:",
    "</ac:",
    "<table",
    "</table",
    "<tr",
    "</tr",
    "<td",
    "</td",
    "<th",
    "</th",
    "<p>",
    "</p>",
)


def _adf_to_storage(adf: dict[str, Any]) -> str:
    """Asks Confluence itself to turn an ADF doc into storage format (synchronous, no write)."""
    data = post(
        "/contentbody/convert/storage",
        {"value": json.dumps(adf), "representation": "atlas_doc_format"},
    )
    return str(data.get("value", ""))


def md_to_storage(md: str) -> str:
    """Converts Markdown to Confluence storage format, keeping raw storage XML lines as they are."""
    parts: list[str] = []
    chunk: list[str] = []

    def flush() -> None:
        text = "\n".join(chunk).strip()
        if text:
            parts.append(_adf_to_storage(md_to_adf(text)))
        chunk.clear()

    for line in md.split("\n"):
        if line.strip().startswith(_RAW_STORAGE_PREFIXES):
            flush()
            parts.append(line)
        else:
            chunk.append(line)
    flush()
    return "".join(parts)


def _shift_task_ids(new_body: str, existing_body: str) -> str:
    """Numbers the appended tasks after the ones already on the page so ids stay unique."""
    pattern = re.compile(r"<ac:task-id>(\d+)</ac:task-id>")
    offset = max((int(i) for i in pattern.findall(existing_body)), default=0)
    if not offset:
        return new_body
    return pattern.sub(lambda m: f"<ac:task-id>{int(m.group(1)) + offset}</ac:task-id>", new_body)


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
    new_content = _shift_task_ids(md_to_storage(append_text), old_body)
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


PAGE = ("page_id", {"help": "Page id"})
# name -> (help, positionals). Every subcommand also takes the common flags below.
COMMANDS: dict[str, tuple[str, tuple[tuple[str, dict[str, Any]], ...]]] = {
    "read": ("Display a page in Markdown or JSON", (PAGE,)),
    "search": ("Search pages across all spaces", (("query", {"help": "Search text"}),)),
    "spaces": ("List the available spaces", ()),
    "create": (
        "Create a page (body: Markdown text, @file or -)",
        (
            ("space", {"help": "Space key"}),
            ("title", {"help": "Page title"}),
            ("body", {"nargs": "?", "help": "Page body"}),
        ),
    ),
    "update": (
        "Replace the whole page body",
        (PAGE, ("body", {"nargs": "?", "help": "New page body"})),
    ),
    "append": (
        "Append text to the bottom of a page",
        (PAGE, ("body", {"nargs": "?", "help": "Text to append"})),
    ),
    "comment": ("Add a comment to a page", (PAGE, ("body", {"nargs": "?", "help": "Comment"}))),
}


def _common_flags(parser: argparse.ArgumentParser, *, root: bool) -> None:
    """Flags accepted before and after the subcommand (`confluence --json read 1` and
    `confluence read 1 --json`). Subcommands leave them unset so the root value survives."""
    unset: dict[str, Any] = {} if root else {"default": argparse.SUPPRESS}
    parser.add_argument("--profile", help="Use a named configuration profile", **unset)
    parser.add_argument("--json", action="store_true", help="Print the raw JSON", **unset)
    parser.add_argument("--file", help="Read the body from this file", **unset)


def _paging_flags(parser: argparse.ArgumentParser, *, root: bool) -> None:
    start: Any = 0 if root else argparse.SUPPRESS
    limit: Any = 15 if root else argparse.SUPPRESS
    parser.add_argument("--start", type=int, default=start, help="First result (paging)")
    parser.add_argument("--limit", type=int, default=limit, help="Page size")


def _version_flag(parser: argparse.ArgumentParser, *, root: bool) -> None:
    parser.add_argument(
        "--version",
        "--ver",
        dest="version",
        type=int,
        default=None if root else argparse.SUPPRESS,
        help="Expected current version (guards against conflicts)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence", add_help=False)
    parser.add_argument(
        "-h", "--help", action="store_true", dest="show_help", help="Show the command overview"
    )
    _common_flags(parser, root=True)
    _paging_flags(parser, root=True)
    _version_flag(parser, root=True)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("help", help="Show the command overview")
    for name, (help_text, positionals) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        for dest, options in positionals:
            command.add_argument(dest, **options)
        _common_flags(command, root=False)
    _paging_flags(sub.choices["search"], root=False)
    sub.choices["search"].add_argument("--space", help="Limit the search to one space key")
    sub.choices["create"].add_argument("--parent", help="Parent page id")
    for name in ("update", "append"):
        _version_flag(sub.choices[name], root=False)
    return parser


def _body(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    body = args.file or args.body
    if not body:
        parser.error(f"{args.command} needs a body or --file")
    return str(body)


HANDLERS: dict[str, Any] = {
    "read": lambda a, _p: cmd_read(a.page_id, as_json=a.json),
    "search": lambda a, _p: cmd_search(
        a.query, space_key=a.space, start=a.start, limit=a.limit, as_json=a.json
    ),
    "spaces": lambda a, _p: cmd_spaces(as_json=a.json),
    "create": lambda a, p: cmd_create(a.space, a.title, _body(a, p), parent_id=a.parent),
    "update": lambda a, p: cmd_update(a.page_id, _body(a, p), expected_version=a.version),
    "append": lambda a, p: cmd_append(a.page_id, _body(a, p), expected_version=a.version),
    "comment": lambda a, p: cmd_comment(a.page_id, _body(a, p)),
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
