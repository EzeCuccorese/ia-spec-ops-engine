"""
Unit tests for workspace_engine.cli.generate_workspace.

Filesystem effects use tmp_path; git and interactive services are mocked so
no real subprocess or terminal interaction happens.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.cli import generate_workspace as gw
from workspace_engine.services.configure_repos import RepoConfig


def _git_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    res = MagicMock()
    res.returncode = returncode
    res.stdout = stdout
    res.stderr = stderr
    return res


# ---------------------------------------------------------------------------
# setup_repo_worktree
# ---------------------------------------------------------------------------


def test_setup_repo_worktree_already_exists_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature", parent="main")

    with patch(
        "workspace_engine.cli.generate_workspace.run_git",
        return_value=_git_result(stdout=f"worktree {target}\nbranch refs/heads/feature\n"),
    ) as mock_run:
        gw.setup_repo_worktree(tmp_path, target, cfg)
    mock_run.assert_called_once()


def test_setup_repo_worktree_no_match_in_existing_list_then_creates(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature", parent="main")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(
                stdout=f"worktree {tmp_path / 'other-1'}\nworktree {tmp_path / 'other-2'}\n"
            )
        if args[0] == "fetch":
            return _git_result(returncode=0)
        if args[:2] == ("rev-parse", "--verify"):
            return _git_result(returncode=0)
        if args[:2] == ("worktree", "add"):
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_unknown_mode_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="unsupported", branch="feature", parent=None)

    with patch(
        "workspace_engine.cli.generate_workspace.run_git",
        return_value=_git_result(stdout=""),
    ) as mock_run:
        gw.setup_repo_worktree(tmp_path, target, cfg)
    mock_run.assert_called_once()  # only the initial "worktree list" call


def test_setup_repo_worktree_new_mode_uses_remote_branch(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature", parent="develop")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[0] == "fetch":
            return _git_result(returncode=0)
        if args[:2] == ("rev-parse", "--verify"):
            return _git_result(returncode=0)
        if args[:2] == ("worktree", "add"):
            assert "origin/develop" in args
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_new_mode_default_parent_falls_back_to_local(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature", parent=None)

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[0] == "fetch":
            return _git_result(returncode=0)
        if args[:2] == ("rev-parse", "--verify"):
            return _git_result(returncode=1)  # remote ref missing
        if args[:2] == ("worktree", "add"):
            assert "main" in args
            assert "origin/main" not in args
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_new_mode_failure_raises(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature", parent="main")

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[0] == "fetch":
            return _git_result(returncode=0)
        if args[:2] == ("rev-parse", "--verify"):
            return _git_result(returncode=0)
        if args[:2] == ("worktree", "add"):
            return _git_result(returncode=1, stderr="locked")
        raise AssertionError(f"unexpected git call: {args}")

    with (
        patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git),
        pytest.raises(RuntimeError, match="Failed to create worktree"),
    ):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_existing_local_branch(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="existing", branch="feature", parent=None)

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[:2] == ("worktree", "add"):
            assert "feature" in args
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_existing_remote_only_branch(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="existing", branch="feature", parent=None)
    cfg.mark_remote_only()

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[0] == "fetch":
            return _git_result(returncode=0)
        if args[:2] == ("worktree", "add"):
            assert "--track" in args
            assert "origin/feature" in args
            return _git_result(returncode=0)
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git):
        gw.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_existing_mode_failure_raises(tmp_path: Path) -> None:
    target = tmp_path / "target"
    cfg = RepoConfig(name="repo-a", mode="existing", branch="feature", parent=None)

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("worktree", "list"):
            return _git_result(stdout="")
        if args[:2] == ("worktree", "add"):
            return _git_result(returncode=1, stderr="conflict")
        raise AssertionError(f"unexpected git call: {args}")

    with (
        patch("workspace_engine.cli.generate_workspace.run_git", side_effect=fake_run_git),
        pytest.raises(RuntimeError, match="Failed to create worktree"),
    ):
        gw.setup_repo_worktree(tmp_path, target, cfg)


# ---------------------------------------------------------------------------
# create_workspace_structure
# ---------------------------------------------------------------------------


def test_create_workspace_structure_writes_manifest_and_agents_md(tmp_path: Path) -> None:
    workspaces_root = tmp_path / "workspaces"
    repo_src = tmp_path / "ai-repositories" / "repo-a"
    repo_src.mkdir(parents=True)
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature-x", parent="main")

    with (
        patch("workspace_engine.cli.generate_workspace.setup_repo_worktree") as mock_setup,
        patch(
            "workspace_engine.cli.generate_workspace.render_agents_md",
            return_value="# AGENTS\n",
        ) as mock_render,
    ):
        result = gw.create_workspace_structure(
            workspace_name="ws-a",
            workspaces_root=workspaces_root,
            repo_configs=[cfg],
            repo_paths={"repo-a": repo_src},
        )

    assert result == workspaces_root / "ws-a"
    mock_setup.assert_called_once()
    mock_render.assert_called_once()

    manifest = json.loads((result / ".ai-toolkit" / "workspace.json").read_text())
    assert manifest["workspace"] == "ws-a"
    assert manifest["repositories"] == [
        {"name": "repo-a", "branch": "feature-x", "parent_branch": "main"}
    ]
    assert (result / "AGENTS.md").read_text() == "# AGENTS\n"
    assert (result / "docs").is_dir()


def test_create_workspace_structure_existing_mode_has_no_parent_branch(tmp_path: Path) -> None:
    workspaces_root = tmp_path / "workspaces"
    repo_src = tmp_path / "ai-repositories" / "repo-a"
    repo_src.mkdir(parents=True)
    cfg = RepoConfig(name="repo-a", mode="existing", branch="feature-x", parent=None)

    with (
        patch("workspace_engine.cli.generate_workspace.setup_repo_worktree"),
        patch("workspace_engine.cli.generate_workspace.render_agents_md", return_value="x"),
    ):
        result = gw.create_workspace_structure(
            workspace_name="ws-b",
            workspaces_root=workspaces_root,
            repo_configs=[cfg],
            repo_paths={"repo-a": repo_src},
        )

    manifest = json.loads((result / ".ai-toolkit" / "workspace.json").read_text())
    assert manifest["repositories"][0]["parent_branch"] is None


def test_create_workspace_structure_with_template_dir(tmp_path: Path) -> None:
    workspaces_root = tmp_path / "workspaces"
    repo_src = tmp_path / "ai-repositories" / "repo-a"
    repo_src.mkdir(parents=True)
    template_dir = tmp_path / "templates"
    cfg = RepoConfig(name="repo-a", mode="new", branch="feature-x", parent="main")

    with (
        patch("workspace_engine.cli.generate_workspace.setup_repo_worktree"),
        patch(
            "workspace_engine.cli.generate_workspace.render_agents_md", return_value="x"
        ) as mock_render,
    ):
        gw.create_workspace_structure(
            workspace_name="ws-c",
            workspaces_root=workspaces_root,
            repo_configs=[cfg],
            repo_paths={"repo-a": repo_src},
            template_dir=template_dir,
        )
    template_file_arg = mock_render.call_args.args[0]
    assert template_file_arg == template_dir / "workspace-agents.md.template"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _base_main_patches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config").mkdir()
    monkeypatch.setattr(gw, "find_project_root", lambda: root)
    monkeypatch.setattr(gw, "parse_dotenv", lambda _p: {})
    monkeypatch.setattr("sys.argv", ["generate-workspace", *argv])
    return root


def test_main_prompts_for_name_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_main_patches(tmp_path, monkeypatch, [])
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "")
    with pytest.raises(SystemExit) as exc:
        gw.main()
    assert exc.value.code == 1


def test_main_prompted_name_accepted_then_workspace_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _base_main_patches(tmp_path, monkeypatch, [])
    workspaces_root = root.parent / "workspaces"
    (workspaces_root / "ws-prompted").mkdir(parents=True)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "ws-prompted")
    with pytest.raises(SystemExit) as exc:
        gw.main()
    assert exc.value.code == 1


def test_main_workspace_already_exists_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _base_main_patches(tmp_path, monkeypatch, ["ws-existing"])
    workspaces_root = root.parent / "workspaces"
    (workspaces_root / "ws-existing").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        gw.main()
    assert exc.value.code == 1


def test_main_no_repos_selected_exits_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _base_main_patches(tmp_path, monkeypatch, ["ws-new"])
    with (
        patch("workspace_engine.cli.generate_workspace.select_repos", return_value=[]),
        pytest.raises(SystemExit) as exc,
    ):
        gw.main()
    assert exc.value.code == 0


def test_main_configuration_cancelled_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_main_patches(tmp_path, monkeypatch, ["ws-new"])
    with (
        patch(
            "workspace_engine.cli.generate_workspace.select_repos",
            return_value=["repo-a"],
        ),
        patch("workspace_engine.cli.generate_workspace.configure_repos", return_value=None),
        pytest.raises(SystemExit) as exc,
    ):
        gw.main()
    assert exc.value.code == 0


def test_main_interactive_flow_creates_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_main_patches(tmp_path, monkeypatch, ["ws-new"])
    cfg = RepoConfig(name="repo-a", mode="new", branch="ws-new", parent="main")
    with (
        patch(
            "workspace_engine.cli.generate_workspace.select_repos",
            return_value=["repo-a"],
        ),
        patch(
            "workspace_engine.cli.generate_workspace.configure_repos",
            return_value=[cfg],
        ),
        patch("workspace_engine.cli.generate_workspace.create_workspace_structure") as mock_create,
    ):
        gw.main()
    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["workspace_name"] == "ws-new"
    assert kwargs["repo_configs"] == [cfg]


def test_main_direct_repo_args_with_at_and_colon_and_plain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_main_patches(
        tmp_path, monkeypatch, ["ws-new", "repo-a@feature", "repo-b:develop", "repo-c"]
    )
    with patch("workspace_engine.cli.generate_workspace.create_workspace_structure") as mock_create:
        gw.main()
    kwargs = mock_create.call_args.kwargs
    configs = {c.name: c for c in kwargs["repo_configs"]}
    assert configs["repo-a"].mode == "existing"
    assert configs["repo-a"].branch == "feature"
    assert configs["repo-b"].mode == "new"
    assert configs["repo-b"].parent == "develop"
    assert configs["repo-b"].branch == "ws-new"
    assert configs["repo-c"].mode == "new"
    assert configs["repo-c"].parent == "main"


def test_main_uses_ai_repositories_dir_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config").mkdir()
    custom_repos = tmp_path / "custom-repos"
    custom_repos.mkdir()
    monkeypatch.setattr(gw, "find_project_root", lambda: root)
    monkeypatch.setattr(gw, "parse_dotenv", lambda _p: {"AI_REPOSITORIES_DIR": str(custom_repos)})
    monkeypatch.setattr("sys.argv", ["generate-workspace", "ws-new", "repo-a"])
    with patch("workspace_engine.cli.generate_workspace.create_workspace_structure") as mock_create:
        gw.main()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["repo_paths"]["repo-a"] == custom_repos / "repo-a"
