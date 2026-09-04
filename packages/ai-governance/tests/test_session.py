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
