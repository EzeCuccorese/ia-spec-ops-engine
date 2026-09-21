import json
from pathlib import Path

import pytest
from spec.core.result import CheckResult, CheckStatus, VerificationReport
from spec.spec.workflow import (
    ArtifactExistsError,
    CorruptStateError,
    InvalidTransitionError,
    Stage,
    Workflow,
    compute_tree_fingerprint,
    slugify,
)


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
    report = VerificationReport(
        checks=(
            CheckResult(
                id="tests",
                status=CheckStatus.PASS,
                evidence={"stdout": "test_second PASSED\ntest_third PASSED\n"},
            ),
        )
    )
    _, evidence_path = workflow.record_verification(report)

    # Missing mappings: should fail
    with pytest.raises(InvalidTransitionError, match="Scenarios lacking test mapping: @s2, @s3"):
        workflow.finish()

    # Map the scenarios in work.md and provide actual test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_cases.py").write_text(
        "def test_second():\n    pass\n\ndef test_third():\n    pass\n",
        encoding="utf-8",
    )
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


def test_slugify_rejects_names_without_letters_or_numbers() -> None:
    with pytest.raises(ValueError, match="at least one letter or number"):
        slugify("*** ---")


def test_compute_tree_fingerprint_for_missing_root_is_stable_empty_hash(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    import hashlib

    assert compute_tree_fingerprint(missing) == hashlib.sha256(b"").hexdigest()


def test_compute_tree_fingerprint_excludes_evidence_directory(tmp_path: Path) -> None:
    (tmp_path / ".spec").mkdir()
    (tmp_path / ".spec" / "evidence").mkdir()
    (tmp_path / ".spec" / "evidence" / "note.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("hello\n", encoding="utf-8")

    fingerprint_with_evidence = compute_tree_fingerprint(tmp_path)

    (tmp_path / ".spec" / "evidence" / "note.json").write_text("{different}", encoding="utf-8")
    fingerprint_after_evidence_change = compute_tree_fingerprint(tmp_path)

    assert fingerprint_with_evidence == fingerprint_after_evidence_change


def test_compute_tree_fingerprint_skips_broken_symlinks(tmp_path: Path) -> None:
    (tmp_path / "tracked.txt").write_text("hello\n", encoding="utf-8")
    broken_link = tmp_path / "broken-link"
    broken_link.symlink_to(tmp_path / "does-not-exist-target")

    # Must not raise even though the symlink target is missing (is_file() is False).
    fingerprint = compute_tree_fingerprint(tmp_path)
    assert isinstance(fingerprint, str)


def test_status_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    state_dir = tmp_path / ".spec"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"schema_version": 99, "active_feature": "x", "stage": "spec"}),
        encoding="utf-8",
    )

    with pytest.raises(CorruptStateError, match="Unsupported workflow state schema"):
        Workflow(tmp_path).status()


def test_status_rejects_malformed_state_payload(tmp_path: Path) -> None:
    state_dir = tmp_path / ".spec"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"schema_version": 1, "active_feature": "x"}),  # missing "stage"
        encoding="utf-8",
    )

    with pytest.raises(CorruptStateError, match="Invalid workflow state"):
        Workflow(tmp_path).status()


def test_create_spec_recovers_when_state_missing_but_spec_file_present(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    spec_dir = tmp_path / ".spec" / "specs" / "feature"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec: Feature\n\nSome content\n", encoding="utf-8")

    snapshot = workflow.create_spec("Feature", "Description")

    assert snapshot.stage is Stage.SPEC
    assert workflow.status().feature == "feature"


def test_create_plan_requires_spec_stage(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)

    with pytest.raises(InvalidTransitionError, match="requires stage spec"):
        workflow.create_plan()


def test_rerunning_tasks_recovers_interruption_after_artifact_creation(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    tasks = tmp_path / ".spec/specs/feature/tasks.md"
    tasks.write_text("# Recovered tasks\n")

    snapshot = workflow.create_tasks()

    assert snapshot.stage is Stage.TASKS
    assert tasks.read_text() == "# Recovered tasks\n"


def test_begin_work_requires_tasks_stage(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")

    with pytest.raises(InvalidTransitionError, match="requires active tasks"):
        workflow.begin_work()


def test_begin_work_preserves_existing_work_log(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    work_md = tmp_path / ".spec/specs/feature/work.md"
    work_md.parent.mkdir(parents=True, exist_ok=True)
    work_md.write_text("# Recovered work log\n", encoding="utf-8")

    snapshot = workflow.begin_work()

    assert snapshot.stage is Stage.WORK
    assert work_md.read_text() == "# Recovered work log\n"


def test_finish_requires_verify_stage(tmp_path: Path) -> None:
    workflow = _workflow_at_work(tmp_path)

    with pytest.raises(InvalidTransitionError, match="requires a verification attempt"):
        workflow.finish()


def test_finish_requires_recorded_evidence_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = _workflow_at_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)

    # Force a VERIFY-stage snapshot without an evidence path.
    current = workflow.status()
    workflow._persist(current.feature, Stage.VERIFY, verification_status=CheckStatus.PASS)

    with pytest.raises(InvalidTransitionError, match="requires recorded verification evidence"):
        workflow.finish()


def test_finish_rejects_config_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import spec.spec.workflow as workflow_module

    workflow = _workflow_at_work(tmp_path)
    verification_config = tmp_path / ".spec" / "verification.json"
    verification_config.parent.mkdir(parents=True, exist_ok=True)
    verification_config.write_text('{"schema_version": 1, "checks": []}\n', encoding="utf-8")

    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)

    # Recorded tree_fingerprint already reflects the config file above, so pin
    # compute_tree_fingerprint to that recorded value at finish-time and force the
    # direct config-hash lookup to disagree with it, isolating the config-hash guard
    # from the (already covered) fingerprint guard.
    recorded_fingerprint = compute_tree_fingerprint(tmp_path)
    monkeypatch.setattr(
        workflow_module, "compute_tree_fingerprint", lambda _root: recorded_fingerprint
    )
    monkeypatch.setattr(workflow_module, "sha256_file", lambda _path: "deadbeef")

    with pytest.raises(InvalidTransitionError, match="Verification configuration was modified"):
        workflow.finish()


def test_finish_skips_traceability_when_spec_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import spec.spec.workflow as workflow_module

    workflow = _workflow_at_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)
    recorded_fingerprint = compute_tree_fingerprint(tmp_path)

    spec_md = workflow.feature_dir("feature") / "spec.md"
    spec_md.unlink()

    # Deleting spec.md changes the real tree fingerprint; pin it back to the
    # recorded value so finish() reaches the (missing) spec-file branch under test
    # instead of failing earlier on the fingerprint guard.
    monkeypatch.setattr(
        workflow_module, "compute_tree_fingerprint", lambda _root: recorded_fingerprint
    )

    snapshot = workflow.finish()

    assert snapshot.stage is Stage.COMPLETE


def test_compute_tree_fingerprint_excludes_evidence_file_at_spec_root(tmp_path: Path) -> None:
    (tmp_path / ".spec").mkdir()
    # An unusual layout where ".spec/evidence" is a plain file rather than a directory.
    (tmp_path / ".spec" / "evidence").write_text("stray evidence file", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("hello\n", encoding="utf-8")

    before = compute_tree_fingerprint(tmp_path)
    (tmp_path / ".spec" / "evidence").write_text("changed evidence file", encoding="utf-8")
    after = compute_tree_fingerprint(tmp_path)

    assert before == after


def test_create_spec_after_completion_refuses_to_recreate_existing_artifact(
    tmp_path: Path,
) -> None:
    workflow = _workflow_at_work(tmp_path)
    report = VerificationReport(checks=(CheckResult(id="tests", status=CheckStatus.PASS),))
    workflow.record_verification(report)
    snapshot = workflow.finish()
    assert snapshot.stage is Stage.COMPLETE

    with pytest.raises(ArtifactExistsError, match="will not be overwritten"):
        workflow.create_spec("Feature", "Description")


def test_create_artifact_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    target = tmp_path / "artifact.txt"
    target.write_text("first\n", encoding="utf-8")

    with pytest.raises(ArtifactExistsError, match="will not be overwritten"):
        workflow._create_artifact(target, "second\n")
