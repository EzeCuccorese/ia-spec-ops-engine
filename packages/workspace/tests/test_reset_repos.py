"""
Unit tests for workspace_engine.cli.reset_repos.

Filesystem effects use tmp_path; git calls and confirmation prompts are
mocked so no real subprocess or terminal interaction happens.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.cli import reset_repos as rr


def _git_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    res = MagicMock()
    res.returncode = returncode
    res.stdout = stdout
    res.stderr = stderr
    return res


# ---------------------------------------------------------------------------
# _parent_branch
# ---------------------------------------------------------------------------


def test_parent_branch_no_manifest(tmp_path: Path) -> None:
    assert rr._parent_branch(tmp_path, "repo-a") is None


def test_parent_branch_matches_repo(tmp_path: Path) -> None:
    manifest_dir = tmp_path / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text(
        json.dumps({"repositories": [{"name": "repo-a", "parent_branch": "develop"}]})
    )
    assert rr._parent_branch(tmp_path, "repo-a") == "develop"


def test_parent_branch_no_match(tmp_path: Path) -> None:
    manifest_dir = tmp_path / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text(
        json.dumps({"repositories": [{"name": "repo-b", "parent_branch": "develop"}]})
    )
    assert rr._parent_branch(tmp_path, "repo-a") is None


def test_parent_branch_malformed_json_returns_none(tmp_path: Path) -> None:
    manifest_dir = tmp_path / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text("{not valid json")
    assert rr._parent_branch(tmp_path, "repo-a") is None


def test_parent_branch_read_oserror_returns_none(tmp_path: Path) -> None:
    manifest_dir = tmp_path / ".ai-toolkit"
    manifest_dir.mkdir()
    manifest = manifest_dir / "workspace.json"
    manifest.write_text("{}")
    with patch.object(Path, "read_text", side_effect=OSError("boom")):
        assert rr._parent_branch(tmp_path, "repo-a") is None


# ---------------------------------------------------------------------------
# _branch_point
# ---------------------------------------------------------------------------


def test_branch_point_no_parent_returns_none(tmp_path: Path) -> None:
    assert rr._branch_point(tmp_path, None) is None


def test_branch_point_uses_remote_ref(tmp_path: Path) -> None:
    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:3] == ("rev-parse", "--verify", "--quiet") and args[-1] == "origin/main":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            assert "origin/main" in args
            return _git_result(returncode=0, stdout="abc1234\n")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        assert rr._branch_point(tmp_path, "main") == "abc1234"


def test_branch_point_falls_back_to_local_ref(tmp_path: Path) -> None:
    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[-1] == "origin/main":
            return _git_result(returncode=1)
        if args[:3] == ("rev-parse", "--verify", "--quiet") and args[-1] == "main":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            assert "main" in args
            return _git_result(returncode=0, stdout="def5678\n")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        assert rr._branch_point(tmp_path, "main") == "def5678"


def test_branch_point_no_local_or_remote_ref_returns_none(tmp_path: Path) -> None:
    with patch("workspace_engine.cli.reset_repos.run_git", return_value=_git_result(returncode=1)):
        assert rr._branch_point(tmp_path, "main") is None


def test_branch_point_merge_base_failure_returns_none(tmp_path: Path) -> None:
    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[0] == "rev-parse":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            return _git_result(returncode=1, stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        assert rr._branch_point(tmp_path, "main") is None


def test_branch_point_merge_base_empty_stdout_returns_none(tmp_path: Path) -> None:
    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[0] == "rev-parse":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            return _git_result(returncode=0, stdout="  \n")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        assert rr._branch_point(tmp_path, "main") is None


# ---------------------------------------------------------------------------
# reset_repositories
# ---------------------------------------------------------------------------


def _make_repo(repos_dir: Path, name: str) -> Path:
    repo = repos_dir / name
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    return repo


def test_reset_repositories_no_repositories_dir(tmp_path: Path) -> None:
    rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 1


def test_reset_repositories_filter_invalid_repo(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    rc = rr.reset_repositories(repo_filter=["missing-repo"], start_dir=tmp_path)
    assert rc == 1


def test_reset_repositories_empty_repos_dir(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_default_discovery_skips_non_git_entries(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "not-a-repo.txt").write_text("x")
    _make_repo(repos_dir, "repo-a")

    with patch(
        "workspace_engine.cli.reset_repos.run_git",
        return_value=_git_result(returncode=0, stdout=""),
    ):
        rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_branch_point_with_empty_log_output(tmp_path: Path) -> None:
    workspace_dir = tmp_path
    repos_dir = workspace_dir / "repositories"
    _make_repo(repos_dir, "repo-a")
    manifest_dir = workspace_dir / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text(
        json.dumps({"repositories": [{"name": "repo-a", "parent_branch": "main"}]})
    )

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args[:3] == ("rev-parse", "--verify", "--quiet") and args[-1] == "origin/main":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            return _git_result(returncode=0, stdout="branchpoint123\n")
        if args[0] == "log":
            return _git_result(returncode=0, stdout="")  # no local commits
        if args == ("status", "--porcelain"):
            return _git_result(stdout="")  # also clean
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(start_dir=workspace_dir)
    assert rc == 0


def test_reset_repositories_only_untracked_files_no_tracked_dirty(tmp_path: Path) -> None:
    """Local commits (so has_changes is True) plus only untracked status lines,
    to exercise the branch where tracked_dirty is empty but untracked is not."""
    workspace_dir = tmp_path
    repos_dir = workspace_dir / "repositories"
    _make_repo(repos_dir, "repo-a")
    manifest_dir = workspace_dir / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text(
        json.dumps({"repositories": [{"name": "repo-a", "parent_branch": "main"}]})
    )

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args[:3] == ("rev-parse", "--verify", "--quiet") and args[-1] == "origin/main":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            return _git_result(returncode=0, stdout="branchpoint123\n")
        if args[0] == "log":
            return _git_result(returncode=0, stdout="abc1 a commit\n")
        if args == ("status", "--porcelain"):
            return _git_result(stdout="?? new.txt\n")
        if args[:2] == ("reset", "--hard"):
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(force=True, start_dir=workspace_dir)
    assert rc == 0


def test_reset_repositories_all_clean(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")

    with patch(
        "workspace_engine.cli.reset_repos.run_git",
        return_value=_git_result(returncode=0, stdout=""),
    ):
        rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_dry_run_reports_and_exits(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args == ("status", "--porcelain"):
            return _git_result(stdout=" M changed.txt\n?? new.txt\n")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(dry_run=True, start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_filter_specific_repos(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")
    _make_repo(repos_dir, "repo-b")

    with patch(
        "workspace_engine.cli.reset_repos.run_git",
        return_value=_git_result(returncode=0, stdout=""),
    ):
        rc = rr.reset_repositories(repo_filter=["repo-a"], start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_decline_confirmation_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args == ("status", "--porcelain"):
            return _git_result(stdout=" M changed.txt\n")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "n")
    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 0


def test_reset_repositories_force_resets_dirty_repo_with_commits(tmp_path: Path) -> None:
    workspace_dir = tmp_path
    repos_dir = workspace_dir / "repositories"
    _make_repo(repos_dir, "repo-a")
    manifest_dir = workspace_dir / ".ai-toolkit"
    manifest_dir.mkdir()
    (manifest_dir / "workspace.json").write_text(
        json.dumps({"repositories": [{"name": "repo-a", "parent_branch": "main"}]})
    )

    commits = "\n".join(f"abc{i} commit {i}" for i in range(7))  # >5 to hit truncation

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args[:3] == ("rev-parse", "--verify", "--quiet") and args[-1] == "origin/main":
            return _git_result(returncode=0)
        if args[0] == "merge-base":
            return _git_result(returncode=0, stdout="branchpoint123\n")
        if args[0] == "log":
            return _git_result(returncode=0, stdout=commits + "\n")
        if args == ("status", "--porcelain"):
            return _git_result(stdout=" M changed.txt\n?? new.txt\n")
        if args[:2] == ("reset", "--hard"):
            assert args[-1] == "branchpoint123"
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(force=True, start_dir=workspace_dir)
    assert rc == 0


def test_reset_repositories_reset_failure_returns_1(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="")  # detached
        if args == ("status", "--porcelain"):
            return _git_result(stdout=" M changed.txt\n")
        if args[:2] == ("reset", "--hard"):
            assert args[-1] == "HEAD"  # no branch point available
            return _git_result(returncode=1, stderr="fatal: could not reset")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(force=True, start_dir=tmp_path)
    assert rc == 1


def test_reset_repositories_accept_confirmation_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos_dir = tmp_path / "repositories"
    _make_repo(repos_dir, "repo-a")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args == ("branch", "--show-current"):
            return _git_result(stdout="feature\n")
        if args == ("status", "--porcelain"):
            return _git_result(stdout=" M changed.txt\n")
        if args[:2] == ("reset", "--hard"):
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "y")
    with patch("workspace_engine.cli.reset_repos.run_git", side_effect=fake_run_git):
        rc = rr.reset_repositories(start_dir=tmp_path)
    assert rc == 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_forwards_args_and_exit_code() -> None:
    with (
        patch("sys.argv", ["reset-repos", "repo-a", "--force", "--dry-run"]),
        patch.object(rr, "reset_repositories", return_value=0) as mock_reset,
        pytest.raises(SystemExit) as exc,
    ):
        rr.main()
    assert exc.value.code == 0
    mock_reset.assert_called_once_with(force=True, dry_run=True, repo_filter=["repo-a"])
