"""Reversible marker-delimited blocks inside shared text files (e.g. AGENTS.md)."""

from __future__ import annotations

import re


def _pattern_for(start: str, end: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(start)}.*?{re.escape(end)}\n?", re.DOTALL)


class BlockInjector:
    """Reversibly injects and removes delimited blocks in configuration files."""

    @staticmethod
    def inject(
        content: str,
        block_body: str,
        *,
        start: str,
        end: str,
        prepend: bool = False,
    ) -> str:
        new_block = f"{start}\n{block_body.strip()}\n{end}\n"
        pattern = _pattern_for(start, end)
        if start in content and end in content:
            return pattern.sub(lambda _: new_block, content)

        stripped = content.rstrip()
        if not stripped:
            return new_block
        if prepend:
            return f"{new_block}\n{content.lstrip()}"
        return f"{stripped}\n\n{new_block}"

    @staticmethod
    def remove(
        content: str,
        *,
        start: str,
        end: str,
    ) -> str:
        if start not in content or end not in content:
            return content
        pattern = _pattern_for(start, end)
        cleaned = pattern.sub("", content)
        if not cleaned.strip():
            return ""
        return cleaned.strip("\n") + "\n"
