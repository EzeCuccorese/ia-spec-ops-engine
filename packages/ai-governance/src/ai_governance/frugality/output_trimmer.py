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
    def is_homogeneous(lineas: list[str], pct: float = 0.7) -> bool:
        prefijos = [l.strip()[:3] for l in lineas if l.strip()]
        if not prefijos:
            return False
        _, top = Counter(prefijos).most_common(1)[0]
        return (top / len(prefijos)) >= pct

    @staticmethod
    def parse_large_json(texto: str, threshold: int = 50) -> tuple[Any, int] | None:
        texto = texto.strip()
        if not texto or texto[0] not in "[{":
            return None
        try:
            parsed = json.loads(texto)
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
                claves = ", ".join(sorted(sample.keys()))
                first_key = sorted(sample.keys())[0] if sample else ""
                sugerencia = f"jq -r '.[].{first_key}' <file>"
            else:
                claves = type(sample).__name__
                sugerencia = "jq -r '.[]' <file>"
            msg = (
                f"[frugality trimmed: JSON array of {n} items]\n"
                f"  sample item keys: {claves}\n"
                f"  project only needed fields, e.g.: {sugerencia}\n\n{reference}"
            )
            return msg.strip()

        claves = ", ".join(sorted(parsed.keys())[:20])
        extra = " ..." if len(parsed) > 20 else ""
        msg = (
            f"[frugality trimmed: JSON object with {n} keys]\n"
            f"  keys: {claves}{extra}\n"
            f"  project only needed keys with jq -r\n\n{reference}"
        )
        return msg.strip()

    @classmethod
    def trim_listing(
        cls, stdout: str, cfg: dict[str, Any], reference: str = ""
    ) -> str | None:
        large_json = cls.parse_large_json(stdout)
        if large_json:
            parsed, n = large_json
            return cls.skeleton_json(parsed, n, reference)

        lineas = stdout.splitlines()
        n = len(lineas)
        min_lineas = cfg.get("min_lineas_listado", 120)
        pct = cfg.get("prefijo_homogeneo_pct", 0.7)

        if n < min_lineas or not cls.is_homogeneous(lineas, pct):
            return None

        h = cfg.get("head_lineas", 30)
        t = cfg.get("tail_lineas", 20)
        head = lineas[:h]
        tail = lineas[-t:] if n > h + t else []
        omitidas = n - len(head) - len(tail)

        partes = [
            "\n".join(head),
            f"[... {omitidas} lines omitted for frugality ...]",
            "\n".join(tail),
        ]
        res = "\n\n".join(partes)
        if reference:
            res += f"\n\n{reference}"
        return res
