import os
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from workspace_engine.services.git_hooks import (
    generate_canonical_pre_push_script,
    get_hooks_status,
    install_git_hooks,
    uninstall_git_hooks,
)
from workspace_engine.cli.manage_hooks import main as manage_hooks_cli


def _init_test_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    clean_env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    clean_env["GIT_AUTHOR_NAME"] = "Test User"
    clean_env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    clean_env["GIT_COMMITTER_NAME"] = "Test User"
    clean_env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True, env=clean_env)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True, capture_output=True, env=clean_env)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True, capture_output=True, env=clean_env)


def test_generate_canonical_pre_push_script():
    script = generate_canonical_pre_push_script()
    assert "#!/usr/bin/env bash" in script
    assert "[1/4] Verificando seguridad" in script
    assert "[2/4] Verificando políticas de commit" in script
    assert "[3/4] Ejecutando análisis estático" in script
    assert "[4/4] Ejecutando suites de tests" in script
    assert "ruff check" in script
    assert "npm test" in script
    assert "go test" in script
    assert "cargo test" in script


def test_install_git_hooks_local():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)

        res = install_git_hooks(target_dir=project_dir, is_global=False, force=True)
        assert res["success"] is True
        assert res["is_global"] is False

        hook_file = project_dir / ".githooks" / "pre-push"
        assert hook_file.exists()
        mode = hook_file.stat().st_mode
        assert mode & stat.S_IXUSR

        status = get_hooks_status(target_dir=project_dir)
        assert status["local"]["hook_exists"] is True
        assert status["local"]["is_executable"] is True
        assert status["local"]["is_active"] is True


def test_uninstall_git_hooks_local():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)

        install_git_hooks(target_dir=project_dir, is_global=False, force=True)
        hook_file = project_dir / ".githooks" / "pre-push"
        assert hook_file.exists()

        uninst = uninstall_git_hooks(target_dir=project_dir, is_global=False)
        assert uninst["success"] is True
        assert not hook_file.exists()

        status = get_hooks_status(target_dir=project_dir)
        assert status["local"]["hook_exists"] is False
        assert status["local"]["is_active"] is False


def test_install_git_hooks_global(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)

        res = install_git_hooks(is_global=True, force=True)
        assert res["success"] is True
        assert res["is_global"] is True

        global_hook = home_path / ".githooks" / "pre-push"
        assert global_hook.exists()
        assert global_hook.stat().st_mode & stat.S_IXUSR

        uninst = uninstall_git_hooks(is_global=True)
        assert uninst["success"] is True
        assert not global_hook.exists()


def test_cli_manage_hooks():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)

        # Test status CLI
        code = manage_hooks_cli(["status", "--dir", str(project_dir)])
        assert code == 0

        # Test install CLI
        code = manage_hooks_cli(["install", "--dir", str(project_dir)])
        assert code == 0
        assert (project_dir / ".githooks" / "pre-push").exists()

        # Test uninstall CLI
        code = manage_hooks_cli(["uninstall", "--dir", str(project_dir)])
        assert code == 0
        assert not (project_dir / ".githooks" / "pre-push").exists()
