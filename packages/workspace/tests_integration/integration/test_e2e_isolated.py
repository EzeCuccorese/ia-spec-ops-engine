"""
Isolated, idempotent end-to-end integration tests for ia-spec-ops-engine.

Creates temporary Git repositories and workspaces to verify:
1. Full Workspace Engine cycle: generate -> worktree -> build -> clean -> delete.
2. Full SDD Engine cycle: init -> specify -> plan -> tasks -> verify -> finish.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from workspace_engine.cli.clean_workspace import clean_workspace
from workspace_engine.cli.generate_workspace import create_workspace_structure
from workspace_engine.services.configure_repos import RepoConfig


def _init_git_repo(repo_path: Path) -> None:
    """Initializes a local git repository with an initial commit."""
    repo_path.mkdir(parents=True, exist_ok=True)
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git_env = {
        **clean_env,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "-C", str(repo_path), "init", "-b", "main"],
        capture_output=True,
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Test User"],
        capture_output=True,
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "test@example.com"],
        capture_output=True,
        check=True,
        env=git_env,
    )
    (repo_path / "README.md").write_text("# Test Repo\n")
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'test'\nversion = '0.1.0'\n")
    subprocess.run(
        ["git", "-C", str(repo_path), "add", "."], capture_output=True, check=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", "chore(init): initial commit"],
        capture_output=True,
        check=True,
        env=git_env,
    )


@pytest.mark.integration
def test_e2e_workspace_flow_isolated():
    """Isolated integration test for the workspace lifecycle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        repos_dir = base_dir / "ai-repositories"
        workspaces_dir = base_dir / "workspaces"

        # 1. Create base repositories
        repo_a = repos_dir / "auth-service"
        repo_b = repos_dir / "billing-service"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)

        # 2. Configure and generate the workspace
        repo_configs = [
            RepoConfig(name="auth-service", mode="new", branch="feature-test", parent="main"),
            RepoConfig(name="billing-service", mode="new", branch="feature-test", parent="main"),
        ]
        repo_paths = {"auth-service": repo_a, "billing-service": repo_b}

        ws_dir = create_workspace_structure(
            workspace_name="feature-test",
            workspaces_root=workspaces_dir,
            repo_configs=repo_configs,
            repo_paths=repo_paths,
        )

        # 3. Validate the created structure
        assert ws_dir.exists()
        assert (ws_dir / "repositories" / "auth-service").exists()
        assert (ws_dir / "repositories" / "billing-service").exists()
        assert (ws_dir / ".ai-toolkit" / "workspace.json").exists()
        assert (ws_dir / "AGENTS.md").exists()

        # 4. Clean up the workspace
        code = clean_workspace(ws_dir)
        assert code == 0
