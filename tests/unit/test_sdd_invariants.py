import pytest
from pathlib import Path
from devscripts.sdd.invariants import (
    HarnessConfig,
    VerificationPayload,
    TaskResult,
    calculate_scope_drift_penalty,
    DEFAULT_MAX_STEPS,
    DEFAULT_DRIFT_PENALTY_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
)


def test_harness_config_defaults_and_immutability():
    config = HarnessConfig()
    assert config.max_steps == 25
    assert config.drift_penalty_threshold == 0.35
    assert config.timeout_seconds == 300
    assert config.allowed_tool_actions == []

    # Check immutability
    with pytest.raises(AttributeError):
        config.max_steps = 30


def test_harness_config_serialization():
    config = HarnessConfig(
        max_steps=50,
        drift_penalty_threshold=0.2,
        timeout_seconds=600,
        allowed_tool_actions=["view_file", "run_command"],
    )
    d = config.to_dict()
    assert d["max_steps"] == 50
    assert d["allowed_tool_actions"] == ["view_file", "run_command"]

    restored = HarnessConfig.from_dict(d)
    assert restored == config


def test_verification_payload_defaults_and_serialization():
    payload = VerificationPayload()
    assert payload.passed is False
    assert payload.linter_status == "PENDING"
    assert payload.test_status == "PENDING"

    d = payload.to_dict()
    restored = VerificationPayload.from_dict(d)
    assert restored == payload


def test_task_result_validations_and_serialization():
    res = TaskResult(
        task_id="task-01",
        role="WORKER",
        status="PASS",
        executed_steps=10,
        scope_drift_penalty=0.1,
        summary="Done",
        details="Tested invariants",
    )
    assert res.task_id == "task-01"
    assert res.status == "PASS"

    # Immutability check
    with pytest.raises(AttributeError):
        res.status = "FAIL"

    # Invalid status
    with pytest.raises(ValueError):
        TaskResult(task_id="task-01", status="INVALID_STATUS")

    restored = TaskResult.from_dict(res.to_dict())
    assert restored.task_id == res.task_id
    assert restored.status == res.status


def test_calculate_scope_drift_penalty_no_drift():
    modified = ["devscripts/sdd/invariants.py"]
    expected = ["devscripts/sdd/invariants.py"]
    penalty = calculate_scope_drift_penalty(modified, expected, executed_steps=5, max_steps=25)
    assert penalty == 0.0
    assert penalty <= DEFAULT_DRIFT_PENALTY_THRESHOLD


def test_calculate_scope_drift_penalty_unexpected_files():
    modified = ["devscripts/sdd/invariants.py", "unrelated.py"]
    expected = ["devscripts/sdd/invariants.py"]
    penalty = calculate_scope_drift_penalty(modified, expected, executed_steps=10, max_steps=25)
    # File drift component = (1 / 2) * 0.75 = 0.375
    assert penalty > DEFAULT_DRIFT_PENALTY_THRESHOLD


def test_calculate_scope_drift_penalty_step_excess():
    modified = ["devscripts/sdd/invariants.py"]
    expected = ["devscripts/sdd/invariants.py"]
    penalty = calculate_scope_drift_penalty(modified, expected, executed_steps=30, max_steps=25)
    # Exceeds max_steps (30 > 25)
    assert penalty > DEFAULT_DRIFT_PENALTY_THRESHOLD


def test_json_serialization_and_empty_expected():
    config = HarnessConfig(max_steps=10)
    assert '"max_steps": 10' in config.to_json()

    vp = VerificationPayload(passed=True)
    assert '"passed": true' in vp.to_json().lower()

    tr = TaskResult(task_id="task-01", status="PASS")
    assert '"task_id": "task-01"' in tr.to_json()

    # Modified files provided but expected_files empty vs None
    penalty_empty = calculate_scope_drift_penalty(["a.py"], [], executed_steps=1, max_steps=25)
    assert penalty_empty == 0.75  # 1.0 * 0.75

    penalty_none = calculate_scope_drift_penalty(["a.py"], None, executed_steps=1, max_steps=25)
    assert penalty_none == 0.0

