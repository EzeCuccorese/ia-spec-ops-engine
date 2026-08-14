"""
devscripts_common.frontmatter — Parser unificado de YAML frontmatter para reglas y especificaciones markdown.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Parsea frontmatter YAML simple delimitado por --- al inicio del contenido Markdown.
    Retorna (metadata_dict, markdown_body).
    """
    metadata: Dict[str, Any] = {}
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
                        except Exception:
                            metadata[k] = [s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()]
                    elif v.lower() in ("true", "yes"):
                        metadata[k] = True
                    elif v.lower() in ("false", "no"):
                        metadata[k] = False
                    else:
                        metadata[k] = v.strip("'\"")
    return metadata, body
