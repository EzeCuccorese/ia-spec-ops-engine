from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spec.cli import main, run_verify
from spec.core.preflight import PreflightManager
from spec.core.result import CheckResult, CheckStatus, VerificationReport
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import (
    InvalidTransitionError,
    Stage,
    Workflow,
    WorkflowSnapshot,
)


def _init_git_repo(path: Path) -> None:
    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        env=git_env,
    )
    (path / "README.md").write_text("Init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "initial commit"],
        check=True,
        env=git_env,
    )


def _setup_workflow_in_work(tmp_path: Path, feature_name: str = "Test Feature") -> Workflow:
    ProjectGovernance(tmp_path).initialize()
    workflow = Workflow(tmp_path)
    workflow.create_spec(feature_name, "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    return workflow


# V01: test_finish_rejects_invalid_evidence
def test_finish_rejects_invalid_evidence(tmp_path: Path) -> None:
    """V01: When evidence on disk is corrupt JSON, a list, missing feature/tree_fingerprint/report,

    or has an unsupported schema_version, finish() rejects with InvalidTransitionError and does NOT
    transition to COMPLETE.
    """
    workflow = _setup_workflow_in_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="test", status=CheckStatus.PASS),))
    snapshot, evidence_path = workflow.record_verification(report)
    assert snapshot.stage is Stage.VERIFY
    assert snapshot.verification_status is CheckStatus.PASS

    valid_content = evidence_path.read_text(encoding="utf-8")
    valid_data = json.loads(valid_content)

    invalid_payloads = [
        ("corrupt_json", "{not-valid-json"),
        ("json_list", json.dumps(["item1", "item2"])),
        (
            "missing_tree_fingerprint",
            json.dumps({k: v for k, v in valid_data.items() if k != "tree_fingerprint"}),
        ),
        ("empty_tree_fingerprint", json.dumps({**valid_data, "tree_fingerprint": ""})),
        ("missing_report", json.dumps({k: v for k, v in valid_data.items() if k != "report"})),
        ("missing_feature", json.dumps({k: v for k, v in valid_data.items() if k != "feature"})),
        ("wrong_schema_version", json.dumps({**valid_data, "schema_version": 999})),
    ]

    for label, payload in invalid_payloads:
        evidence_path.write_text(payload, encoding="utf-8")
        with pytest.raises(InvalidTransitionError, match="(?i)evidence"):
            workflow.finish()

        current_status = workflow.status()
        assert current_status is not None
        assert current_status.stage is Stage.VERIFY, (
            f"Failed for {label}: state transitioned away from VERIFY"
        )


# V02: test_required_nonpass_never_closes
def test_required_nonpass_never_closes(tmp_path: Path) -> None:
    """V02: Checks that are absent, empty, skipped, failed, error, or timed out must NEVER

    produce status PASS or allow transition to COMPLETE.
    """
    workflow = _setup_workflow_in_work(tmp_path)

    non_pass_reports = [
        ("empty_checks", VerificationReport(checks=())),
        (
            "skipped_check",
            VerificationReport(
                checks=(CheckResult(id="c1", status=CheckStatus.SKIPPED, required=True),)
            ),
        ),
        (
            "failed_check",
            VerificationReport(
                checks=(CheckResult(id="c2", status=CheckStatus.FAIL, required=True),)
            ),
        ),
        (
            "error_check",
            VerificationReport(
                checks=(CheckResult(id="c3", status=CheckStatus.ERROR, required=True),)
            ),
        ),
        (
            "timeout_check",
            VerificationReport(
                checks=(
                    CheckResult(
                        id="c4",
                        status=CheckStatus.ERROR,
                        required=True,
                        summary="Command timed out after 300 seconds",
                    ),
                )
            ),
        ),
    ]

    for label, report in non_pass_reports:
        assert report.status is not CheckStatus.PASS, f"{label} produced PASS"
        assert report.passed is False, f"{label} passed is True"

        snapshot, _ = workflow.record_verification(report)
        assert snapshot.stage is Stage.VERIFY
        assert snapshot.verification_status is not CheckStatus.PASS

        with pytest.raises(InvalidTransitionError, match="PASS"):
            workflow.finish()

        current = workflow.status()
        assert current is not None
        assert current.stage is not Stage.COMPLETE


# V03: test_invalid_transition_has_no_check_side_effect
def test_invalid_transition_has_no_check_side_effect(tmp_path: Path) -> None:
    """V03: In spec/cli.py run_verify, state transition must be validated BEFORE executing checks.

    If transition is invalid (e.g. state is IDLE or COMPLETE), verification commands must NOT be executed.
    """
    ProjectGovernance(tmp_path).initialize()
    spy_file = tmp_path / "spy_side_effect.txt"
    config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "spy-check",
                "command": [
                    sys.executable,
                    "-c",
                    f"import pathlib; pathlib.Path(r'{spy_file}').write_text('executed')",
                ],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(config), encoding="utf-8")

    # Case 1: IDLE state (no active spec)
    assert Workflow(tmp_path).status() is None
    with pytest.raises((InvalidTransitionError, SystemExit)):
        run_verify(tmp_path)
    assert not spy_file.exists(), "Check was executed during IDLE state!"

    with pytest.raises(SystemExit) as exc1:
        main(["verify", "--root", str(tmp_path)])
    assert exc1.value.code != 0
    assert not spy_file.exists(), "CLI verify executed check during IDLE state!"

    # Case 2: COMPLETE state
    workflow = Workflow(tmp_path)
    workflow.create_spec("Complete Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    pass_report = VerificationReport(checks=(CheckResult(id="init", status=CheckStatus.PASS),))
    workflow.record_verification(pass_report)
    completed_snapshot = workflow.finish()
    assert completed_snapshot.stage is Stage.COMPLETE

    with pytest.raises((InvalidTransitionError, SystemExit)):
        run_verify(tmp_path)
    assert not spy_file.exists(), "Check was executed during COMPLETE state!"

    with pytest.raises(SystemExit) as exc2:
        main(["verify", "--root", str(tmp_path)])
    assert exc2.value.code != 0
    assert not spy_file.exists(), "CLI verify executed check during COMPLETE state!"


# V04: test_preflight_checks_selected_base
def test_preflight_checks_selected_base(tmp_path: Path) -> None:
    """V04: Preflight baseline check runs on the selected base/tree, not blindly on cwd."""
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()

    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"

    # On main branch: write config.py with MODE = "production"
    (tmp_path / "config.py").write_text('MODE = "production"\n', encoding="utf-8")
    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "gate-check",
                "command": [
                    sys.executable,
                    "-c",
                    "import config; assert config.MODE == 'production'",
                ],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "setup main with production config"],
        check=True,
        env=git_env,
    )

    # Create and checkout feature-dev branch: modify config.py to MODE = "dev"
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "-b", "feature-dev"],
        check=True,
        env=git_env,
    )
    (tmp_path / "config.py").write_text('MODE = "dev"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "config.py"], check=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "dev mode on branch"],
        check=True,
        env=git_env,
    )

    # While cwd is on feature-dev (which would fail the check):
    # Preflight specifying base_branch="main" must test the main branch tree and PASS!
    mgr = PreflightManager(tmp_path)
    res_main = mgr.run("Main Feature", base_branch="main", use_worktree=False)
    assert res_main["status"] == "READY", f"Baseline failed: {res_main.get('error')}"
    assert res_main["baseline"] == "PASS"

    # Conversely, preflight specifying base_branch="feature-dev" must test feature-dev and FAIL!
    res_dev = mgr.run("Dev Feature", base_branch="feature-dev", use_worktree=False)
    assert res_dev["status"] == "FAIL"
    assert "Baseline verification checks failed" in res_dev["error"]


# V05: test_tree_changes_during_checks_rejected
def test_tree_changes_during_checks_rejected(tmp_path: Path) -> None:
    """V05: Fingerprint taken before and after checks; if working tree was modified while checks

    were running, verification evidence is rejected.
    """
    workflow = _setup_workflow_in_work(tmp_path)
    tamper_file = tmp_path / "tamper_during.py"
    tamper_file.write_text("ORIGINAL = True\n", encoding="utf-8")

    # Command mutates the working tree while checks are running
    config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "tampering-check",
                "command": [
                    sys.executable,
                    "-c",
                    f"import pathlib; pathlib.Path(r'{tamper_file}').write_text('TAMPERED = True\\n')",
                ],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(InvalidTransitionError, match="(?i)(tree|fingerprint)"):
        run_verify(tmp_path)

    # Workflow stage must not be COMPLETE
    current = workflow.status()
    assert current is not None
    assert current.stage is not Stage.COMPLETE


# V06: test_tree_changes_after_checks_rejected
def test_tree_changes_after_checks_rejected(tmp_path: Path) -> None:
    """V06: Modifying source code after record_verification() causes finish() to reject

    due to fingerprint mismatch until re-verified.
    """
    workflow = _setup_workflow_in_work(tmp_path)
    src_file = tmp_path / "app.py"
    src_file.write_text("def run(): return 1\n", encoding="utf-8")

    report = VerificationReport(checks=(CheckResult(id="test", status=CheckStatus.PASS),))
    workflow.record_verification(report)

    # Tamper with file after verification
    src_file.write_text("def run(): return 999\n", encoding="utf-8")

    with pytest.raises(InvalidTransitionError, match="(?i)(fingerprint|tree)"):
        workflow.finish()

    assert workflow.status().stage is Stage.VERIFY

    # Re-verify -> finish() succeeds
    workflow.record_verification(report)
    snapshot = workflow.finish()
    assert snapshot.stage is Stage.COMPLETE


# V07: test_trace_requires_executed_tests
def test_trace_requires_executed_tests(tmp_path: Path) -> None:
    """V07: Scenario tags (@s1) in test files that were NOT collected or executed do NOT

    count as PASS. Report and CLI exit must be INCOMPLETE / non-zero.
    """
    workflow = Workflow(tmp_path)
    ProjectGovernance(tmp_path).initialize()
    workflow.create_spec("Trace Gate Feature", "Description")

    # Spec defines @s1
    spec_md = workflow.feature_dir("trace-gate-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Trace Gate Feature\n\n@s1\nScenario: Target case\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()

    # Create a test file in tests/ containing @s1, but the test command skips / doesn't execute it
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "test_s1.py"
    test_file.write_text("def test_s1():\n    pass\n", encoding="utf-8")

    # Configure verification check that collects 0 tests or runs an unrelated command
    config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "unrelated-tests",
                "command": [
                    sys.executable,
                    "-c",
                    "print('collected 0 items / 0 passed'); print('unrelated check passed')",
                ],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(config), encoding="utf-8")

    exit_code = run_verify(tmp_path, as_json=False)
    assert exit_code != 0, f"Expected non-zero exit code for unexecuted scenarios, got {exit_code}"

    # State.json and evidence MUST record INCOMPLETE, NEVER PASS on trace gap
    state_file = tmp_path / ".spec" / "state.json"
    assert state_file.exists()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data.get("verification_status") == "INCOMPLETE"

    with pytest.raises(InvalidTransitionError, match="(?i)(scenario|trace|status PASS)"):
        workflow.finish()


# V08: test_evidence_attempts_are_immutable
def test_evidence_attempts_are_immutable(tmp_path: Path) -> None:
    """V08: Evidence attempts (both preflight baseline and verification) are strictly

    immutable and append-only (baseline-<timestamp>.json, verification-<timestamp>.json).
    No destructive overwrite of evidence files.
    """
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()
    v_config = {
        "schema_version": 1,
        "checks": [{"id": "pass", "command": ["true"], "required": True}],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    # 1. Preflight baseline attempts
    mgr = PreflightManager(tmp_path)
    gate1 = mgr.run_baseline_gate()
    assert gate1.passed is True
    evidence_dir = tmp_path / ".spec" / "evidence" / "preflight"
    baseline_files_1 = sorted(evidence_dir.glob("baseline-*.json"))
    assert len(baseline_files_1) == 1
    first_baseline_file = baseline_files_1[0]
    first_baseline_bytes = first_baseline_file.read_bytes()
    first_baseline_hash = hashlib.sha256(first_baseline_bytes).hexdigest()

    gate2 = mgr.run_baseline_gate()
    assert gate2.passed is True
    baseline_files_2 = sorted(evidence_dir.glob("baseline-*.json"))
    assert len(baseline_files_2) == 2
    second_baseline_file = [f for f in baseline_files_2 if f != first_baseline_file][0]

    # First baseline file MUST be strictly identical byte-for-byte and hash-for-hash
    assert first_baseline_file.read_bytes() == first_baseline_bytes
    assert hashlib.sha256(first_baseline_file.read_bytes()).hexdigest() == first_baseline_hash
    assert second_baseline_file.is_file()
    assert (evidence_dir / "latest_baseline.json").exists()

    # 2. Verification attempts
    workflow = Workflow(tmp_path)
    workflow.create_spec("Immutable Evidence Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()

    report1 = VerificationReport(checks=(CheckResult(id="pass1", status=CheckStatus.PASS),))
    snapshot1, vpath1 = workflow.record_verification(report1)
    assert vpath1.is_file()
    v1_bytes = vpath1.read_bytes()
    v1_hash = hashlib.sha256(v1_bytes).hexdigest()

    report2 = VerificationReport(checks=(CheckResult(id="pass2", status=CheckStatus.PASS),))
    snapshot2, vpath2 = workflow.record_verification(report2)
    assert vpath2.is_file()
    assert vpath1 != vpath2, "Verification evidence file path was not unique"

    # First verification evidence file MUST be untouched
    assert vpath1.read_bytes() == v1_bytes
    assert hashlib.sha256(vpath1.read_bytes()).hexdigest() == v1_hash


# V09: test_concurrent_updates_do_not_lose_state
def test_concurrent_updates_do_not_lose_state(tmp_path: Path) -> None:
    """V09: Atomic/file-locked writes on .spec/state.json prevent lost updates or corruption

    under concurrency.
    """
    workflow = _setup_workflow_in_work(tmp_path)

    def update_worker(worker_id: int) -> None:
        snap = WorkflowSnapshot(
            feature="test-feature",
            stage=Stage.WORK,
            updated_at=f"2026-09-07T12:00:0{worker_id}Z",
            verification_status=CheckStatus.PASS,
            evidence_path=f".spec/evidence/test-feature/worker-{worker_id}.json",
        )
        workflow.save_state(snap)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(update_worker, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # State file must remain valid, uncorrupted JSON adhering to schema
    status = workflow.status()
    assert status is not None
    assert status.stage is Stage.WORK
    assert status.verification_status is CheckStatus.PASS
    assert status.evidence_path is not None
    assert status.evidence_path.startswith(".spec/evidence/test-feature/worker-")


# V10: test_verification_config_is_bound_to_evidence
def test_verification_config_is_bound_to_evidence(tmp_path: Path) -> None:
    """V10: Changing verification.json checks after PASS invalidates the recorded evidence."""
    workflow = _setup_workflow_in_work(tmp_path)
    config_file = tmp_path / ".spec" / "verification.json"
    initial_config = {
        "schema_version": 1,
        "checks": [{"id": "check-a", "command": ["true"], "required": True}],
    }
    config_file.write_text(json.dumps(initial_config), encoding="utf-8")

    report = VerificationReport(checks=(CheckResult(id="check-a", status=CheckStatus.PASS),))
    workflow.record_verification(report)
    assert workflow.status().stage is Stage.VERIFY

    # Modify verification.json after recording PASS
    modified_config = {
        "schema_version": 1,
        "checks": [
            {"id": "check-a", "command": ["true"], "required": True},
            {"id": "check-b", "command": ["true"], "required": True},
        ],
    }
    config_file.write_text(json.dumps(modified_config), encoding="utf-8")

    # finish() must reject because the config was modified after evidence was recorded
    with pytest.raises(InvalidTransitionError, match="(?i)(config|fingerprint|evidence)"):
        workflow.finish()

    assert workflow.status().stage is Stage.VERIFY

    # Re-verify with updated config -> finish() succeeds
    report2 = VerificationReport(
        checks=(
            CheckResult(id="check-a", status=CheckStatus.PASS),
            CheckResult(id="check-b", status=CheckStatus.PASS),
        )
    )
    workflow.record_verification(report2)
    snapshot = workflow.finish()
    assert snapshot.stage is Stage.COMPLETE
