from __future__ import annotations

import re

START_MARKER = "<!-- rules:start -->"
END_MARKER = "<!-- rules:end -->"
PATTERN = re.compile(
    rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)


class BlockInjector:
    """Reversibly injects and removes delimited rules blocks in configuration files."""

    @staticmethod
    def inject(content: str, block_body: str) -> str:
        new_block = f"{START_MARKER}\n{block_body.strip()}\n{END_MARKER}\n"
        if START_MARKER in content and END_MARKER in content:
            return PATTERN.sub(new_block, content)

        stripped = content.rstrip()
        if not stripped:
            return new_block
        return f"{stripped}\n\n{new_block}"

    @staticmethod
    def remove(content: str) -> str:
        if START_MARKER not in content or END_MARKER not in content:
            return content
        cleaned = PATTERN.sub("", content)
        if not cleaned.strip():
            return ""
        return cleaned.rstrip() + "\n"
