"""
test_trimmer.py — Specialized test output condenser for coding agents.
Reduces green test noise by up to 95% while keeping failure traces and summary lines intact.
"""

from __future__ import annotations

import re
from typing import Any

TEST_CMD_RE = re.compile(
    r"\b(jest|vitest|mocha|ava|tap|nyc)\b"
    r"|\bpytest\b|\bnosetests?\b|\btox\b"
    r"|\bgo\s+test\b|\bcargo\s+test\b"
    r"|\brspec\b|\bminitest\b|\bphpunit\b"
    r"|\bgradle\w*\s+.*\btest\b|\bmvn\w*\s+.*\btest\b"
    r"|\bdotnet\s+test\b|\bctest\b"
    r"|\b(npm|yarn|pnpm|bun)\s+(run\s+)?test\b",
    re.IGNORECASE,
)

FAIL_MARKER_RE = re.compile(
    r"\bFAIL(ED)?\b|✕|✗|×|--- FAIL:|AssertionError|"
    r"Traceback \(most recent call last\)|panicked at|"
    r"^E\s{3}|Failures:|^Error:\s",
    re.MULTILINE,
)


class TestTrimmer:
    @staticmethod
    def is_test_command(cmd: str) -> bool:
        return bool(TEST_CMD_RE.search(cmd))

    @staticmethod
    def trim(stdout: str, cfg: dict[str, Any], reference: str = "") -> str:
        lines = stdout.splitlines()
        n = len(lines)
        if n == 0:
            return stdout

        tail_n = min(cfg.get("test_tail_lineas", 15), n)
        summary_start = n - tail_n
        final_summary = lines[summary_start:]

        failure_indices = [
            i for i, line in enumerate(lines[:summary_start]) if FAIL_MARKER_RE.search(line)
        ]

        parts = []
        if not failure_indices:
            head_n = min(cfg.get("test_head_lineas", 3), summary_start)
            parts.append("\n".join(lines[:head_n]))
            omitted = summary_start - head_n
            if omitted > 0:
                parts.append(
                    f"[... {omitted} lines of green test output omitted for frugality ...]"
                )
            previous_end = summary_start - 1
        else:
            before = cfg.get("test_contexto_antes", 3)
            after = cfg.get("test_contexto_despues", 30)
            blocks: list[tuple[int, int]] = []
            for i in failure_indices:
                start, end = max(0, i - before), min(summary_start - 1, i + after)
                if blocks and start <= blocks[-1][1] + 1:
                    blocks[-1] = (blocks[-1][0], max(blocks[-1][1], end))
                else:
                    blocks.append((start, end))

            previous_end = -1
            for start, end in blocks:
                omitted = start - previous_end - 1
                if omitted > 0:
                    parts.append(f"[... {omitted} test output lines omitted ...]")
                parts.append("\n".join(lines[start : end + 1]))
                previous_end = end

        if summary_start > previous_end + 1:
            # summary_start > previous_end + 1 already guarantees omitted > 0 here.
            omitted = summary_start - previous_end - 1
            parts.append(f"[... {omitted} lines omitted ...]")

        parts.append("\n".join(final_summary))

        result = "\n\n".join(parts)
        if reference:
            result += f"\n\n{reference}"
        return result
