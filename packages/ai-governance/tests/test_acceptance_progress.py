"""
test_acceptance_progress.py — Acceptance tests for progress & session contracts P01–P07.

Contracts:
- P01 (test_invalid_ids_do_not_alias_valid_task): Ensure invalid IDs are rejected with ValueError and do NOT alias to valid tasks.
- P02 (test_create_existing_fails_without_overwrite): Calling create/new on existing task ID fails without overwriting state or history.
- P03 (test_concurrent_updates_preserve_history): Concurrent appends/updates preserve both entries without lost updates.
- P04 (test_corrupt_state_is_not_missing): Corrupt JSON file raises explicit error and is not treated as None or overwritten.
- P05 (test_configured_directory_failure_is_visible): Inaccessible/unwritable directory raises explicit error without silent fallback.
- P06 (test_close_reopen_and_resume_are_neutral): Closing, reopening, and resuming tasks work neutrally without Jira/Git/Claude dependencies.
- P07 (test_path_boundary_rejects_external_symlink): Rejects symlinks pointing outside task directory boundary.
"""

from __future__ import annotations

import concurrent.futures
import stat
from pathlib import Path

import pytest
from ai_governance.session.cli import main as cli_main
from ai_governance.session.tracker import CorruptTaskError, SessionTracker, TaskState


def test_invalid_ids_do_not_alias_valid_task(tmp_path: Path) -> None:
    """P01: Ensure invalid IDs (like 'a/b', 'a b', '../', empty string) are rejected with

    ValueError and do NOT alias to 'ab' or overwrite valid tasks.
    """
    tracker = SessionTracker(root_dir=tmp_path)

    # 1. Establish legitimate valid task 'ab'
    valid_task = TaskState(id="ab", title="Legitimate Task AB", summary="Original summary")
    tracker.create_task(valid_task)
    tracker.append_log("ab", "Legitimate initial log entry.")

    # 2. Attempt invalid IDs that previously could have been sanitized/aliased to 'ab'
    invalid_ids = [
        "a/b",
        "a b",
        "a\tb",
        "a\nb",
        "../ab",
        "ab/../",
        "../",
        "",
        "   ",
        "a\\b",
        "/ab",
        "ab/",
        ".ab",
    ]

    for bad_id in invalid_ids:
        # Strict validation on create_task
        with pytest.raises(ValueError):
            tracker.create_task(TaskState(id=bad_id, title="Malicious Alias", summary="Hacked"))

        # Strict validation on get_task
        with pytest.raises(ValueError):
            tracker.get_task(bad_id)

        # Strict validation on append_log
        with pytest.raises(ValueError):
            tracker.append_log(bad_id, "Injected log entry")

        # Strict validation on read_log
        with pytest.raises(ValueError):
            tracker.read_log(bad_id)

    # 3. Verify legitimate task 'ab' remains completely intact and unaffected
    task_ab = tracker.get_task("ab")
    assert task_ab is not None
    assert task_ab.title == "Legitimate Task AB"
    assert task_ab.summary == "Original summary"

    log_ab = tracker.read_log("ab")
    assert "Legitimate initial log entry." in log_ab
    assert "Injected log entry" not in log_ab


def test_create_existing_fails_without_overwrite(tmp_path: Path, monkeypatch, capsys) -> None:
    """P02: Calling create / new on an existing task ID must fail (e.g.

    FileExistsError or ValueError) without overwriting previous state or history.
    """
    tracker = SessionTracker(root_dir=tmp_path / "progress")

    # Create original task
    original = TaskState(
        id="TASK-100",
        title="Initial Original Title",
        summary="Original untouched summary",
        steps=[{"text": "Step 1", "done": True}],
    )
    tracker.create_task(original)
    tracker.append_log("TASK-100", "Initial log commit 1.")

    # Calling create_task with duplicate ID must fail
    duplicate = TaskState(
        id="TASK-100",
        title="Overwriting Title",
        summary="Overwritten summary",
    )
    with pytest.raises((FileExistsError, ValueError)):
        tracker.create_task(duplicate)

    # Verify original state and history are 100% preserved
    reloaded = tracker.get_task("TASK-100")
    assert reloaded is not None
    assert reloaded.title == "Initial Original Title"
    assert reloaded.summary == "Original untouched summary"
    assert len(reloaded.steps) == 1
    assert "Initial log commit 1." in tracker.read_log("TASK-100")
    assert "Overwriting Title" not in tracker.read_log("TASK-100")

    # Verify CLI 'new' also fails with non-zero exit code on duplicate
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    monkeypatch.setattr(
        "sys.argv",
        ["progress", "new", "TASK-100", "--title", "CLI Duplicate", "--summary", "CLI summary"],
    )
    rc = cli_main()
    assert rc == 1
    # Agent mode routes ERROR status lines to stderr (see ai_governance.output.emit_status).
    err_out = capsys.readouterr().err
    assert "Error creating task" in err_out

    # State still preserved after CLI attempt
    reloaded_after_cli = tracker.get_task("TASK-100")
    assert reloaded_after_cli is not None
    assert reloaded_after_cli.title == "Initial Original Title"


def test_concurrent_updates_preserve_history(tmp_path: Path) -> None:
    """P03: Concurrent appends / updates using file locks or atomic writes

    preserve both entries or raise explicit conflict without lost updates.
    """
    tracker = SessionTracker(root_dir=tmp_path)
    task_id = "CONCUR-1"
    tracker.create_task(TaskState(id=task_id, title="Concurrent Task"))

    num_threads = 20
    entries = [f"Unique log entry payload #{i}" for i in range(num_threads)]

    def _worker(entry: str) -> None:
        local_tracker = SessionTracker(root_dir=tmp_path)
        local_tracker.append_log(task_id, entry)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker, entry) for entry in entries]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    log_content = tracker.read_log(task_id)
    for entry in entries:
        assert entry in log_content, f"Missing entry: {entry}"


def test_corrupt_state_is_not_missing(tmp_path: Path) -> None:
    """P04: Corrupt JSON file raises an explicit error and does NOT get treated

    as None/missing or get silently overwritten by a new task.
    """
    tracker = SessionTracker(root_dir=tmp_path)
    corrupt_id = "CORRUPT-42"
    task_file = tracker.tasks_dir / f"{corrupt_id}.json"
    task_file.write_text("{invalid json: broken syntax, [[", encoding="utf-8")

    # get_task must raise an explicit error (e.g. CorruptTaskError or ValueError)
    # and MUST NOT return None
    with pytest.raises((CorruptTaskError, ValueError)):
        tracker.get_task(corrupt_id)

    # create_task must NOT silently overwrite the corrupted task file
    new_attempt = TaskState(id=corrupt_id, title="Overwrite Corrupt", summary="Trying overwrite")
    with pytest.raises((FileExistsError, ValueError)):
        tracker.create_task(new_attempt)

    # Content on disk must remain the corrupted file untouched
    assert task_file.read_text(encoding="utf-8") == "{invalid json: broken syntax, [["


def test_configured_directory_failure_is_visible(tmp_path: Path) -> None:
    """P05: When the configured progress directory is inaccessible/unwritable,

    it raises an explicit error and does NOT silently fall back to an unexpected folder.
    """
    # Create an unwritable directory
    unwritable_root = tmp_path / "unwritable_root"
    unwritable_root.mkdir()
    # Remove write permission
    unwritable_root.chmod(stat.S_IREAD | stat.S_IEXEC)

    forbidden_dir = unwritable_root / "cannot_create_subdir"

    cwd_before = Path.cwd()
    unexpected_fallback = cwd_before / ".ai-governance" / "progress"
    fallback_created_before = unexpected_fallback.exists()

    try:
        with pytest.raises(OSError):
            SessionTracker(root_dir=forbidden_dir)

        # Ensure no silent fallback created .ai-governance in cwd
        if not fallback_created_before:
            assert not unexpected_fallback.exists()
    finally:
        # Restore permissions for cleanup
        unwritable_root.chmod(stat.S_IRWXU)


def test_close_reopen_and_resume_are_neutral(tmp_path: Path, monkeypatch) -> None:
    """P06: Closing, reopening, and resuming tasks work cleanly without requiring

    Jira, Git, or Claude dependencies.
    """
    # Ensure no Jira, Git, or Claude env vars
    monkeypatch.delenv("AI_GOVERNANCE_STATE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROGRESS_DIR", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_SERVER", raising=False)

    tracker = SessionTracker(root_dir=tmp_path)
    task_id = "OFFLINE-1"
    task = TaskState(id=task_id, title="Offline Neutral Task", summary="Purely local work")
    tracker.create_task(task)

    # Active initially
    assert len(tracker.list_active_tasks()) == 1
    assert tracker.list_active_tasks()[0].id == task_id
    assert tracker.get_task(task_id).status == "active"

    # Close task
    closed_task = tracker.close_task(task_id, reason="Completed offline task")
    assert closed_task.status == "closed"
    assert len(tracker.list_active_tasks()) == 0
    assert tracker.get_task(task_id).status == "closed"
    assert "Closed task: Completed offline task" in tracker.read_log(task_id)

    # Reopen task
    reopened_task = tracker.reopen_task(task_id, reason="Reopening for extra tests")
    assert reopened_task.status == "active"
    assert len(tracker.list_active_tasks()) == 1
    assert tracker.get_task(task_id).status == "active"
    assert "Reopened task: Reopening for extra tests" in tracker.read_log(task_id)

    # Pause and resume task
    tracker.pause_task(task_id)
    assert tracker.get_task(task_id).status == "paused"
    resumed_task = tracker.resume_task(task_id)
    assert resumed_task.status == "active"
    assert tracker.get_task(task_id).status == "active"


def test_path_boundary_rejects_external_symlink(tmp_path: Path) -> None:
    """P07: Rejects symlinks pointing outside the task directory boundary."""
    tracker = SessionTracker(root_dir=tmp_path)

    # Target file outside the tracker boundary
    outside_dir = tmp_path / "external_boundary"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret_data.json"
    secret_file.write_text('{"id": "secret", "title": "Confidential"}', encoding="utf-8")

    # Symlink inside tasks_dir pointing to external target
    symlink_task = tracker.tasks_dir / "LINK-1.json"
    symlink_task.symlink_to(secret_file)

    # Must raise ValueError / boundary error when accessed via tracker
    with pytest.raises(ValueError, match="traverses outside|outside tasks directory"):
        tracker.get_task("LINK-1")

    with pytest.raises(ValueError, match="traverses outside|outside tasks directory"):
        tracker.create_task(TaskState(id="LINK-1", title="Symlink Overwrite"))

    # Also verify external symlink on markdown log
    secret_log = outside_dir / "secret_log.md"
    secret_log.write_text("Secret Log Content", encoding="utf-8")
    symlink_md = tracker.tasks_dir / "LINK-LOG.md"
    symlink_md.symlink_to(secret_log)

    with pytest.raises(ValueError, match="traverses outside|outside tasks directory"):
        tracker.read_log("LINK-LOG")

    with pytest.raises(ValueError, match="traverses outside|outside tasks directory"):
        tracker.append_log("LINK-LOG", "Unauthorized append")
