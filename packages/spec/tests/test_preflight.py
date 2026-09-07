from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from spec.cli import main
from spec.core.preflight import PreflightManager
from spec.governance.project import ProjectGovernance


def _init_git_repo(path: Path) -> None:
    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    git_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    subprocess.run(
        ["git", "init", "-b", "main", str(path)], check=True, capture_output=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"], check=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        env=git_env,
    )
    (path / "README.md").write_text("Hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, env=git_env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "initial commit"], check=True, env=git_env
    )


def test_resolve_branches(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    mgr = PreflightManager(tmp_path)
    info = mgr.resolve_branches()
    assert info.current_branch == "main"
    assert "main" in info.local_branches


def test_baseline_gate_skipped_when_no_verification_config(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()

    mgr = PreflightManager(tmp_path)
    res = mgr.run("Sample Feature", use_worktree=False)

    assert res["status"] == "READY"
    assert res["feature"] == "sample-feature"
    assert res["baseline"] == "PASS"


def test_baseline_gate_aborts_on_failure(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    ProjectGovernance(tmp_path).initialize()

    # Configure a failing check in .spec/verification.json
    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "failing-check",
                "command": ["false"],
                "required": True,
            }
        ],
    }
    (tmp_path / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    mgr = PreflightManager(tmp_path)
    res = mgr.run("Broken Feature", use_worktree=False)

    assert res["status"] == "FAIL"
    assert "Baseline verification checks failed" in res["error"]
    assert res["checks_passed"] == 0
    assert res["checks_total"] == 1
    # Verify no spec was created
    assert not (tmp_path / ".spec" / "specs" / "broken-feature").exists()


def test_baseline_gate_passes_and_provisions_worktree(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    # Configure a passing check
    v_config = {
        "schema_version": 1,
        "checks": [
            {
                "id": "passing-check",
                "command": ["true"],
                "required": True,
            }
        ],
    }
    (repo_dir / ".spec" / "verification.json").write_text(json.dumps(v_config), encoding="utf-8")

    # Create dummy .env and .venv to test symlink and copy
    (repo_dir / ".env").write_text("FOO=bar", encoding="utf-8")
    (repo_dir / ".venv").mkdir()
    (repo_dir / ".venv" / "bin").mkdir()

    mgr = PreflightManager(repo_dir)
    res = mgr.run("Payment Gateway", branch="feature/payment-gw", use_worktree=True)

    assert res["status"] == "READY"
    assert res["feature"] == "payment-gateway"
    assert res["baseline"] == "PASS"

    worktree_path = Path(res["worktree_path"])
    assert worktree_path.exists()
    assert (worktree_path / ".spec" / "specs" / "payment-gateway" / "spec.md").exists()
    assert (worktree_path / ".env").exists()
    # Check that .venv symlink was created
    assert (worktree_path / ".venv").is_symlink()


def test_cli_preflight_command(tmp_path: Path, capsys) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    ProjectGovernance(repo_dir).initialize()

    with pytest.raises(SystemExit) as exc:
        main(["preflight", "CLI Feature", "--no-worktree", "--root", str(repo_dir), "--json"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "READY"
    assert payload["feature"] == "cli-feature"
