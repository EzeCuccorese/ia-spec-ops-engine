"""Coverage tests for ai_governance.frugality.output_trimmer edge cases."""

from __future__ import annotations

import json

from ai_governance.frugality.output_trimmer import OutputTrimmer


def test_is_homogeneous_returns_false_for_blank_input() -> None:
    assert OutputTrimmer.is_homogeneous(["", "   ", ""]) is False


def test_parse_large_json_returns_none_on_decode_error() -> None:
    assert OutputTrimmer.parse_large_json("[1, 2, not json") is None


def test_parse_large_json_dict_over_threshold() -> None:
    data = {f"key_{i}": i for i in range(60)}
    result = OutputTrimmer.parse_large_json(json.dumps(data), threshold=50)
    assert result is not None
    parsed, n = result
    assert n == 60
    assert isinstance(parsed, dict)


def test_skeleton_json_list_of_non_dict_items() -> None:
    result = OutputTrimmer.skeleton_json([1, 2, 3, 4], 4)
    assert "sample item keys: int" in result
    assert "jq -r '.[]' <file>" in result


def test_skeleton_json_dict_with_reference() -> None:
    parsed = {f"key_{i}": i for i in range(25)}
    result = OutputTrimmer.skeleton_json(parsed, 25, reference="full output: /tmp/x.txt")
    assert "JSON object with 25 keys" in result
    assert "..." in result
    assert "full output: /tmp/x.txt" in result


def test_skeleton_json_small_dict_no_ellipsis() -> None:
    parsed = {"a": 1, "b": 2}
    result = OutputTrimmer.skeleton_json(parsed, 2)
    assert "JSON object with 2 keys" in result
    assert "..." not in result


def test_parse_large_json_returns_none_when_under_threshold() -> None:
    small = json.dumps([1, 2, 3])
    assert OutputTrimmer.parse_large_json(small, threshold=50) is None


def test_trim_listing_empty_tail_when_lines_fit_in_head_and_tail_budget() -> None:
    """When total lines <= head+tail, the tail section is empty."""
    cfg = {
        "min_lineas_listado": 50,
        "prefijo_homogeneo_pct": 0.7,
        "head_lineas": 40,
        "tail_lineas": 40,
    }
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(60)]
    result = OutputTrimmer.trim_listing("\n".join(lines), cfg)
    assert result is not None
    assert "[... 20 lines omitted for frugality ...]" in result
    assert result.strip().endswith("[... 20 lines omitted for frugality ...]")


def test_trim_listing_returns_none_when_not_homogeneous() -> None:
    cfg = {
        "min_lineas_listado": 5,
        "prefijo_homogeneo_pct": 0.7,
        "head_lineas": 5,
        "tail_lineas": 5,
    }
    prefixes = ["abc", "def", "ghi", "jkl", "mno", "pqr", "stu", "vwx", "yz1", "234"]
    lines = [f"{prefix} distinct line {i}" for i, prefix in enumerate(prefixes)]
    assert OutputTrimmer.trim_listing("\n".join(lines), cfg) is None


def test_trim_listing_returns_none_when_under_min_lines() -> None:
    cfg = {
        "min_lineas_listado": 100,
        "prefijo_homogeneo_pct": 0.7,
        "head_lineas": 5,
        "tail_lineas": 5,
    }
    lines = [f"/src/item_{i}.tsx" for i in range(10)]
    assert OutputTrimmer.trim_listing("\n".join(lines), cfg) is None


def test_trim_listing_appends_reference_when_provided() -> None:
    cfg = {
        "min_lineas_listado": 50,
        "prefijo_homogeneo_pct": 0.7,
        "head_lineas": 5,
        "tail_lineas": 5,
    }
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(80)]
    result = OutputTrimmer.trim_listing("\n".join(lines), cfg, reference="full output: /tmp/x.txt")
    assert result is not None
    assert "full output: /tmp/x.txt" in result
