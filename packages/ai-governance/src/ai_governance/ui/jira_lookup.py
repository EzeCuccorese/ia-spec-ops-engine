"""Read-only Jira issue lookup helper for linking Taskflow sessions to Jira tickets."""

from __future__ import annotations

import re
import urllib.parse

from ..tools import jira
from ..tools.atlassian_common import AtlassianError

_JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
_BROWSE_RE = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]+-\d+)")


def extract_jira_key(raw: str) -> str:
    """Extract and normalize a Jira issue key (e.g. ``PROJ-123``) from a key or Jira URL."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Provide a Jira issue key or URL")
    if "://" in cleaned:
        parsed = urllib.parse.urlparse(cleaned)
        qs = urllib.parse.parse_qs(parsed.query)
        selected = qs.get("selectedIssue")
        if selected and _JIRA_KEY_RE.match(selected[0].strip().upper()):
            return selected[0].strip().upper()
        if match := _BROWSE_RE.search(parsed.path):
            return match.group(1).upper()
        raise ValueError(f"Could not find a Jira issue key in URL: {cleaned!r}")
    candidate = cleaned.upper()
    if not _JIRA_KEY_RE.match(candidate):
        raise ValueError(f"Invalid Jira issue key {cleaned!r}; expected e.g. PROJ-123")
    return candidate


def _nested_name(fields: dict[str, object], key: str, subkey: str = "name") -> str:
    raw = fields.get(key)
    if isinstance(raw, dict):
        val = raw.get(subkey)
        return str(val).strip() if val else ""
    return ""


def fetch_jira_issue(raw: str) -> dict[str, str]:
    """Fetch read-only Jira issue metadata for pre-filling a Taskflow session."""
    key = extract_jira_key(raw)
    safe_key = urllib.parse.quote(key, safe="")
    data = jira.get(f"/issue/{safe_key}?fields=summary,status,issuetype,priority,parent")
    if not isinstance(data, dict):
        raise AtlassianError(f"Unexpected Jira response for {key}")
    fields = data.get("fields")
    fields_dict = fields if isinstance(fields, dict) else {}
    base_url = jira._get_base_url().rstrip("/")
    return {
        "key": key,
        "title": str(fields_dict.get("summary") or "").strip(),
        "status": _nested_name(fields_dict, "status"),
        "issue_type": _nested_name(fields_dict, "issuetype"),
        "priority": _nested_name(fields_dict, "priority"),
        "parent": _nested_name(fields_dict, "parent", "key"),
        "url": f"{base_url}/browse/{key}" if base_url else "",
    }
