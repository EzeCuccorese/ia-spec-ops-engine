"""
Baseline Calibration & Invariant Verification Suite for Multi-Agent SDD Harness.

Tests deterministic success/failure boundaries for execution step counts,
scope drift penalties, and immutability/roundtrip serialization contracts.
"""

import tempfile
from pathlib import Path
import pytest

from devscripts.sdd.harness import HarnessSession
from devscripts.sdd.invariants import (
    HarnessConfig,
    TaskResult,
    VerificationPayload,
    calculate_scope_drift_penalty,
    DEFAULT_MAX_STEPS,
    DEFAULT_DRIFT_PENALTY_THRESHOLD,
)


def test_calibration_success_pass_within_limits():
    """
    Test A (Acierto): Ejecución dentro de max_steps (<= 25) y drift penalty <= 0.35
    valida estado SUCCESS para WORKER y PASS para QA.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = HarnessConfig(max_steps=25, drift_penalty_threshold=0.35)
        session = HarnessSession(target_dir=tmp_dir, config=config)

        # Worker evaluation within limits (15 steps <= 25, drift 0.10 <= 0.35) -> SUCCESS
        worker_eval = session.evaluate_task_execution(
            task_id="task-01",
            role="WORKER",
            executed_steps=15,
            scope_drift_penalty=0.10,
            summary="Task completed within step and drift thresholds",
        )
        assert worker_eval.status == "SUCCESS"
        assert worker_eval.executed_steps == 15
        assert worker_eval.scope_drift_penalty == 0.10

        # QA evaluation within limits (25 steps <= 25, drift 0.35 <= 0.35) -> PASS
        qa_eval = session.evaluate_task_execution(
            task_id="task-01",
            role="QA",
            executed_steps=25,
            scope_drift_penalty=0.35,
            summary="QA passed within maximum allowed thresholds",
        )
        assert qa_eval.status == "PASS"
        assert qa_eval.executed_steps == 25
        assert qa_eval.scope_drift_penalty == 0.35

        # Test calculation of penalty with expected vs modified files (0 drift)
        mod_files = ["devscripts/sdd/invariants.py"]
        exp_files = ["devscripts/sdd/invariants.py"]
        calculated_penalty = calculate_scope_drift_penalty(
            modified_files=mod_files,
            expected_files=exp_files,
            executed_steps=20,
            max_steps=25,
        )
        assert calculated_penalty <= 0.35

        calc_eval = session.evaluate_task_execution(
            task_id="task-01",
            role="WORKER",
            executed_steps=20,
            modified_files=mod_files,
            expected_files=exp_files,
        )
        assert calc_eval.status == "SUCCESS"


def test_calibration_failure_step_limit_exceeded():
    """
    Test B (Fallo por pasos): Exceso de pasos (> 25)
    valida estado REMEDIATION_REQUIRED.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = HarnessConfig(max_steps=25, drift_penalty_threshold=0.35)
        session = HarnessSession(target_dir=tmp_dir, config=config)

        # 26 steps (> 25) even with 0 drift -> REMEDIATION_REQUIRED
        worker_eval = session.evaluate_task_execution(
            task_id="task-02",
            role="WORKER",
            executed_steps=26,
            scope_drift_penalty=0.0,
            summary="Exceeded max step limit",
        )
        assert worker_eval.status == "REMEDIATION_REQUIRED"

        # QA eval with 30 steps -> REMEDIATION_REQUIRED
        qa_eval = session.evaluate_task_execution(
            task_id="task-02",
            role="QA",
            executed_steps=30,
            scope_drift_penalty=0.1,
            summary="QA detected excess steps",
        )
        assert qa_eval.status == "REMEDIATION_REQUIRED"

        # Verify record_worker_result enforces REMEDIATION_REQUIRED when steps exceeded
        w_log = session.record_worker_result(
            task_id="task-02",
            summary="Worker attempt with 28 steps",
            details="Excess steps test",
            status="SUCCESS",
            executed_steps=28,
        )
        log_content = w_log.read_text()
        assert "- **Status:** REMEDIATION_REQUIRED" in log_content


def test_calibration_failure_scope_drift_exceeded():
    """
    Test C (Fallo por drift): Scope Drift Penalty > 0.35
    valida estado REMEDIATION_REQUIRED.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = HarnessConfig(max_steps=25, drift_penalty_threshold=0.35)
        session = HarnessSession(target_dir=tmp_dir, config=config)

        # Explicit penalty > 0.35 (e.g., 0.36) within step limit (10 steps) -> REMEDIATION_REQUIRED
        worker_eval = session.evaluate_task_execution(
            task_id="task-03",
            role="WORKER",
            executed_steps=10,
            scope_drift_penalty=0.36,
            summary="Excessive scope drift penalty",
        )
        assert worker_eval.status == "REMEDIATION_REQUIRED"

        # QA eval with scope drift penalty = 0.50 -> REMEDIATION_REQUIRED
        qa_eval = session.evaluate_task_execution(
            task_id="task-03",
            role="QA",
            executed_steps=10,
            scope_drift_penalty=0.50,
            summary="QA detected excessive scope drift",
        )
        assert qa_eval.status == "REMEDIATION_REQUIRED"

        # Test calculated penalty when unexpected files are modified
        mod_files = ["devscripts/sdd/invariants.py", "unrelated_1.py", "unrelated_2.py"]
        exp_files = ["devscripts/sdd/invariants.py"]
        calculated_penalty = calculate_scope_drift_penalty(
            modified_files=mod_files,
            expected_files=exp_files,
            executed_steps=10,
            max_steps=25,
        )
        assert calculated_penalty > 0.35

        calc_eval = session.evaluate_task_execution(
            task_id="task-03",
            role="WORKER",
            executed_steps=10,
            modified_files=mod_files,
            expected_files=exp_files,
        )
        assert calc_eval.status == "REMEDIATION_REQUIRED"


def test_calibration_immutability_and_serialization_invariants():
    """
    Test D (Invariantes): Serialización roundtrip e inmutabilidad de dataclasses
    (HarnessConfig, TaskResult, VerificationPayload).
    """
    # 1. HarnessConfig Invariants
    config = HarnessConfig(
        max_steps=25,
        drift_penalty_threshold=0.35,
        timeout_seconds=300,
        allowed_tool_actions=["view_file", "replace_file_content"],
    )
    with pytest.raises(AttributeError):
        config.max_steps = 50  # Frozen dataclass mutation check

    config_dict = config.to_dict()
    config_json = config.to_json()
    config_restored = HarnessConfig.from_dict(config_dict)
    assert config_restored == config
    assert "allowed_tool_actions" in config_json

    # 2. TaskResult Invariants
    task_res = TaskResult(
        task_id="task-04",
        role="WORKER",
        status="SUCCESS",
        executed_steps=12,
        scope_drift_penalty=0.15,
        summary="Calibration test invariant",
        details="Tested immutability and roundtrip",
    )
    with pytest.raises(AttributeError):
        task_res.status = "FAIL"  # Frozen dataclass mutation check

    res_dict = task_res.to_dict()
    res_json = task_res.to_json()
    res_restored = TaskResult.from_dict(res_dict)
    assert res_restored.task_id == task_res.task_id
    assert res_restored.status == task_res.status
    assert res_restored.executed_steps == task_res.executed_steps
    assert res_restored.scope_drift_penalty == task_res.scope_drift_penalty

    # 3. VerificationPayload Invariants
    payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
        remediation_instructions="None required",
        details={"checks_passed": 4},
    )
    with pytest.raises(AttributeError):
        payload.passed = False  # Frozen dataclass mutation check

    payload_dict = payload.to_dict()
    payload_json = payload.to_json()
    payload_restored = VerificationPayload.from_dict(payload_dict)
    assert payload_restored == payload
    assert "checks_passed" in payload_json
