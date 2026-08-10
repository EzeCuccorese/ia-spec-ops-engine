import tempfile
from pathlib import Path
import pytest

from devscripts.sdd import harness, memory

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
