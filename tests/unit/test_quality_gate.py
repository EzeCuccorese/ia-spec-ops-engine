"""
Unit tests for devscripts.sdd.quality_gate module.
"""

import json
from pathlib import Path
import pytest

from devscripts.sdd.quality_gate import (
    BaselineSnapshot,
    TestDelta,
    EntryPointCheck,
    ContractCheck,
    GateResult,
    verify_entry_points,
    verify_public_contracts,
    compare_test_results,
    capture_baseline,
    run_gate_check,
)


def test_baseline_snapshot_serialization():
    snapshot = BaselineSnapshot(
        timestamp="2026-08-11T12:00:00Z",
        total_tests=403,
        passed_tests=401,
        failed_tests=0,
        skipped_tests=2,
        entry_points={"sdd": "devscripts.cli.sdd.sdd:main"},
        public_contracts={"devscripts.core.finder": ["find_project_root"]},
        test_names=["tests/unit/test_sdd.py::test_example"],
    )

    data_dict = snapshot.to_dict()
    assert data_dict["total_tests"] == 403
    assert data_dict["entry_points"]["sdd"] == "devscripts.cli.sdd.sdd:main"

    json_str = snapshot.to_json()
    reconstructed = BaselineSnapshot.from_json(json_str)

    assert reconstructed == snapshot


def test_gate_result_serialization():
    test_delta = TestDelta(
        status="PASS",
        baseline_passed=400,
        current_passed=400,
        regressions=[],
        new_failures=[],
        new_skipped=[],
    )
    ep_check = EntryPointCheck(
        passed=True,
        total=1,
        successful=["sdd"],
        failed={},
    )
    contract_check = ContractCheck(
        passed=True,
        missing_symbols={},
    )
    gate_res = GateResult(
        passed=True,
        timestamp="2026-08-11T12:00:00Z",
        phase="pre-task",
        test_result=test_delta,
        entry_point_result=ep_check,
        contract_result=contract_check,
        details={"info": "all good"},
    )

    json_str = gate_res.to_json()
    reconstructed = GateResult.from_dict(json.loads(json_str))
    assert reconstructed.passed is True
    assert reconstructed.phase == "pre-task"
    assert reconstructed.test_result.status == "PASS"


def test_verify_entry_points_valid():
    entry_points = {
        "sdd": "devscripts.cli.sdd.sdd:main",
    }
    check = verify_entry_points(entry_points)
    assert check.passed is True
    assert check.total == 1
    assert "sdd" in check.successful
    assert len(check.failed) == 0


def test_verify_entry_points_invalid():
    entry_points = {
        "non_existent": "devscripts.cli.non_existent_module:main",
        "invalid_func": "devscripts.cli.sdd.sdd:non_existent_func",
    }
    check = verify_entry_points(entry_points)
    assert check.passed is False
    assert "non_existent" in check.failed
    assert "invalid_func" in check.failed


def test_verify_public_contracts_valid():
    contracts = {
        "devscripts.core.finder": ["find_project_root"],
    }
    check = verify_public_contracts(contracts)
    assert check.passed is True
    assert len(check.missing_symbols) == 0


def test_verify_public_contracts_missing_symbol():
    contracts = {
        "devscripts.core.finder": ["non_existent_symbol_12345"],
    }
    check = verify_public_contracts(contracts)
    assert check.passed is False
    assert "devscripts.core.finder" in check.missing_symbols
    assert "non_existent_symbol_12345" in check.missing_symbols["devscripts.core.finder"]


def test_compare_test_results_no_regression():
    baseline_tests = ["test_a", "test_b"]
    current_passed = ["test_a", "test_b"]
    current_failed = []
    current_skipped = []

    delta = compare_test_results(
        baseline_passed_names=baseline_tests,
        current_passed_names=current_passed,
        current_failed_names=current_failed,
        current_skipped_names=current_skipped,
    )
    assert delta.status == "PASS"
    assert len(delta.regressions) == 0


def test_compare_test_results_with_regression():
    baseline_tests = ["test_a", "test_b"]
    current_passed = ["test_a"]
    current_failed = ["test_b"]
    current_skipped = []

    delta = compare_test_results(
        baseline_passed_names=baseline_tests,
        current_passed_names=current_passed,
        current_failed_names=current_failed,
        current_skipped_names=current_skipped,
    )
    assert delta.status == "REGRESSION"
    assert delta.regressions == ["test_b"]


def test_capture_baseline_and_gate_check(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\nsdd = "devscripts.cli.sdd.sdd:main"\n', encoding="utf-8")
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_dummy.py").write_text("def test_dummy_pass(): assert True\n", encoding="utf-8")

    baseline_file = tmp_path / "baseline.json"
    snapshot = capture_baseline(output_path=baseline_file, root_dir=tmp_path)

    assert snapshot.total_tests == 1
    assert "sdd" in snapshot.entry_points
    assert baseline_file.exists()

    gate_res = run_gate_check(baseline_path=baseline_file, phase="test-phase", root_dir=tmp_path)
    assert gate_res.passed is True
    assert gate_res.phase == "test-phase"
