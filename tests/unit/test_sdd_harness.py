import os
import tempfile
from pathlib import Path
import pytest

from devscripts.core.process import run_command_safe
from devscripts.sdd import harness, memory
from devscripts.sdd.invariants import VerificationPayload

def test_parse_tasks():
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tmp:
        tmp.write("""# Feature Tasks
- [ ] Task 1: Setup database schema
- [x] Task 2: Create API endpoints
- [ ] T3: Add unit tests
""")
        tmp_path = Path(tmp.name)

    tasks = harness.parse_tasks(tmp_path)
    assert len(tasks) == 3
    assert tasks[0].id == "task-01"
    assert not tasks[0].completed
    assert tasks[1].completed
    assert tasks[2].id == "T3"
    assert not tasks[2].completed


def test_get_next_pending_task_and_mark_completed():
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tmp:
        tmp.write("""# Tasks
- [x] Task 1
- [ ] Task 2
- [ ] Task 3
""")
        tmp_path = Path(tmp.name)

    pending = harness.get_next_pending_task(tmp_path)
    assert pending is not None
    assert pending.description == "Task 2"

    success = harness.mark_task_completed(tmp_path, pending)
    assert success

    lines = tmp_path.read_text().splitlines()
    assert lines[2] == "- [x] Task 2"


    next_pending = harness.get_next_pending_task(tmp_path)
    assert next_pending is not None
    assert next_pending.description == "Task 3"


def test_log_task_event_and_harness_session():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_dir = tmp_path / ".specify" / "specs" / "my-feature"
        spec_dir.mkdir(parents=True, exist_ok=True)
        
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("- [ ] T1: Build feature\n")

        sess = harness.HarnessSession(feature_name="my-feature", target_dir=str(tmp_path))
        st = sess.status()
        assert st["total_tasks"] == 1
        assert st["completed_tasks"] == 0
        assert st["pending_tasks"] == 1

        w_log = sess.record_worker_result("T1", "Implemented feature T1", "Details of T1", status="SUCCESS")
        assert w_log.exists()

        qa_log = sess.record_qa_result("T1", "QA Approved T1", "All tests passed", passed=True)
        assert qa_log.exists()

        st_after = sess.status()
        assert st_after["completed_tasks"] == 1
        assert st_after["pending_tasks"] == 0


def test_harness_session_step_counter_and_remediation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_dir = tmp_path / ".specify" / "specs" / "test-feature"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("- [ ] T1: Feature Task\n")

        custom_config = harness.HarnessConfig(max_steps=10, drift_penalty_threshold=0.35)
        sess = harness.HarnessSession(feature_name="test-feature", target_dir=str(tmp_path), config=custom_config)

        # Initial steps and config assertion
        assert sess.executed_steps == 0
        assert sess.config.max_steps == 10

        sess.increment_steps(5)
        assert sess.executed_steps == 5

        # Normal execution evaluation (5 steps <= 10, penalty 0.0 <= 0.35)
        eval_res = sess.evaluate_task_execution("T1", role="WORKER")
        assert eval_res.status == "SUCCESS"
        assert eval_res.executed_steps == 5

        # Step count exceeds max_steps (12 > 10) -> REMEDIATION_REQUIRED
        eval_exceeded = sess.evaluate_task_execution("T1", role="WORKER", executed_steps=12)
        assert eval_exceeded.status == "REMEDIATION_REQUIRED"

        # Scope drift penalty exceeds threshold -> REMEDIATION_REQUIRED
        eval_drift = sess.evaluate_task_execution("T1", role="WORKER", executed_steps=5, scope_drift_penalty=0.5)
        assert eval_drift.status == "REMEDIATION_REQUIRED"

        # Recording worker result with excess steps overrides status to REMEDIATION_REQUIRED
        worker_log = sess.record_worker_result("T1", "Summary", "Details", status="SUCCESS", executed_steps=15)
        log_content = worker_log.read_text()
        assert "- **Status:** REMEDIATION_REQUIRED" in log_content

        # Recording QA result with high drift overrides status to REMEDIATION_REQUIRED and fails QA
        qa_log = sess.record_qa_result("T1", "QA Summary", "QA Details", passed=True, executed_steps=5, scope_drift_penalty=0.4)
        qa_content = qa_log.read_text()
        assert "- **Status:** REMEDIATION_REQUIRED" in qa_content

        # Confirm task remained uncompleted due to QA failure/remediation
        st = sess.status()
        assert st["completed_tasks"] == 0


def test_harness_verification_integration():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_dir = tmp_path / ".specify" / "specs" / "verify-feature"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("- [ ] T1: Build component\n")

        sess = harness.HarnessSession(feature_name="verify-feature", target_dir=str(tmp_path))

        # Test verify_task return type
        v_payload = sess.verify_task(run_tests=False, run_linter=False)
        assert isinstance(v_payload, VerificationPayload)

        # Test failed verification payload override
        failed_payload = VerificationPayload(
            passed=False,
            linter_status="FAIL",
            test_status="PASS",
            remediation_instructions="Fix syntax error"
        )

        eval_res = sess.evaluate_task_execution("T1", role="QA", verification_payload=failed_payload)
        assert eval_res.status == "FAIL"

        qa_log = sess.record_qa_result("T1", "QA check", "Failed linter", passed=True, verification_payload=failed_payload, auto_commit=False)
        qa_content = qa_log.read_text()
        assert "- **Status:** FAIL" in qa_content
        assert "Fix syntax error" in qa_content


def test_harness_auto_git_commit_aider_style():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        git_env = os.environ.copy()
        git_env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})

        run_command_safe(["git", "init"], cwd=str(tmp_path), env=git_env)
        run_command_safe(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), env=git_env)
        run_command_safe(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), env=git_env)
        run_command_safe(["git", "config", "commit.gpgsign", "false"], cwd=str(tmp_path), env=git_env)

        spec_dir = tmp_path / ".specify" / "specs" / "git-feature"
        spec_dir.mkdir(parents=True, exist_ok=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("- [ ] task-01: Implement feature X\n")

        run_command_safe(["git", "add", "-A"], cwd=str(tmp_path), env=git_env)
        run_command_safe(["git", "-c", "commit.gpgsign=false", "commit", "-m", "initial commit"], cwd=str(tmp_path), env=git_env)

        code_file = tmp_path / "app.py"
        code_file.write_text("print('hello world')\n")

        sess = harness.HarnessSession(feature_name="git-feature", target_dir=str(tmp_path))

        qa_log = sess.record_qa_result("task-01", "QA Passed", "All tests green", passed=True, auto_commit=True)
        assert qa_log.exists()

        code, out, err = run_command_safe(["git", "log", "-n", "1", "--oneline"], cwd=str(tmp_path), env=git_env)
        assert code == 0
        assert "sdd(task): complete task-01 - Implement feature X" in out


def test_harness_additional_edge_cases(tmp_path: Path):
    # parse_tasks / mark_task_completed with missing files or out of range
    assert harness.parse_tasks(tmp_path / "nonexistent.md") == []
    assert harness.mark_task_completed(tmp_path / "nonexistent.md", harness.SDDTask("1", "desc", False, 1)) is False

    dummy_md = tmp_path / "dummy.md"
    dummy_md.write_text("- [ ] task-01: First\n")
    assert harness.mark_task_completed(dummy_md, harness.SDDTask("1", "desc", False, 999)) is False

    # build_task_context with spec.md, checklist.md, memory.md
    spec_dir = tmp_path / ".specify" / "specs" / "full-feat"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("Spec header\nLine 2\n")
    (spec_dir / "checklist.md").write_text("Checklist item 1\n")
    (tmp_path / ".specify" / "memory.md").write_text("Memory item 1\n")
    (spec_dir / "tasks.md").write_text("- [ ] task-01: Task 1\n")

    task = harness.SDDTask("task-01", "Task 1", False, 1)
    ctx = harness.build_task_context(task, feature_name="full-feat", target_dir=str(tmp_path))
    assert ctx["task_id"] == "task-01"
    assert "Spec header" in ctx["spec_summary"]
    assert "Checklist item 1" in ctx["checklist_summary"]
    assert "Memory item 1" in ctx["memory_summary"]

    # Session reset_steps and run_next
    sess = harness.HarnessSession(feature_name="full-feat", target_dir=str(tmp_path))
    sess.increment_steps(5)
    assert sess.executed_steps == 5
    sess.reset_steps()
    assert sess.executed_steps == 0

    dispatch = sess.run_next()
    assert dispatch["status"] == "TASK_DISPATCHED"
    assert dispatch["task"].id == "task-01"

    # Mark completed and run_next again
    harness.mark_task_completed(spec_dir / "tasks.md", task)
    all_done = sess.run_next()
    assert all_done["status"] == "ALL_COMPLETED"

    # commit_task_completion when no changes staged
    git_env = os.environ.copy()
    git_env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    run_command_safe(["git", "init"], cwd=str(tmp_path), env=git_env)
    run_command_safe(["git", "add", "-A"], cwd=str(tmp_path), env=git_env)
    run_command_safe(["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=str(tmp_path), env=git_env)
    # Re-stage any history files created after init commit
    run_command_safe(["git", "add", "-A"], cwd=str(tmp_path), env=git_env)
    if run_command_safe(["git", "status", "--porcelain"], cwd=str(tmp_path), env=git_env)[1].strip():
        run_command_safe(["git", "-c", "commit.gpgsign=false", "commit", "-m", "sync"], cwd=str(tmp_path), env=git_env)
    assert sess.commit_task_completion("task-01", "description") is None

