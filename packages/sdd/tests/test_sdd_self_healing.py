"""
Tests unitarios para el módulo de Self-Healing y extracción de fallos de tests.
"""

from pathlib import Path
import pytest

from sdd_engine.harness.self_healing import (
    parse_pytest_failures,
    parse_generic_failures,
    SelfHealingCycle,
    TestFailureDetail,
)


def test_parse_pytest_failures():
    sample_output = """
=================================== FAILURES ===================================
___________________________ test_feature_execution ____________________________

    def test_feature_execution():
>       assert result == "expected"
E       AssertionError: assert 'actual' == 'expected'
E         - expected
E         + actual

tests/test_flow.py:42: AssertionError
=========================== short test summary info ============================
FAILED tests/test_flow.py::test_feature_execution - AssertionError: assert 'actual' == 'expected'
============================== 1 failed in 0.15s ===============================
"""
    failures = parse_pytest_failures(sample_output)
    assert len(failures) >= 1
    f = failures[0]
    assert "test_feature_execution" in f.test_name
    assert "tests/test_flow.py" in f.file_path
    assert f.line_number == 42
    assert "AssertionError" in f.error_message or "AssertionError" in f.failing_assertion


def test_self_healing_cycle_attempts_and_prompt():
    cycle = SelfHealingCycle(task_id="T1-auth", max_retries=3)
    assert cycle.current_attempt == 0

    detail = TestFailureDetail(
        test_name="test_login",
        file_path="tests/test_auth.py",
        line_number=25,
        failing_assertion="assert token is not None",
    )

    record = cycle.record_attempt(passed=False, failures=[detail], linter_errors=["E501 line too long"])
    assert record["attempt"] == 1
    assert record["can_retry"] is True

    prompt = cycle.generate_repair_instructions([detail], ["E501 line too long"])
    assert "Intento 1/3" in prompt
    assert "test_login" in prompt
    assert "assert token is not None" in prompt
    assert "E501 line too long" in prompt
