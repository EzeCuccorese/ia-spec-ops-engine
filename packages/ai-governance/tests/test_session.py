from __future__ import annotations

from pathlib import Path

from ai_governance.session.tracker import SessionTracker, TaskState


def test_session_tracker_crud(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(
        id="ONB-1164",
        title="Webview Authentication Refactor",
        status="active",
        summary="Refactoring auth flow in Android and Webview",
        steps=[{"text": "Add unit tests", "done": True}, {"text": "Run e2e", "done": False}],
        repos=[{"path": "/app/auth", "branch": "feat/onb-1164", "pr": "42"}],
    )
    tracker.save_task(task)

    loaded = tracker.get_task("ONB-1164")
    assert loaded is not None
    assert loaded.id == "ONB-1164"
    assert loaded.title == "Webview Authentication Refactor"
    assert loaded.status == "active"
    assert len(loaded.steps) == 2
    assert loaded.steps[0]["done"] is True
    assert loaded.steps[1]["done"] is False

    # Append notes to markdown log
    tracker.append_log("ONB-1164", "Tested token refresh endpoint successfully.")
    log = tracker.read_log("ONB-1164")
    assert "Tested token refresh endpoint successfully." in log

    # List active tasks
    active = tracker.list_active_tasks()
    assert len(active) == 1
    assert active[0].id == "ONB-1164"


def test_task_resolver_jira_regex() -> None:
    from ai_governance.session.resolver import JIRA_RE

    m1 = JIRA_RE.search("feat/onb-1164-login-fix")
    assert m1 is not None
    assert m1.group(1).upper() == "ONB-1164"

    m2 = JIRA_RE.search("fix/PROJ-99-crash")
    assert m2 is not None
    assert m2.group(1).upper() == "PROJ-99"

    m3 = JIRA_RE.search("chore/cleanup-code")
    assert m3 is None


def test_session_tracker_default_neutral_path(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("SPECOPS_PROGRESS_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROGRESS_DIR", raising=False)

    # 1. Default: ~/.specops/progress
    tracker = SessionTracker()
    assert tracker.root_dir == fake_home / ".specops" / "progress"

    # Remove the created specops dir to test fallback when only claude dir exists
    import shutil

    shutil.rmtree(fake_home / ".specops")

    # 2. Fallback to ~/.claude/progress if it exists and specops doesn't
    claude_dir = fake_home / ".claude" / "progress"
    claude_dir.mkdir(parents=True)
    tracker_legacy = SessionTracker()
    assert tracker_legacy.root_dir == claude_dir

    # 3. SPECOPS_PROGRESS_DIR env var takes highest precedence
    custom_dir = tmp_path / "custom_progress"
    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(custom_dir))
    tracker_env = SessionTracker()
    assert tracker_env.root_dir == custom_dir


def test_session_tracker_directory_traversal(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)

    # Path traversal patterns are strictly rejected with ValueError (P01)
    with pytest.raises(ValueError):
        tracker._json_path("../../etc/passwd")

    with pytest.raises(ValueError):
        tracker._md_path("../sub/task")

    # Empty or pure traversal identifiers raise ValueError
    with pytest.raises(ValueError):
        tracker._json_path("..")

    with pytest.raises(ValueError):
        tracker._json_path("../../")

    with pytest.raises(ValueError):
        tracker._sanitize_task_id("")

    # If an attacker somehow bypasses _validate_task_id, relative_to check catches it
    tracker._validate_task_id = lambda tid: "../../outside"
    with pytest.raises(ValueError, match="traverses outside"):
        tracker._json_path("malicious")
    with pytest.raises(ValueError, match="traverses outside"):
        tracker._md_path("malicious")


def test_session_tracker_write_failure_raises_oserror(tmp_path: Path, monkeypatch) -> None:
    import os

    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(id="FAIL-1", title="Write Failure Test")

    def mock_write_fail(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(os, "replace", mock_write_fail)
    with pytest.raises(OSError, match="Failed to save task"):
        tracker.save_task(task)

    monkeypatch.undo()

    def mock_open_fail(*args, **kwargs):
        raise OSError("Read-only file system")

    monkeypatch.setattr("builtins.open", mock_open_fail)
    with pytest.raises(OSError, match="Failed to append log"):
        tracker.append_log("FAIL-1", "Test note")


def test_session_cli_error_handling(monkeypatch, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "1")
    monkeypatch.setattr("sys.argv", ["progress", "new", "..", "--title", "Bad Task"])
    rc = cli.main()
    assert rc == 1
    # Agent mode routes ERROR status lines to stderr (see ai_governance.output.emit_status).
    err_out = capsys.readouterr().err
    assert "Error creating task" in err_out
