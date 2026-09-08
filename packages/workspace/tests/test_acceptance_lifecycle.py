"""
test_acceptance_lifecycle.py — Acceptance tests for workspace lifecycle contracts W01–W08.

Contracts from 02-CONTRATOS-DE-TEST.md:
- W01 (test_delete_rejects_escape_and_unowned): Deleting a workspace rejects paths outside
      workspaces_dir (e.g. ../../, absolute paths outside, symlinks pointing outside) and
      unowned directories without deleting foreign files.
- W02 (test_dirty_workspace_is_preserved): If a workspace repo has uncommitted/untracked changes,
      delete does NOT silently force delete with rmtree. It must preserve dirty repos or require
      explicit unforced confirmation.
- W03 (test_failed_delete_never_reports_success): If a git or filesystem error occurs during
      deletion, it must NOT report success and must surface the failure.
- W04 (test_clean_owned_workspace_lifecycle): Clean create -> use -> stop -> delete lifecycle
      of owned workspaces cleanly cleans up Git worktrees and files.
- W05 (test_pid_reuse_does_not_signal_foreign_process): stop_workspace verifies process identity
      (e.g. checks command line/process creation time or process attributes) before sending
      SIGTERM/SIGKILL so a reused PID belonging to an unrelated system process is NEVER signaled.
- W06 (test_owned_process_stop_is_bounded): Stopping an owned process waits with bounded timeout
      and reports clean shutdown.
- W07 (test_workspace_needs_no_spec_or_governance): Workspace lifecycle functions standalone
      without importing spec or ai_governance.
- W08 (test_reset_keeps_two_archives): Verifies that resetting/rotating preserves previous
      archives intact.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from workspace_engine.cli.clean_workspace import clean_workspace
from workspace_engine.cli.delete_workspaces import delete_single_workspace, delete_workspaces
from workspace_engine.cli.reset_repos import reset_repositories
from workspace_engine.cli.stop_workspace import stop_workspace
from workspace_engine.utils import run_git


def _init_test_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    clean_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    clean_env["GIT_AUTHOR_NAME"] = "Test User"
    clean_env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    clean_env["GIT_COMMITTER_NAME"] = "Test User"
    clean_env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    subprocess.run(
        ["git", "-C", str(path), "init", "-b", "main"],
        check=True,
        capture_output=True,
        env=clean_env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
        env=clean_env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        env=clean_env,
    )


def test_delete_rejects_escape_and_unowned(tmp_path: Path) -> None:
    """W01: Deleting a workspace rejects paths outside workspaces_dir (../../, absolute

    paths outside, symlinks pointing outside) and unowned directories without deleting foreign files.
    """
    workspaces_dir = tmp_path / "managed_workspaces"
    workspaces_dir.mkdir(parents=True)

    outside_dir = tmp_path / "outside_directory"
    outside_dir.mkdir(parents=True)
    sentinel_outside = outside_dir / "confidential_sentinel.txt"
    sentinel_outside.write_text("SENSITIVE_OUTSIDE_DATA", encoding="utf-8")

    # Variant A: Traversal attempt using '../../'
    escape_relative = workspaces_dir / ".." / "outside_directory"
    with pytest.raises(ValueError, match="escapes managed workspaces directory|outside"):
        delete_single_workspace(escape_relative, workspaces_dir=workspaces_dir)

    assert sentinel_outside.exists()
    assert sentinel_outside.read_text(encoding="utf-8") == "SENSITIVE_OUTSIDE_DATA"

    # Variant B: Absolute path outside workspaces_dir
    with pytest.raises(ValueError, match="escapes managed workspaces directory|outside"):
        delete_single_workspace(outside_dir, workspaces_dir=workspaces_dir)

    assert sentinel_outside.exists()
    assert sentinel_outside.read_text(encoding="utf-8") == "SENSITIVE_OUTSIDE_DATA"

    # Variant C: Symlink inside workspaces_dir pointing outside
    symlink_ws = workspaces_dir / "symlinked_ws"
    symlink_ws.symlink_to(outside_dir)
    with pytest.raises(ValueError, match="escapes managed workspaces directory|outside"):
        delete_single_workspace(symlink_ws, workspaces_dir=workspaces_dir)

    assert sentinel_outside.exists()
    assert sentinel_outside.read_text(encoding="utf-8") == "SENSITIVE_OUTSIDE_DATA"
    assert outside_dir.exists()

    # Variant D: Unowned directory inside workspaces_dir (missing ownership marker)
    unowned_dir = workspaces_dir / "unowned_project"
    unowned_dir.mkdir()
    unowned_sentinel = unowned_dir / "foreign_code.txt"
    unowned_sentinel.write_text("FOREIGN_PROPRIETARY_WORK", encoding="utf-8")

    with pytest.raises(ValueError, match="not an owned workspace|ownership marker"):
        delete_single_workspace(unowned_dir, workspaces_dir=workspaces_dir)

    # Foreign files inside unowned dir must remain 100% intact
    assert unowned_dir.exists()
    assert unowned_sentinel.exists()
    assert unowned_sentinel.read_text(encoding="utf-8") == "FOREIGN_PROPRIETARY_WORK"


def test_dirty_workspace_is_preserved(tmp_path: Path) -> None:
    """W02: If a workspace repo has uncommitted/untracked changes, delete does NOT

    silently force delete with rmtree. It must preserve dirty repos or require explicit
    unforced confirmation.
    """
    workspaces_dir = tmp_path / "workspaces"
    ws_dir = workspaces_dir / "dirty_ws"
    ws_dir.mkdir(parents=True)
    (ws_dir / ".workspace_metadata").write_text('{"id": "dirty_ws"}', encoding="utf-8")

    repos_dir = ws_dir / "repositories"
    repo_dir = repos_dir / "my_repo"
    _init_test_git_repo(repo_dir)

    tracked_file = repo_dir / "tracked.txt"
    tracked_file.write_text("initial version\n", encoding="utf-8")
    run_git(repo_dir, "add", "tracked.txt")
    run_git(repo_dir, "commit", "-m", "initial commit")

    # 1. Modify tracked file (uncommitted modification)
    tracked_file.write_text("modified uncommitted dirty work\n", encoding="utf-8")

    # Calling delete without force must fail and NOT delete the workspace
    result = delete_single_workspace(ws_dir, force=False, workspaces_dir=workspaces_dir)
    assert result is False
    assert ws_dir.exists()
    assert tracked_file.exists()
    assert tracked_file.read_text(encoding="utf-8") == "modified uncommitted dirty work\n"

    # 2. Add untracked file
    run_git(repo_dir, "checkout", "--", "tracked.txt")
    untracked_file = repo_dir / "untracked_scratch.py"
    untracked_file.write_text("print('valuable uncommitted scratch')", encoding="utf-8")

    result2 = delete_single_workspace(ws_dir, force=False, workspaces_dir=workspaces_dir)
    assert result2 is False
    assert ws_dir.exists()
    assert untracked_file.exists()
    assert untracked_file.read_text(encoding="utf-8") == "print('valuable uncommitted scratch')"

    # 3. Explicit force=True allows deletion
    result_forced = delete_single_workspace(ws_dir, force=True, workspaces_dir=workspaces_dir)
    assert result_forced is True
    assert not ws_dir.exists()


def test_failed_delete_never_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """W03: If a git or filesystem error occurs during deletion, it must NOT report

    success and must surface the failure.
    """
    workspaces_dir = tmp_path / "workspaces"
    ws_dir = workspaces_dir / "failing_ws"
    ws_dir.mkdir(parents=True)
    (ws_dir / ".workspace_metadata").write_text('{"id": "failing_ws"}', encoding="utf-8")
    (ws_dir / "file.txt").write_text("data", encoding="utf-8")

    # Case A: Filesystem error in rmtree
    def failing_rmtree(path, *args, **kwargs):
        raise PermissionError(f"Simulated permission denied for {path}")

    monkeypatch.setattr("shutil.rmtree", failing_rmtree)

    res = delete_single_workspace(ws_dir, force=True, workspaces_dir=workspaces_dir)
    assert res is False, "delete_single_workspace must return False on rmtree error"

    out = capsys.readouterr().out
    assert "eliminado" not in out.lower() or "error" in out.lower()
    assert ws_dir.exists(), "Resource must remain visible when deletion fails"

    # Calling CLI delete_workspaces must return non-zero exit code
    exit_code = delete_workspaces(["failing_ws"], force=True, workspaces_dir=workspaces_dir)
    assert exit_code != 0

    # Case B: Git worktree remove failure
    monkeypatch.undo()
    main_repo = tmp_path / "main_repo_fail"
    _init_test_git_repo(main_repo)
    (main_repo / "init.txt").write_text("main", encoding="utf-8")
    run_git(main_repo, "add", ".")
    run_git(main_repo, "commit", "-m", "init")

    repos_dir = ws_dir / "repositories"
    repos_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = repos_dir / "git_repo"
    run_git(main_repo, "worktree", "add", "-b", "failing-branch", str(repo_dir))

    def failing_git(repo_path, *args, **kwargs):
        if "remove" in args:
            mock = MagicMock()
            mock.returncode = 1
            mock.stdout = ""
            mock.stderr = "fatal: failed to remove worktree: lock active"
            return mock
        return run_git(repo_path, *args)

    monkeypatch.setattr("workspace_engine.cli.delete_workspaces._git", failing_git)
    res_git_err = delete_single_workspace(ws_dir, force=True, workspaces_dir=workspaces_dir)
    assert res_git_err is False
    assert ws_dir.exists()


def test_clean_owned_workspace_lifecycle(tmp_path: Path) -> None:
    """W04: Clean create -> use -> stop -> delete lifecycle of owned workspaces

    cleanly cleans up Git worktrees and files.
    """
    # 1. Main project repository
    main_repo = tmp_path / "repos" / "app_main"
    _init_test_git_repo(main_repo)
    (main_repo / "main.py").write_text("print('app main')", encoding="utf-8")
    run_git(main_repo, "add", ".")
    run_git(main_repo, "commit", "-m", "initial commit")

    workspaces_dir = tmp_path / "workspaces"
    workspaces_dir.mkdir(parents=True)

    # 2. Create owned workspace with worktree
    ws_dir = workspaces_dir / "feature-ws"
    ws_repos_dir = ws_dir / "repositories"
    ws_repos_dir.mkdir(parents=True)
    ws_worktree = ws_repos_dir / "app_main"

    add_res = run_git(main_repo, "worktree", "add", "-b", "feat-branch", str(ws_worktree))
    assert add_res.returncode == 0
    (ws_dir / ".workspace_metadata").write_text('{"name": "feature-ws"}', encoding="utf-8")

    # Verify worktree registered in main repo
    wt_list_before = run_git(main_repo, "worktree", "list")
    assert str(ws_worktree) in wt_list_before.stdout

    # 3. Use workspace (make clean commit in worktree)
    (ws_worktree / "feature.py").write_text("# new feature", encoding="utf-8")
    run_git(ws_worktree, "add", ".")
    run_git(ws_worktree, "commit", "-m", "add feature")
    assert run_git(ws_worktree, "status", "--porcelain").stdout.strip() == ""

    # 4. Stop workspace
    stop_rc = stop_workspace(ws_dir)
    assert stop_rc == 0

    # 5. Delete workspace
    del_ok = delete_single_workspace(ws_dir, force=False, workspaces_dir=workspaces_dir)
    assert del_ok is True
    assert not ws_dir.exists()

    # Verify worktree cleanly deregistered in main repo
    wt_list_after = run_git(main_repo, "worktree", "list")
    assert str(ws_worktree) not in wt_list_after.stdout
    assert (main_repo / "main.py").exists()


def test_pid_reuse_does_not_signal_foreign_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W05: stop_workspace verifies process identity before sending SIGTERM/SIGKILL

    so a reused PID belonging to an unrelated system process is NEVER signaled.
    """
    ws_dir = tmp_path / "ws_pid_reuse"
    pids_dir = ws_dir / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)

    foreign_pid = 54321
    pid_file = pids_dir / "payment-service.pid"
    # Recorded PID file
    pid_file.write_text(f"{foreign_pid}\n", encoding="utf-8")

    signals_sent = []

    def mock_kill(pid, sig):
        if sig == 0:
            return  # alive check
        signals_sent.append((pid, sig))

    def mock_killpg(pgid, sig):
        signals_sent.append((pgid, sig))

    monkeypatch.setattr("os.kill", mock_kill)
    monkeypatch.setattr("os.killpg", mock_killpg)
    monkeypatch.setattr("os.getpgid", lambda p: p)

    # Process identity reports an unrelated system process
    def mock_cmdline(pid):
        return "/usr/sbin/cron -f"

    monkeypatch.setattr(
        "workspace_engine.cli.stop_workspace.get_process_cmdline",
        mock_cmdline,
    )

    stop_workspace(ws_dir)

    # CRITICAL ORACLE: No signal (SIGTERM, SIGKILL, etc.) was sent to the foreign process!
    assert len(signals_sent) == 0, f"Foreign process was signaled: {signals_sent}"
    # Stale pid file was safely cleaned up
    assert not pid_file.exists()


def test_pid_reuse_rejects_matching_name_in_foreign_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W05: stop_workspace rechaza procesos cuyo nombre de servicio coincide pero pertenecen a otro workspace

    (e.g. buscando en ws_a/api contra node /workspaces/proyecto-b/api/server.js).
    """
    ws_dir = tmp_path / "ws_pid_reuse_ws_a"
    pids_dir = ws_dir / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)

    foreign_pid = 54322
    pid_file = pids_dir / "api.pid"
    pid_file.write_text(f"{foreign_pid}\n", encoding="utf-8")

    signals_sent = []

    def mock_kill(pid, sig):
        if sig == 0:
            return  # alive check
        signals_sent.append((pid, sig))

    def mock_killpg(pgid, sig):
        signals_sent.append((pgid, sig))

    monkeypatch.setattr("os.kill", mock_kill)
    monkeypatch.setattr("os.killpg", mock_killpg)
    monkeypatch.setattr("os.getpgid", lambda p: p)

    # El cmdline pertenece a otro workspace (proyecto-b)
    monkeypatch.setattr(
        "workspace_engine.cli.stop_workspace.get_process_cmdline",
        lambda pid: "node /workspaces/proyecto-b/api/server.js",
    )

    stop_workspace(ws_dir)

    # ORÁCULO CRÍTICO: No se envía ninguna señal al proceso del workspace ajeno
    assert len(signals_sent) == 0, f"Foreign workspace process was signaled: {signals_sent}"
    assert not pid_file.exists()


def test_owned_process_stop_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """W06: Stopping an owned process waits with bounded timeout and reports clean shutdown."""
    ws_dir = tmp_path / "ws_proc_stop"
    pids_dir = ws_dir / ".ai-toolkit" / "run-pids"
    pids_dir.mkdir(parents=True)

    # Spawn an owned local process
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        cmd_str = f"{sys.executable} -c import time; time.sleep(60)"
        pid_file = pids_dir / "test-service.pid"
        # Store metadata with repo name and PID
        pid_file.write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "repo": "test-service",
                    "cmdline": cmd_str,
                }
            ),
            encoding="utf-8",
        )

        # In sandboxed environments where macOS seatbelt blocks 'ps', provide cmdline via monkeypatch
        from workspace_engine.utils import get_process_cmdline

        if not get_process_cmdline(proc.pid):
            monkeypatch.setattr(
                "workspace_engine.cli.stop_workspace.get_process_cmdline",
                lambda p: cmd_str if p == proc.pid else "",
            )

        # Stop workspace with bounded timeout
        rc = stop_workspace(ws_dir, timeout=3.0)
        assert rc == 0

        # Process must be terminated
        proc.wait(timeout=2.0)
        assert proc.poll() is not None
        assert not pid_file.exists()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_workspace_needs_no_spec_or_governance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W07: Workspace lifecycle functions standalone without importing spec or ai_governance."""
    # Block siblings in sys.modules
    monkeypatch.setitem(sys.modules, "spec", None)
    monkeypatch.setitem(sys.modules, "ai_governance", None)

    # Verify lifecycle runs cleanly
    ws_dir = tmp_path / "standalone_ws"
    ws_dir.mkdir(parents=True)
    (ws_dir / ".workspace_metadata").write_text('{"name": "standalone"}', encoding="utf-8")

    assert clean_workspace(ws_dir) == 0
    assert stop_workspace(ws_dir) == 0
    assert delete_single_workspace(ws_dir, workspaces_dir=tmp_path) is True

    # Scan all Python files in workspace_engine to assert no import of spec or ai_governance
    pkg_src = Path(__file__).parent.parent / "src" / "workspace_engine"
    for py_file in pkg_src.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("spec"), f"{py_file} imports {alias.name}"
                    assert not alias.name.startswith("ai_governance"), (
                        f"{py_file} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("spec"), f"{py_file} imports from {node.module}"
                assert not node.module.startswith("ai_governance"), (
                    f"{py_file} imports from {node.module}"
                )


def test_reset_keeps_two_archives(tmp_path: Path) -> None:
    """W08: Verifies that resetting/rotating preserves previous archives intact

    and leaves the third working copy pristine.
    """
    ws_dir = tmp_path / "ws_archives"
    ws_dir.mkdir(parents=True)
    (ws_dir / ".workspace_metadata").write_text('{"name": "ws_archives"}', encoding="utf-8")

    repos_dir = ws_dir / "repositories"
    repo_dir = repos_dir / "service_core"
    _init_test_git_repo(repo_dir)

    base_file = repo_dir / "core.py"
    base_file.write_text("PRISTINE_BASE_CODE_V1 = True\n", encoding="utf-8")
    run_git(repo_dir, "add", "core.py")
    run_git(repo_dir, "commit", "-m", "v1 pristine base")

    # Run 1 produces Archive 1
    archives_dir = ws_dir / "archives"
    archives_dir.mkdir()
    archive1 = archives_dir / "run_1_archive.tar"
    archive1_bytes = b"ARCHIVE_1_IMMUTABLE_EVIDENCE_RUN_101"
    archive1.write_bytes(archive1_bytes)

    # Run 2 produces Archive 2
    archive2 = archives_dir / "run_2_archive.tar"
    archive2_bytes = b"ARCHIVE_2_IMMUTABLE_EVIDENCE_RUN_102"
    archive2.write_bytes(archive2_bytes)

    # Run 3 makes active modifications to the repository fixture
    base_file.write_text("DIRTY_MUTATED_CORE_DURING_RUN_3 = True\n", encoding="utf-8")
    scratch_file = repo_dir / "scratch_untracked.log"
    scratch_file.write_text("untracked scratch log", encoding="utf-8")

    # Reset repository fixture to pristine base
    rc = reset_repositories(force=True, start_dir=ws_dir)
    assert rc == 0
    clean_workspace(ws_dir)

    # ORACLE:
    # 1. Both archives remain 100% intact with matching bytes
    assert archive1.exists()
    assert archive1.read_bytes() == archive1_bytes
    assert archive2.exists()
    assert archive2.read_bytes() == archive2_bytes

    # 2. Tracked repo fixture is restored to pristine base
    assert base_file.read_text(encoding="utf-8") == "PRISTINE_BASE_CODE_V1 = True\n"
    diff_out = run_git(repo_dir, "diff").stdout.strip()
    assert diff_out == "", f"Repo is not pristine: {diff_out}"
