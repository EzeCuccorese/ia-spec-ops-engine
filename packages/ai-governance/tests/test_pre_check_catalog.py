from ai_governance.frugality.pre_check import PreCheck, replacement_patterns


def test_replacement_patterns_point_to_deterministic_tools() -> None:
    patterns = replacement_patterns()
    assert patterns
    for pattern_id, matcher, advice in patterns:
        assert pattern_id.startswith("tool:") and callable(matcher)
        assert advice.startswith("Deterministic alternative:")


def test_which_stacks_suggests_ws_detect() -> None:
    advice = PreCheck.check_command(
        "which java node python go", extra_patterns=replacement_patterns()
    )
    assert advice is not None and "ws detect" in advice


def test_unrelated_command_has_no_advice() -> None:
    assert PreCheck.check_command("echo hi", extra_patterns=replacement_patterns()) is None
