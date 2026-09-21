"""
Unit tests for workspace_engine.cli.create_worktree.

Uses real `git init` repositories under tmp_path so the actual `git worktree add`
plumbing is exercised without touching the developer's machine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from workspace_engine.cli import create_worktree


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)
    return path


def test_create_worktree_creates_new_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    result = create_worktree.create_worktree("feature-x", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-feature-x").is_dir()
    assert (tmp_path / "workspace-feature-x" / "README.md").is_file()


def test_create_worktree_sanitizes_branch_with_slash(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    result = create_worktree.create_worktree("feat/y", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-feat-y").is_dir()


def test_create_worktree_uses_explicit_target_dir(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    target = tmp_path / "custom-target"

    result = create_worktree.create_worktree("feature-z", start_dir=repo, target_dir=target)

    assert result == 0
    assert target.is_dir()
    assert not (tmp_path / "workspace-feature-z").exists()


def test_create_worktree_existing_local_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "branch", "existing-branch"], cwd=repo, check=True)

    result = create_worktree.create_worktree("existing-branch", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-existing-branch").is_dir()


def test_create_worktree_uses_explicit_from_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "checkout", "-q", "-b", "other"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

    result = create_worktree.create_worktree("feature-w", from_branch="other", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-feature-w").is_dir()


def test_create_worktree_tracks_remote_only_branch(tmp_path: Path) -> None:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "remote-only"], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "remote-only"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-D", "remote-only"], cwd=repo, check=True)

    result = create_worktree.create_worktree("remote-only", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-remote-only").is_dir()


def test_create_worktree_target_dir_already_exists(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    existing = tmp_path / "workspace-dup"
    existing.mkdir()

    result = create_worktree.create_worktree("dup", start_dir=repo)

    assert result == 1


def test_create_worktree_failure_is_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")

    def fake_run_cmd(cmd: list[str]) -> tuple[int, str, str]:
        if "worktree" in cmd and "add" in cmd:
            return 1, "", "boom"
        return 0, "", ""

    monkeypatch.setattr(create_worktree, "_run_cmd", fake_run_cmd)

    result = create_worktree.create_worktree("broken", start_dir=repo)

    assert result == 1


def test_create_worktree_copies_config_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "config").mkdir()
    (repo / "config" / ".env").write_text("A=1\n", encoding="utf-8")
    (repo / "memory").mkdir()
    (repo / "memory" / "notes.md").write_text("note\n", encoding="utf-8")

    result = create_worktree.create_worktree("feature-cfg", start_dir=repo)

    assert result == 0
    worktree_dir = tmp_path / "workspace-feature-cfg"
    assert (worktree_dir / "config" / ".env").read_text(encoding="utf-8") == "A=1\n"
    assert (worktree_dir / "memory" / "notes.md").is_file()


def test_create_worktree_updates_protected_base_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    # "main" triggers the `git pull origin main` path; with no remote configured
    # the pull fails but is not fatal, and the worktree is still created.
    result = create_worktree.create_worktree("feature-pull", start_dir=repo)

    assert result == 0
    assert (tmp_path / "workspace-feature-pull").is_dir()


def test_main_documented_form_repo_target_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    target = tmp_path / "explicit-target"

    with pytest.raises(SystemExit) as exc:
        create_worktree.main([str(repo), str(target), "feature-cli"])

    assert exc.value.code == 0
    assert target.is_dir()


def test_main_legacy_branch_only_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit) as exc:
        create_worktree.main(["legacy-branch"])

    assert exc.value.code == 0
    assert (tmp_path / "workspace-legacy-branch").is_dir()


def test_main_uses_sys_argv_when_no_argv_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.argv", ["ws-worktree", "argv-branch"])

    with pytest.raises(SystemExit) as exc:
        create_worktree.main()

    assert exc.value.code == 0
    assert (tmp_path / "workspace-argv-branch").is_dir()
