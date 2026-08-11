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
