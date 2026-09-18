from __future__ import annotations

import re

START_MARKER = "<!-- rules:start -->"
END_MARKER = "<!-- rules:end -->"
HARNESS_START_MARKER = "<!-- harness:start -->"
HARNESS_END_MARKER = "<!-- harness:end -->"
PATTERN = re.compile(
    rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)


def _pattern_for(start: str, end: str) -> re.Pattern[str]:
    if start == START_MARKER and end == END_MARKER:
        return PATTERN
    return re.compile(rf"{re.escape(start)}.*?{re.escape(end)}\n?", re.DOTALL)


class BlockInjector:
    """Reversibly injects and removes delimited blocks in configuration files."""

    @staticmethod
    def inject(
        content: str,
        block_body: str,
        *,
        start: str = START_MARKER,
        end: str = END_MARKER,
    ) -> str:
        new_block = f"{start}\n{block_body.strip()}\n{end}\n"
        pattern = _pattern_for(start, end)
        if start in content and end in content:
            return pattern.sub(new_block, content)

        stripped = content.rstrip()
        if not stripped:
            return new_block
        return f"{stripped}\n\n{new_block}"

    @staticmethod
    def remove(
        content: str,
        *,
        start: str = START_MARKER,
        end: str = END_MARKER,
    ) -> str:
        if start not in content or end not in content:
            return content
        pattern = _pattern_for(start, end)
        cleaned = pattern.sub("", content)
        if not cleaned.strip():
            return ""
        return cleaned.rstrip() + "\n"
