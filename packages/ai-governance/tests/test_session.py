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


# ---------------------------------------------------------------------------
# resolver.py — real git repositories in tmp_path (no mocked subprocess).
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path, branch: str = "main") -> None:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_git_branch_and_root_real_repo(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver

    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/ONB-1234-fix")
    assert TaskResolver._git_branch(repo) == "feature/ONB-1234-fix"
    assert TaskResolver._git_root(repo) == repo.resolve()


def test_git_value_returns_none_for_non_git_dir(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver

    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    assert TaskResolver._git_branch(not_a_repo) is None
    assert TaskResolver._git_root(not_a_repo) is None


def test_git_value_returns_none_on_subprocess_error(monkeypatch) -> None:
    import subprocess

    from ai_governance.session.resolver import TaskResolver

    def boom(*args, **kwargs):
        raise FileNotFoundError("git binary missing")

    monkeypatch.setattr(subprocess, "run", boom)
    assert TaskResolver._git_value(["git", "--version"]) is None


def test_resolve_from_git_match_and_no_match(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver

    matching = tmp_path / "matching"
    _init_git_repo(matching, branch="feature/ONB-1234-fix")
    assert TaskResolver.resolve_from_git(matching) == "ONB-1234"

    plain = tmp_path / "plain"
    _init_git_repo(plain, branch="chore/cleanup")
    assert TaskResolver.resolve_from_git(plain) is None


def test_resolve_from_context_matches_by_task_id(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    repo = tmp_path / "repo_id"
    _init_git_repo(repo, branch="feat/ONB-1-login")
    tasks = [TaskState(id="ONB-1", title="T")]
    assert TaskResolver.resolve_from_context(tasks, repo) == "ONB-1"


def test_resolve_from_context_matches_by_reference(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    repo = tmp_path / "repo_ref"
    _init_git_repo(repo, branch="feat/ONB-2-thing")
    tasks = [
        TaskState(
            id="custom-id",
            title="T",
            references=[{"kind": "jira", "value": "onb-2"}],
        )
    ]
    assert TaskResolver.resolve_from_context(tasks, repo) == "custom-id"


def test_resolve_from_context_multiple_key_matches_falls_back_to_repo(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    repo = tmp_path / "repo_multi"
    _init_git_repo(repo, branch="feat/ONB-3-x")
    tasks = [
        TaskState(id="ONB-3", title="T1", repos=[{"path": str(repo)}]),
        TaskState(id="dup", title="T2", references=[{"kind": "jira", "value": "ONB-3"}]),
    ]
    assert TaskResolver.resolve_from_context(tasks, repo) == "ONB-3"


def test_resolve_from_context_no_git_root_returns_none(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    plain = tmp_path / "not_a_repo_ctx"
    plain.mkdir()
    tasks = [TaskState(id="X", title="T")]
    assert TaskResolver.resolve_from_context(tasks, plain) is None


def test_resolve_from_context_falls_back_to_repo_path(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    repo = tmp_path / "repo_path_match"
    _init_git_repo(repo, branch="chore/tidy")
    tasks = [TaskState(id="ID-1", title="T", repos=[{"path": str(repo)}])]
    assert TaskResolver.resolve_from_context(tasks, repo) == "ID-1"


def test_resolve_from_context_multiple_repo_matches_returns_none(tmp_path: Path) -> None:
    from ai_governance.session.resolver import TaskResolver
    from ai_governance.session.tracker import TaskState

    repo = tmp_path / "repo_path_dup"
    _init_git_repo(repo, branch="chore/tidy")
    tasks = [
        TaskState(id="A", title="T", repos=[{"path": str(repo)}]),
        TaskState(id="B", title="T", repos=[{"path": str(repo)}]),
    ]
    assert TaskResolver.resolve_from_context(tasks, repo) is None


# ---------------------------------------------------------------------------
# tracker.py — remaining error/edge branches.
# ---------------------------------------------------------------------------


def test_task_state_from_dict_rejects_non_dict() -> None:
    import pytest
    from ai_governance.session.tracker import CorruptTaskError, TaskState

    with pytest.raises(CorruptTaskError):
        TaskState.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_validate_task_id_rejects_invalid_characters(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid characters"):
        tracker._validate_task_id("bad*id")


def test_json_path_reports_symlink_target_when_resolve_result_changes(
    tmp_path: Path, monkeypatch
) -> None:
    # The directory-traversal guard resolves `raw_path` once up front and again
    # inside the symlink-specific check. Under normal conditions both calls
    # return the same value, so we simulate a second, different resolution to
    # exercise the dedicated "Symlink" error message deterministically.
    import pathlib

    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    inside_target = tracker.tasks_dir / "inner.json"
    inside_target.write_text("{}")
    link = tracker.tasks_dir / "evil.json"
    link.symlink_to(inside_target)
    outside = tmp_path / "outside.json"

    real_resolve = pathlib.Path.resolve
    calls = {"n": 0}

    def fake_resolve(self, *args, **kwargs):
        result = real_resolve(self, *args, **kwargs)
        if self == link:
            calls["n"] += 1
            if calls["n"] == 2:
                return outside
        return result

    monkeypatch.setattr(pathlib.Path, "resolve", fake_resolve)
    with pytest.raises(ValueError, match="Symlink"):
        tracker._json_path("evil")


def test_md_path_reports_symlink_target_when_resolve_result_changes(
    tmp_path: Path, monkeypatch
) -> None:
    import pathlib

    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    inside_target = tracker.tasks_dir / "inner.md"
    inside_target.write_text("log")
    link = tracker.tasks_dir / "evil2.md"
    link.symlink_to(inside_target)
    outside = tmp_path / "outside.md"

    real_resolve = pathlib.Path.resolve
    calls = {"n": 0}

    def fake_resolve(self, *args, **kwargs):
        result = real_resolve(self, *args, **kwargs)
        if self == link:
            calls["n"] += 1
            if calls["n"] == 2:
                return outside
        return result

    monkeypatch.setattr(pathlib.Path, "resolve", fake_resolve)
    with pytest.raises(ValueError, match="Symlink"):
        tracker._md_path("evil2")


def test_get_task_raises_oserror_on_unreadable_file(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="P1", title="X"))
    path = tracker._json_path("P1")
    path.chmod(0o000)
    try:
        with pytest.raises(OSError, match="Failed to read task"):
            tracker.get_task("P1")
    finally:
        path.chmod(0o644)


def test_get_task_raises_corrupt_task_error(tmp_path: Path) -> None:
    import pytest
    from ai_governance.session.tracker import CorruptTaskError

    tracker = SessionTracker(root_dir=tmp_path)
    (tracker.tasks_dir / "BAD.json").write_text("not valid json")
    with pytest.raises(CorruptTaskError):
        tracker.get_task("BAD")


def test_mutate_task_missing_raises_oserror(tmp_path: Path) -> None:
    # _read_task_path raises FileNotFoundError, which _mutate_task's broad
    # `except OSError` re-wraps (FileNotFoundError is an OSError subclass).
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    with pytest.raises(OSError, match="Failed to update task"):
        tracker.update_summary("NOPE", "text")


def test_mutate_task_corrupt_raises(tmp_path: Path) -> None:
    import pytest
    from ai_governance.session.tracker import CorruptTaskError

    tracker = SessionTracker(root_dir=tmp_path)
    (tracker.tasks_dir / "CORRUPT.json").write_text("{bad json")
    with pytest.raises(CorruptTaskError):
        tracker.update_summary("CORRUPT", "text")


def test_update_task_not_found_raises(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(id="U1", title="X")
    with pytest.raises(FileNotFoundError):
        tracker.update_task(task)


def test_update_task_success(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(id="U2", title="X")
    tracker.create_task(task)
    task.summary = "updated"
    result = tracker.update_task(task)
    assert result.summary == "updated"


def test_add_step_and_fact_and_note_reject_blank_text(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="E1", title="X"))
    with pytest.raises(ValueError):
        tracker.add_step("E1", "   ")
    with pytest.raises(ValueError):
        tracker.add_fact("E1", "   ")
    with pytest.raises(ValueError):
        tracker.add_note("E1", "   ")


def test_add_link_rejects_blank_title_or_url(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="E2", title="X"))
    with pytest.raises(ValueError):
        tracker.add_link("E2", "", "http://x")
    with pytest.raises(ValueError):
        tracker.add_link("E2", "title", "")


def test_add_reference_rejects_blank_kind_or_value(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="E3", title="X"))
    with pytest.raises(ValueError):
        tracker.add_reference("E3", "", "value")
    with pytest.raises(ValueError):
        tracker.add_reference("E3", "kind", "")


def test_complete_and_remove_step_by_index_and_text(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="S1", title="X"))
    tracker.add_step("S1", "first")
    tracker.add_step("S1", "second")
    tracker.complete_step("S1", 1)
    task = tracker.get_task("S1")
    assert task is not None
    assert task.steps[0]["done"] is True
    tracker.complete_step("S1", "second")
    task = tracker.get_task("S1")
    assert task is not None
    assert task.steps[1]["done"] is True
    tracker.remove_step("S1", 1)
    task = tracker.get_task("S1")
    assert task is not None
    assert len(task.steps) == 1


def test_find_item_not_found_raises(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="S2", title="X"))
    tracker.add_step("S2", "only")
    with pytest.raises(ValueError, match="Item not found"):
        tracker.complete_step("S2", "missing")
    with pytest.raises(ValueError, match="Item not found"):
        tracker.complete_step("S2", 99)


def test_add_repository_partial_fields_and_updates_existing(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="R1", title="X"))
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    tracker.add_repository("R1", repo_path, branch="main")
    task = tracker.get_task("R1")
    assert task is not None
    assert task.repos[0]["branch"] == "main"
    assert "pr" not in task.repos[0]

    tracker.add_repository("R1", repo_path, pr="7")
    task = tracker.get_task("R1")
    assert task is not None
    assert task.repos[0]["pr"] == "7"
    assert task.repos[0]["branch"] == "main"

    tracker.add_repository("R1", repo_path, worktree="wt")
    task = tracker.get_task("R1")
    assert task is not None
    assert task.repos[0]["worktree"] == "wt"
    assert len(task.repos) == 1


def test_remove_repository_not_found_raises(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="R2", title="X"))
    with pytest.raises(ValueError, match="Repository not found"):
        tracker.remove_repository("R2", tmp_path / "nope")


def test_sync_repositories_updates_branch_when_dir_exists(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    repo_dir = tmp_path / "repo_sync"
    repo_dir.mkdir()
    tracker.create_task(TaskState(id="SY1", title="X"))
    tracker.add_repository("SY1", repo_dir)
    tracker.sync_repositories("SY1", lambda p: "new-branch")
    task = tracker.get_task("SY1")
    assert task is not None
    assert task.repos[0]["branch"] == "new-branch"


def test_sync_repositories_skips_missing_dir(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="SY2", title="X"))
    tracker.add_repository("SY2", tmp_path / "missing_repo")
    tracker.sync_repositories("SY2", lambda p: "should-not-be-used")
    task = tracker.get_task("SY2")
    assert task is not None
    assert "branch" not in task.repos[0]


def test_sync_repositories_resolver_returns_none(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    repo_dir = tmp_path / "repo_sync_none"
    repo_dir.mkdir()
    tracker.create_task(TaskState(id="SY3", title="X"))
    tracker.add_repository("SY3", repo_dir)
    tracker.sync_repositories("SY3", lambda p: None)
    task = tracker.get_task("SY3")
    assert task is not None
    assert "branch" not in task.repos[0]


def test_read_log_raises_oserror_on_unreadable_file(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="L1", title="X"))
    tracker.append_log("L1", "content")
    md_path = tracker._md_path("L1")
    md_path.chmod(0o000)
    try:
        with pytest.raises(OSError, match="Failed to read log"):
            tracker.read_log("L1")
    finally:
        md_path.chmod(0o644)


def test_list_tasks_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    import shutil

    tracker = SessionTracker(root_dir=tmp_path)
    shutil.rmtree(tracker.tasks_dir)
    assert tracker.list_tasks() == []


def test_list_tasks_skips_corrupt_entries(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="OK1", title="X"))
    (tracker.tasks_dir / "BAD.json").write_text("not json")
    tasks = tracker.list_tasks()
    assert [t.id for t in tasks] == ["OK1"]


def test_digest_empty_when_no_tasks(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    assert tracker.digest() == "PROGRESS (0 open)"


def test_digest_with_explicit_focus_pending_and_others(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="F1", title="X", summary="s"))
    tracker.add_step("F1", "pending step")
    tracker.create_task(TaskState(id="F2", title="Y"))
    text = tracker.digest(focus_id="F1")
    assert "- F1 [active]: s" in text
    assert "next: pending step" in text
    assert "others: F2" in text


def test_digest_defaults_to_first_task_when_no_focus_given(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="D1", title="X", summary="sum1"))
    text = tracker.digest()
    assert "PROGRESS (1 open)" in text
    assert "D1" in text


def test_digest_focus_no_pending_steps_and_no_others(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="G1", title="X", summary="s"))
    text = tracker.digest(focus_id="G1")
    assert "next:" not in text
    assert "others:" not in text


def test_digest_truncates_when_exceeding_max_chars(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="H1", title="X", summary="s" * 100))
    text = tracker.digest(focus_id="H1", max_chars=20)
    assert text.endswith("…")
    assert len(text) <= 20


def test_import_legacy_directory_imports_with_log_skip_and_invalid(tmp_path: Path) -> None:
    import json

    tracker = SessionTracker(root_dir=tmp_path / "progress")
    legacy_root = tmp_path / "legacy"
    tasks_dir = legacy_root / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "LEG-1.json").write_text(json.dumps({"id": "LEG-1", "title": "Legacy"}))
    (tasks_dir / "LEG-1.md").write_text("Old log body")
    (tasks_dir / "BAD.json").write_text("not json")

    report = tracker.import_legacy_directory(legacy_root)
    assert report["imported"] == 1
    assert report["invalid"] == 1
    task = tracker.get_task("LEG-1")
    assert task is not None
    log = tracker.read_log("LEG-1")
    assert "Old log body" in log

    report2 = tracker.import_legacy_directory(legacy_root)
    assert report2["skipped"] == 1


def test_import_legacy_directory_missing_sources_is_noop(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path / "progress")
    report = tracker.import_legacy_directory(tmp_path / "nonexistent")
    assert report == {"imported": 0, "skipped": 0, "invalid": 0}


def test_task_lock_and_log_operations_without_fcntl(tmp_path: Path, monkeypatch) -> None:
    from ai_governance.session import tracker as tracker_module

    monkeypatch.setattr(tracker_module, "fcntl", None)
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="NF1", title="X"))
    tracker.append_log("NF1", "no-lock entry")
    log = tracker.read_log("NF1")
    assert "no-lock entry" in log


def test_module_sets_fcntl_none_when_import_fails(monkeypatch) -> None:
    import importlib
    import sys

    mod_name = "ai_governance.session.tracker"
    original_module = sys.modules.get(mod_name)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    try:
        sys.modules.pop(mod_name, None)
        reloaded = importlib.import_module(mod_name)
        assert reloaded.fcntl is None
    finally:
        sys.modules.pop(mod_name, None)
        if original_module is not None:
            sys.modules[mod_name] = original_module
        else:
            importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# cli.py — show_task rendering and main() dispatch branches.
# ---------------------------------------------------------------------------


def test_show_task_agent_mode_full(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "1")
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(
        id="T1",
        title="Title",
        status="active",
        summary="Sum",
        steps=[{"text": "s1", "done": True}],
        facts=[{"text": "f1"}],
        repos=[{"path": "/p", "branch": "main"}],
        links=[{"title": "l1", "url": "http://x"}],
        references=[{"kind": "jira", "value": "T-1"}],
    )
    tracker.create_task(task)
    tracker.append_log("T1", "log body")
    cli.show_task(task, full_log=True, tracker=tracker)
    out = capsys.readouterr().out
    assert "Steps" in out
    assert "Facts" in out
    assert "Repositories" in out
    assert "Links" in out
    assert "References" in out
    assert "Complete Log:" in out
    assert "log body" in out


def test_show_task_agent_mode_minimal_no_log(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "1")
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(id="T2", title="Title2")
    tracker.create_task(task)
    cli.show_task(task, full_log=True, tracker=tracker)
    out = capsys.readouterr().out
    assert "Steps" not in out
    assert "Complete Log:" not in out


def test_show_task_tty_mode_full(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "0")
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(
        id="T3",
        title="Title3",
        status="active",
        summary="",
        steps=[{"text": "s1", "done": False}],
        facts=[{"text": "f1"}],
        repos=[{"path": "/p"}],
        links=[{"title": "l", "url": "u"}],
        references=[{"kind": "k", "value": "v"}],
    )
    tracker.create_task(task)
    tracker.append_log("T3", "table log body")
    cli.show_task(task, full_log=True, tracker=tracker)
    out = capsys.readouterr().out
    assert "T3" in out
    assert "table log body" in out


def test_show_task_tty_mode_minimal(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "0")
    task = TaskState(id="T4", title="Title4")
    cli.show_task(task, full_log=False, tracker=None)
    out = capsys.readouterr().out
    assert "T4" in out


def test_cli_show_json_full_includes_log(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    assert cli.main(["new", "T10", "--title", "Hello"]) == 0
    capsys.readouterr()
    assert cli.main(["note", "T10", "some note"]) == 0
    capsys.readouterr()
    rc = cli.main(["show", "T10", "--json", "--full"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "log" in data
    assert "some note" in data["log"]


def test_cli_reopen_task(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T11", "--title", "H"])
    cli.main(["close", "T11"])
    capsys.readouterr()
    rc = cli.main(["reopen", "T11", "--reason", "back"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "T11" in out


def test_cli_resume_without_target_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["resume"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No task matches" in err


def test_cli_reference_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T12", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["reference", "T12", "jira", "T12", "--url", "http://x"])
    assert rc == 0


def test_cli_repo_add_and_remove(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T13", "--title", "H"])
    capsys.readouterr()
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    rc = cli.main(
        ["repo", "T13", "add", str(repo_dir), "--branch", "main", "--pr", "1", "--worktree", "wt"]
    )
    assert rc == 0
    capsys.readouterr()
    rc2 = cli.main(["repo", "T13", "remove", str(repo_dir)])
    assert rc2 == 0


def test_cli_sync_specific_task(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T14", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["sync", "T14"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Synced 1 task" in out


def test_cli_sync_all_tasks(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T15", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["sync"])
    assert rc == 0


def test_cli_note_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T16", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["note", "T16", "note text"])
    assert rc == 0


def test_cli_digest_json_and_text(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "T17", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["digest", "--id", "T17", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "digest" in data
    rc2 = cli.main(["digest"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "PROGRESS" in out2


def test_cli_migrate_legacy_json(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    legacy = tmp_path / "legacy"
    tasks_dir = legacy / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "OLD-1.json").write_text(json.dumps({"id": "OLD-1", "title": "Old"}))
    rc = cli.main(["migrate-legacy", str(legacy), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["imported"] == 1


def test_cli_migrate_legacy_text(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    legacy = tmp_path / "legacy2"
    tasks_dir = legacy / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "OLD-2.json").write_text(json.dumps({"id": "OLD-2", "title": "Old"}))
    rc = cli.main(["migrate-legacy", str(legacy)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Imported 1" in out


def test_cli_unknown_cmd_falls_through_to_help(monkeypatch, tmp_path: Path, capsys) -> None:
    import argparse

    from ai_governance.session import cli

    class FakeParser:
        def parse_args(self, argv):
            return argparse.Namespace(cmd="mystery")

        def print_help(self):
            print("HELP TEXT")

    monkeypatch.setattr(cli, "_build_parser", lambda: FakeParser())
    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    rc = cli.main([])
    assert rc == 0
    assert "HELP TEXT" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Additional tracker.py branches: id validation, atomic write, legacy dirs,
# init errors, compact limits eviction, duplicate creation, and CRUD verbs.
# ---------------------------------------------------------------------------


def test_validate_task_id_rejects_leading_dot(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    with pytest.raises(ValueError, match="cannot start with a dot"):
        tracker._validate_task_id(".hidden")


def test_atomic_write_text_reraises_when_tempfile_creation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    import tempfile

    import pytest
    from ai_governance.session.tracker import _atomic_write_text

    def boom(*args, **kwargs):
        raise OSError("no space left")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", boom)
    with pytest.raises(OSError, match="no space left"):
        _atomic_write_text(tmp_path / "out.json", "content")


def test_session_tracker_uses_legacy_tareas_dir(tmp_path: Path) -> None:
    root = tmp_path / "root_tareas"
    (root / "tareas").mkdir(parents=True)
    tracker = SessionTracker(root_dir=root)
    assert tracker.tasks_dir == root / "tareas"


def test_session_tracker_uses_legacy_archivadas_dir(tmp_path: Path) -> None:
    root = tmp_path / "root_archivadas"
    (root / "archivadas").mkdir(parents=True)
    tracker = SessionTracker(root_dir=root)
    assert tracker.archive_dir == root / "archivadas"


def test_session_tracker_init_raises_oserror_when_dir_creation_fails(tmp_path: Path) -> None:
    import pytest

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(OSError, match="inaccessible or cannot be created"):
        SessionTracker(root_dir=blocker)


def test_session_tracker_custom_compact_limits_archives_overflow(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path, compact_limits={"steps": 1})
    assert tracker.compact_limits["steps"] == 1
    tracker.create_task(TaskState(id="CL1", title="X"))
    tracker.add_step("CL1", "one")
    tracker.add_step("CL1", "two")
    task = tracker.get_task("CL1")
    assert task is not None
    assert len(task.steps) == 1
    assert task.steps[0]["text"] == "two"
    log = tracker.read_log("CL1")
    assert "Archived steps: one" in log


def test_json_and_md_path_allow_symlink_pointing_inside_tasks_dir(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    inside_json = tracker.tasks_dir / "inner_ok.json"
    inside_json.write_text("{}")
    json_link = tracker.tasks_dir / "ok.json"
    json_link.symlink_to(inside_json)
    assert tracker._json_path("ok") == json_link

    inside_md = tracker.tasks_dir / "inner_ok.md"
    inside_md.write_text("log")
    md_link = tracker.tasks_dir / "ok.md"
    md_link.symlink_to(inside_md)
    assert tracker._md_path("ok") == md_link


def test_create_task_raises_when_already_exists(tmp_path: Path) -> None:
    import pytest

    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="DUP", title="X"))
    with pytest.raises(FileExistsError):
        tracker.create_task(TaskState(id="DUP", title="Y"))


def test_add_fact_and_add_link_success_paths(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="AF1", title="X"))
    task = tracker.add_fact("AF1", "some fact")
    assert task.facts[0]["text"] == "some fact"
    task = tracker.add_link("AF1", "title", "http://x")
    assert task.links[0]["url"] == "http://x"


def test_pause_and_resume_task(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="PZ1", title="X"))
    task = tracker.pause_task("PZ1", "waiting")
    assert task.status == "paused"
    task = tracker.resume_task("PZ1")
    assert task.status == "active"


def test_resume_task_noop_when_not_paused(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="PZ2", title="X"))
    task = tracker.resume_task("PZ2")
    assert task.status == "active"


def test_list_tasks_excludes_closed_by_default(tmp_path: Path) -> None:
    tracker = SessionTracker(root_dir=tmp_path)
    tracker.create_task(TaskState(id="LC1", title="X"))
    tracker.create_task(TaskState(id="LC2", title="Y"))
    tracker.close_task("LC2")
    active = tracker.list_tasks()
    assert [t.id for t in active] == ["LC1"]
    all_tasks = tracker.list_tasks(include_closed=True)
    assert {t.id for t in all_tasks} == {"LC1", "LC2"}


# ---------------------------------------------------------------------------
# Additional cli.py branches: show_task no-full-log paths and full main()
# subcommand dispatch coverage (list, here, show variants, pause, resume,
# summary, step, fact, link).
# ---------------------------------------------------------------------------


def test_show_task_agent_mode_no_full_log(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "1")
    task = TaskState(id="T5", title="T5")
    cli.show_task(task, full_log=False, tracker=None)
    out = capsys.readouterr().out
    assert "T5" in out


def test_show_task_tty_mode_full_log_empty(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_AGENT", "0")
    tracker = SessionTracker(root_dir=tmp_path)
    task = TaskState(id="T6", title="T6")
    tracker.create_task(task)
    cli.show_task(task, full_log=True, tracker=tracker)
    out = capsys.readouterr().out
    assert "T6" in out
    assert "Complete Log" not in out


def test_cli_main_list_default_and_json(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "L1", "--title", "One"])
    capsys.readouterr()
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "L1" in out

    rc2 = cli.main(["list", "--all", "--json"])
    assert rc2 == 0
    data = json.loads(capsys.readouterr().out)
    assert any(t["id"] == "L1" for t in data)


def test_cli_main_no_cmd_defaults_to_list(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    rc = cli.main([])
    assert rc == 0


def test_cli_here_command_resolves_task(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    progress_dir = tmp_path / "progress"
    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(progress_dir))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    repo = tmp_path / "repo_here"
    _init_git_repo(repo, branch="chore/plain")
    cli.main(["new", "HERE1", "--title", "H"])
    capsys.readouterr()
    cli.main(["repo", "HERE1", "add", str(repo)])
    capsys.readouterr()
    monkeypatch.chdir(repo)
    rc = cli.main(["here"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "HERE1" in out


def test_cli_show_missing_task_raises(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    rc = cli.main(["show", "NOPE"])
    assert rc == 1


def test_cli_show_json_without_full(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "SJ1", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["show", "SJ1", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "log" not in data


def test_cli_show_non_json(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "SN1", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["show", "SN1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SN1" in out


def test_cli_pause_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "PZ", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["pause", "PZ", "--reason", "later"])
    assert rc == 0


def test_cli_resume_with_explicit_task_id(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "RS1", "--title", "H"])
    capsys.readouterr()
    cli.main(["pause", "RS1"])
    capsys.readouterr()
    rc = cli.main(["resume", "RS1"])
    assert rc == 0


def test_cli_summary_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "SM1", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["summary", "SM1", "New summary text"])
    assert rc == 0


def test_cli_step_command_add_done_remove(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "STP1", "--title", "H"])
    capsys.readouterr()
    assert cli.main(["step", "STP1", "add", "first step"]) == 0
    capsys.readouterr()
    assert cli.main(["step", "STP1", "done", "1"]) == 0
    capsys.readouterr()
    assert cli.main(["step", "STP1", "remove", "1"]) == 0


def test_cli_fact_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "FC1", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["fact", "FC1", "verified fact"])
    assert rc == 0


def test_cli_link_command(monkeypatch, tmp_path: Path, capsys) -> None:
    from ai_governance.session import cli

    monkeypatch.setenv("SPECOPS_PROGRESS_DIR", str(tmp_path))
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    cli.main(["new", "LK1", "--title", "H"])
    capsys.readouterr()
    rc = cli.main(["link", "LK1", "Docs", "http://example.com"])
    assert rc == 0
