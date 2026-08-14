"""
devscripts.sdd.parser — Raw input parser and specification generator for SDD.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Optional, Union
import urllib.request


def parse(input_raw: str, output_file: Optional[Union[str, Path]] = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_type = "Direct Text"
    origin = input_raw
    title = "Specification Request"
    body = ""

    if re.match(r"^https?://github\.com/([^/]+)/([^/]+)/(issues|pull)/([0-9]+)", input_raw):
        source_type = "GitHub Issue/PR"
        m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/(issues|pull)/([0-9]+)", input_raw)
        if m:
            owner, repo, kind, number = m.groups()
            title = f"GitHub {kind} #{number}: {owner}/{repo}"
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{owner}/{repo}/issues/{number}",
                    headers={"User-Agent": "sdd-parser"},
                )
                with urllib.request.urlopen(req) as response:
                    d = json.loads(response.read())
                    title = d.get("title", title)
                    body = d.get("body", "")
            except (OSError, ValueError):
                body = f"Fetched reference from URL: {origin} (Details could not be retrieved automatically)."
    elif re.match(r"^https?://[^/]+/browse/([A-Z0-9]+-[0-9]+)", input_raw) or re.match(
        r"^https?://[^/]+/jira/.*([A-Z0-9]+-[0-9]+)", input_raw
    ):
        source_type = "Jira Ticket"
        m = re.search(r"([A-Z0-9]+-[0-9]+)", input_raw)
        jira_key = m.group(1) if m else "UNKNOWN"
        title = f"Jira Issue: {jira_key}"
        body = f"Referenced Jira Ticket: [{jira_key}]({origin})"
    elif os.path.isfile(input_raw):
        source_type = "Local File"
        origin = os.path.abspath(input_raw)
        with open(input_raw, encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        if lines and re.match(r"^#+\s+(.+)", lines[0]):
            match = re.match(r"^#+\s+(.+)", lines[0])
            title = match.group(1) if match else f"Specification from {os.path.basename(input_raw)}"
            body = "\n".join(lines[1:])
        else:
            title = f"Specification from {os.path.basename(input_raw)}"
            body = content
    else:
        lines = input_raw.splitlines()
        if lines:
            first = re.sub(r"^[#\s]*", "", lines[0])
            if first:
                title = first
        body = input_raw

    if not body.strip():
        body = title

    spec = f"""# Specification: {title}

- **Source Type:** {source_type}
- **Origin:** {origin}
- **Parsed Date:** {ts}

## 1. Overview & Objective
{title}

## 2. Requirements & Context
{body}

## 3. Acceptance Criteria (SDD Verified)
- [ ] Requirements defined in formal specification are implemented.
- [ ] Unit & integration tests created and passing.
- [ ] No regression introduced to existing components.
- [ ] Code quality, linter rules, and guidelines satisfied.

## 4. Execution Plan
1. **Spec Review**: Confirm alignment with architectural rules.
2. **Implementation**: Execute changes in an isolated Git Worktree.
3. **Audit**: Validate tests, diff, and memory updates.
"""

    if output_file:
        out_path = Path(output_file).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(spec)
        print(f"Parsed specification saved to: {out_path}")
    else:
        print(spec)

    return spec
