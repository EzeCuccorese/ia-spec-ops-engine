"""Coverage tests for ai_governance.frugality.test_trimmer edge cases."""

from __future__ import annotations

from ai_governance.frugality.test_trimmer import TestTrimmer

CFG = {
    "test_umbral_chars": 200,
    "test_head_lineas": 2,
    "test_tail_lineas": 3,
    "test_contexto_antes": 2,
    "test_contexto_despues": 5,
}


def test_trim_returns_stdout_unchanged_when_empty() -> None:
    assert TestTrimmer.trim("", CFG) == ""


def test_trim_no_omission_when_head_covers_entire_pre_summary_section() -> None:
    """When head_lineas >= summary_start, there is nothing to omit before the tail."""
    cfg = {**CFG, "test_head_lineas": 10, "test_tail_lineas": 2}
    lines = [f"PASSED line {i}" for i in range(5)] + ["tail line 1", "tail line 2"]
    result = TestTrimmer.trim("\n".join(lines), cfg)
    assert "omitted for frugality" not in result


def test_trim_failure_at_start_has_no_leading_omission() -> None:
    """A failure block starting at line 0 has previous_end == start - 1, so no lead gap."""
    cfg = {**CFG, "test_contexto_antes": 2, "test_contexto_despues": 1, "test_tail_lineas": 2}
    lines = [
        "FAILED test_x - AssertionError",
        "extra context line",
        "tail line 1",
        "tail line 2",
    ]
    result = TestTrimmer.trim("\n".join(lines), cfg)
    assert "test output lines omitted" not in result.split("FAILED")[0]


def test_trim_no_trailing_gap_when_last_block_reaches_summary_start() -> None:
    """When the last failure block's end reaches summary_start - 1, no trailing omission."""
    cfg = {**CFG, "test_contexto_antes": 1, "test_contexto_despues": 100, "test_tail_lineas": 2}
    lines = [
        "some passing line",
        "FAILED test_y - boom",
        "tail line 1",
        "tail line 2",
    ]
    result = TestTrimmer.trim("\n".join(lines), cfg)
    assert result.count("[...") == 0


def test_trim_trailing_gap_when_last_block_ends_before_summary_start() -> None:
    """When context-after is short, a trailing gap is reported before the summary."""
    cfg = {**CFG, "test_contexto_antes": 0, "test_contexto_despues": 0, "test_tail_lineas": 2}
    lines = [
        "FAILED test_z - boom",
        "unrelated passing line",
        "tail line 1",
        "tail line 2",
    ]
    result = TestTrimmer.trim("\n".join(lines), cfg)
    assert "[... 1 lines omitted ...]" in result
