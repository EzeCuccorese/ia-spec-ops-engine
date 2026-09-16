"""
output_trimmer.py — Trims excessively large homogenous listings and massive JSON structures.
Never modifies git diff, format-patch, or git show outputs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

SKIP_COMMAND_RE = re.compile(r"\bgit\s+(diff|show|format-patch)\b", re.IGNORECASE)


class OutputTrimmer:
    @staticmethod
    def should_skip(cmd: str) -> bool:
        return bool(SKIP_COMMAND_RE.search(cmd))

    @staticmethod
    def is_homogeneous(lines: list[str], pct: float = 0.7) -> bool:
        prefixes = [line.strip()[:3] for line in lines if line.strip()]
        if not prefixes:
            return False
        _, top = Counter(prefixes).most_common(1)[0]
        return (top / len(prefixes)) >= pct

    @staticmethod
    def parse_large_json(text: str, threshold: int = 50) -> tuple[Any, int] | None:
        text = text.strip()
        if not text or text[0] not in "[{":
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None

        if isinstance(parsed, list) and len(parsed) > threshold:
            return parsed, len(parsed)
        if isinstance(parsed, dict) and len(parsed) > threshold:
            return parsed, len(parsed)
        return None

    @staticmethod
    def skeleton_json(parsed: Any, n: int, reference: str = "") -> str:
        if isinstance(parsed, list):
            sample = parsed[0]
            if isinstance(sample, dict):
                keys = ", ".join(sorted(sample.keys()))
                first_key = sorted(sample.keys())[0] if sample else ""
                suggestion = f"jq -r '.[].{first_key}' <file>"
            else:
                keys = type(sample).__name__
                suggestion = "jq -r '.[]' <file>"
            msg = (
                f"[frugality trimmed: JSON array of {n} items]\n"
                f"  sample item keys: {keys}\n"
                f"  project only needed fields, e.g.: {suggestion}\n\n{reference}"
            )
            return msg.strip()

        keys = ", ".join(sorted(parsed.keys())[:20])
        extra = " ..." if len(parsed) > 20 else ""
        msg = (
            f"[frugality trimmed: JSON object with {n} keys]\n"
            f"  keys: {keys}{extra}\n"
            f"  project only needed keys with jq -r\n\n{reference}"
        )
        return msg.strip()

    @classmethod
    def trim_listing(cls, stdout: str, cfg: dict[str, Any], reference: str = "") -> str | None:
        large_json = cls.parse_large_json(stdout)
        if large_json:
            parsed, n = large_json
            return cls.skeleton_json(parsed, n, reference)

        lines = stdout.splitlines()
        n = len(lines)
        min_lines = cfg.get("min_lineas_listado", 120)
        pct = cfg.get("prefijo_homogeneo_pct", 0.7)

        if n < min_lines or not cls.is_homogeneous(lines, pct):
            return None

        h = cfg.get("head_lineas", 30)
        t = cfg.get("tail_lineas", 20)
        head = lines[:h]
        tail = lines[-t:] if n > h + t else []
        omitted = n - len(head) - len(tail)

        parts = [
            "\n".join(head),
            f"[... {omitted} lines omitted for frugality ...]",
            "\n".join(tail),
        ]
        res = "\n\n".join(parts)
        if reference:
            res += f"\n\n{reference}"
        return res
