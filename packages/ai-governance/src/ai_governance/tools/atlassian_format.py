"""Format conversion between Markdown, Atlassian Document Format (ADF), and Confluence XHTML storage."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

_CODE_MACRO = re.compile(
    r'<ac:structured-macro[^>]*ac:name=["\']code["\'][^>]*>.*?</ac:structured-macro>',
    flags=re.DOTALL | re.IGNORECASE,
)
_CODE_LANG = re.compile(
    r'<ac:parameter ac:name=["\']language["\']>([^<]*)</ac:parameter>', re.IGNORECASE
)
_CODE_BODY = re.compile(
    r"<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body>", flags=re.DOTALL
)

_MARKS: dict[str, tuple[str, str]] = {
    "strong": ("**", "**"),
    "em": ("*", "*"),
    "code": ("`", "`"),
    "strike": ("~~", "~~"),
}


def _apply_marks(text: str, marks: list[dict[str, Any]]) -> str:
    for mark in marks:
        mtype = mark.get("type", "")
        if mtype in _MARKS:
            prefix, suffix = _MARKS[mtype]
            text = f"{prefix}{text}{suffix}"
        elif mtype == "link":
            href = mark.get("attrs", {}).get("href", "")
            text = f"[{text}]({href})"
    return text


def _adf_table_to_md(content: list[dict[str, Any]]) -> str:
    rows = []
    for row in content:
        cells = [adf_to_md(cell).strip().replace("\n", " ") for cell in row.get("content", [])]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) > 1:
        n_cols = len(content[0].get("content", []))
        sep = "| " + " | ".join(["---"] * n_cols) + " |"
        rows.insert(1, sep)
    return "\n".join(rows) + "\n\n"


def _adf_list_to_md(content: list[dict[str, Any]], *, ordered: bool = False) -> str:
    if ordered:
        lines = [f"{i + 1}. {adf_to_md(item).strip()}\n" for i, item in enumerate(content)]
    else:
        lines = [f"- {adf_to_md(item).strip()}\n" for item in content]
    return "".join(lines) + "\n"


def _format_task_item(node: dict[str, Any], inner: str) -> str:
    done = node.get("attrs", {}).get("state") == "DONE"
    return f"[{'x' if done else ' '}] {inner.strip()}"


_ADF_CONTAINERS: dict[str, Callable[[dict[str, Any], str], str]] = {
    "paragraph": lambda _n, inner: f"{inner}\n\n",
    "heading": lambda n, inner: f"{'#' * n.get('attrs', {}).get('level', 2)} {inner}\n\n",
    "listItem": lambda _n, inner: inner.strip(),
    "taskItem": _format_task_item,
    "codeBlock": lambda n, inner: (
        f"```{n.get('attrs', {}).get('language', '')}\n{inner.rstrip()}\n```\n\n"
    ),
    "blockquote": lambda _n, inner: f"> {inner.strip()}\n\n",
    "rule": lambda _n, _inner: "---\n\n",
}


def adf_to_md(node: Any) -> str:
    """Converts Atlassian Document Format (ADF) to clean Markdown."""
    if not node or not isinstance(node, dict):
        return ""
    ntype = node.get("type", "")
    content = node.get("content", [])

    if ntype == "text":
        return _apply_marks(node.get("text", ""), node.get("marks", []))
    if ntype in ("bulletList", "taskList"):
        return _adf_list_to_md(content, ordered=False)
    if ntype == "orderedList":
        return _adf_list_to_md(content, ordered=True)
    if ntype == "table":
        return _adf_table_to_md(content)

    inner = "".join(adf_to_md(c) for c in content)
    formatter = _ADF_CONTAINERS.get(ntype)
    return formatter(node, inner) if formatter else inner


def _flatten_item(fragment: str) -> str:
    """Drops the <p> wrappers Confluence puts inside list items and quotes (one line out)."""
    fragment = re.sub(r"</?p[^>]*>", " ", fragment, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", fragment).strip()


def _convert_ordered_list(match: re.Match[str]) -> str:
    items = re.findall(r"<li[^>]*>(.*?)</li>", match.group(0), flags=re.DOTALL | re.IGNORECASE)
    return "\n" + "\n".join(f"{n}. {_flatten_item(i)}" for n, i in enumerate(items, 1)) + "\n"


def _convert_table(match: re.Match[str]) -> str:
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


_INLINE_HTML_SUBS: tuple[tuple[str, str], ...] = (
    (r"<pre[^>]*><code[^>]*>(.*?)</code></pre>", r"\n```\n\1\n```\n"),
    (r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n"),
    (r"<code[^>]*>(.*?)</code>", r"`\1`"),
    (r"<strong[^>]*>(.*?)</strong>", r"**\1**"),
    (r"<b[^>]*>(.*?)</b>", r"**\1**"),
    (r"<em[^>]*>(.*?)</em>", r"*\1*"),
    (r"<i[^>]*>(.*?)</i>", r"*\1*"),
    (r"<s[^>]*>(.*?)</s>", r"~~\1~~"),
    (r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r"[\2](\1)"),
)

_BLOCK_HTML_SUBS: tuple[tuple[str, Any, int], ...] = (
    (r"<ol[^>]*>.*?</ol>", _convert_ordered_list, re.DOTALL | re.IGNORECASE),
    (
        r"<li[^>]*>(.*?)</li>",
        lambda m: f"- {_flatten_item(m.group(1))}\n",
        re.DOTALL | re.IGNORECASE,
    ),
    (r"</?[uo]l[^>]*>", "\n", re.IGNORECASE),
    (r"<table[^>]*>.*?</table>", _convert_table, re.DOTALL | re.IGNORECASE),
    (
        r"<blockquote[^>]*>(.*?)</blockquote>",
        lambda m: f"\n> {_flatten_item(m.group(1))}\n",
        re.DOTALL | re.IGNORECASE,
    ),
    (r"<p[^>]*>(.*?)</p>", r"\n\1\n", re.DOTALL | re.IGNORECASE),
    (r"<br\s*/?>", "\n", re.IGNORECASE),
    (r"<hr\s*/?>", "\n---\n", re.IGNORECASE),
    (r"<ac:rich-text-body>(.*?)</ac:rich-text-body>", r"\1", re.DOTALL | re.IGNORECASE),
    (r"<ac:[^>]*>.*?</ac:[^>]*>", "", re.DOTALL),
    (r"<[^>]+>", "", 0),
)


def _park_code_macros(text: str) -> tuple[str, list[str]]:
    code_blocks: list[str] = []

    def park(match: re.Match[str]) -> str:
        lang = _CODE_LANG.search(match.group(0))
        body = _CODE_BODY.search(match.group(0))
        fence = f"```{lang.group(1) if lang else ''}\n{body.group(1) if body else ''}\n```"
        code_blocks.append(fence)
        return f"\n\x00CODE{len(code_blocks) - 1}\x00\n"

    return _CODE_MACRO.sub(park, text), code_blocks


def html_to_md(html_str: str) -> str:
    """Converts Confluence storage format (XHTML) to clean Markdown."""
    if not html_str:
        return ""
    text, code_blocks = _park_code_macros(html_str)
    for level in range(6, 0, -1):
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            rf"\n{'#' * level} \1\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    for pattern, repl in _INLINE_HTML_SUBS:
        text = re.sub(pattern, repl, text, flags=re.DOTALL | re.IGNORECASE)
    for pattern, repl, flags in _BLOCK_HTML_SUBS:
        text = re.sub(pattern, repl, text, flags=flags)
    text = html.unescape(text)
    text = re.sub(r"\x00CODE(\d+)\x00", lambda m: code_blocks[int(m.group(1))], text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
