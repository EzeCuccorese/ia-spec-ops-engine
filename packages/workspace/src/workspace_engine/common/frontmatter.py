"""
workspace_engine.common.frontmatter — Unified YAML frontmatter parser for markdown rules and specs.
"""

from __future__ import annotations

import json
from typing import Any


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Parses simple YAML frontmatter delimited by --- at the start of Markdown content.
    Returns (metadata_dict, markdown_body).
    """
    metadata: dict[str, Any] = {}
    body = content.strip()
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        try:
                            metadata[k] = json.loads(v)
                        except json.JSONDecodeError:
                            metadata[k] = [
                                s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()
                            ]
                    elif v.lower() in ("true", "yes"):
                        metadata[k] = True
                    elif v.lower() in ("false", "no"):
                        metadata[k] = False
                    else:
                        metadata[k] = v.strip("'\"")
    return metadata, body
