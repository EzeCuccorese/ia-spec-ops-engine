"""Markdown to Atlassian Document Format (ADF), shared by the Jira and Confluence tools.

Jira Cloud only accepts ADF, and Confluence takes it too. The conversion lives in one place so
the rest of the code never depends on the third-party converter directly.
"""

from __future__ import annotations

from typing import Any

import marklas


def md_to_adf(text: str) -> dict[str, Any]:
    """Converts GitHub-flavoured Markdown (headings, task lists, tables, code...) to an ADF doc."""
    return marklas.to_adf(text)
