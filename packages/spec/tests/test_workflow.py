import json
from pathlib import Path

import pytest

from spec.core.result import CheckResult, CheckStatus, VerificationReport
from spec.spec.workflow import ArtifactExistsError, InvalidTransitionError, Stage, Workflow


def test_create_spec_initializes_active_recoverable_state(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)

    snapshot = workflow.create_spec("User authentication", "Authenticate users safely.")

    assert snapshot.feature == "user-authentication"
    assert snapshot.stage is Stage.SPEC
    assert workflow.status() == snapshot
    assert (tmp_path / ".spec/specs/user-authentication/spec.md").exists()
    persisted = json.loads((tmp_path / ".spec/state.json").read_text())
    assert persisted["active_feature"] == "user-authentication"
    assert persisted["stage"] == "spec"


def test_duplicate_spec_does_not_overwrite_user_artifact(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("User authentication", "First version")
    spec = tmp_path / ".spec/specs/user-authentication/spec.md"
    spec.write_text("user edited content\n")

    with pytest.raises(ArtifactExistsError):
        workflow.create_spec("User authentication", "Replacement")

    assert spec.read_text() == "user edited content\n"


def test_new_spec_does_not_replace_an_active_incomplete_feature(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("First", "Description")

    with pytest.raises(InvalidTransitionError, match="already active"):
        workflow.create_spec("Second", "Description")

    assert workflow.status().feature == "first"


def test_plan_requires_active_spec(tmp_path: Path) -> None:
    with pytest.raises(InvalidTransitionError, match="active spec"):
        Workflow(tmp_path).create_plan()


def test_plan_requires_nonempty_spec_artifact(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    (tmp_path / ".spec/specs/feature/spec.md").write_text("")

    with pytest.raises(InvalidTransitionError, match="spec.md"):
        workflow.create_plan()


def test_tasks_require_plan(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")

    with pytest.raises(InvalidTransitionError, match="plan"):
        workflow.create_tasks()


def test_full_artifact_flow_persists_each_transition(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")

    plan_snapshot = workflow.create_plan()
    tasks_snapshot = workflow.create_tasks()

    assert plan_snapshot.stage is Stage.PLAN
    assert tasks_snapshot.stage is Stage.TASKS
    assert (tmp_path / ".spec/specs/feature/plan.md").exists()
    assert (tmp_path / ".spec/specs/feature/tasks.md").exists()
    assert Workflow(tmp_path).status().stage is Stage.TASKS


def test_status_reports_missing_state_without_mutation(tmp_path: Path) -> None:
    assert Workflow(tmp_path).status() is None
    assert not (tmp_path / ".spec").exists()


def test_rerunning_plan_recovers_interruption_after_artifact_creation(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    plan = tmp_path / ".spec/specs/feature/plan.md"
    plan.write_text("# Recovered plan\n")

    snapshot = workflow.create_plan()

    assert snapshot.stage is Stage.PLAN
    assert plan.read_text() == "# Recovered plan\n"


def _workflow_at_work(tmp_path: Path) -> Workflow:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    snapshot = workflow.begin_work()
    assert snapshot.stage is Stage.WORK
    return workflow


def test_verification_attempt_records_immutable_evidence(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.FAIL),))

    snapshot, evidence_path = workflow.record_verification(report)

    assert snapshot.stage is Stage.VERIFY
    assert snapshot.verification_status is CheckStatus.FAIL
    assert evidence_path.is_file()
    assert json.loads(evidence_path.read_text())["report"]["status"] == "FAIL"


def test_failed_verification_cannot_finish(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)
    workflow.record_verification(
        VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.FAIL),))
    )

    with pytest.raises(InvalidTransitionError, match="PASS"):
        workflow.finish()


def test_passed_verification_is_required_to_finish(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)

    snapshot = workflow.finish()

    assert snapshot.stage is Stage.COMPLETE
    assert snapshot.verification_status is CheckStatus.PASS


def test_finish_enforces_scenario_traceability(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Trace Feature", "Test traceability gate")
    spec_md = workflow.feature_dir("trace-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Trace Feature\n\n"
        "@s2\nScenario: Second case\n  Given x\n  When y\n  Then z\n\n"
        "@s3\nScenario: Third case\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    _, evidence_path = workflow.record_verification(report)

    # Missing mappings: should fail
    with pytest.raises(InvalidTransitionError, match="Scenarios lacking test mapping: @s2, @s3"):
        workflow.finish()

    # Map the scenarios in work.md
    work_md = workflow.feature_dir("trace-feature") / "work.md"
    work_md.write_text(
        "# Work Log\n\n- @s2 -> test_second\n- @s3 -> test_third\n",
        encoding="utf-8",
    )
    _, evidence_path = workflow.record_verification(report)

    snapshot = workflow.finish()
    assert snapshot.stage is Stage.COMPLETE

    assert snapshot.evidence_path == str(evidence_path.relative_to(tmp_path))


def test_finish_rejects_modified_working_tree_after_verification(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)
    src_file = tmp_path / "src" / "main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("def hello(): return 'world'\n", encoding="utf-8")

    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)

    # Modifying a source file after verification triggers fingerprint mismatch
    src_file.write_text("def hello(): return 'tampered'\n", encoding="utf-8")

    with pytest.raises(
        InvalidTransitionError,
        match="Finish rejected: Working tree was modified after recorded verification \\(fingerprint mismatch\\)",
    ):
        workflow.finish()

    # Re-verifying allows finish() to pass
    workflow.record_verification(report)
    snapshot = workflow.finish()
    assert snapshot.stage is Stage.COMPLETE
