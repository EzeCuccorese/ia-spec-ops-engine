import os
import stat
import subprocess
import tempfile
from pathlib import Path

from workspace_engine.cli.manage_hooks import main as manage_hooks_cli
from workspace_engine.services.git_hooks import (
    generate_canonical_pre_push_script,
    get_hooks_status,
    install_git_hooks,
    uninstall_git_hooks,
)


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


def test_generate_canonical_pre_push_script():
    script = generate_canonical_pre_push_script()
    assert "#!/usr/bin/env bash" in script
    assert "[1/5] Verificando secretos" in script
    assert "[2/5] Verificando políticas de commit" in script
    assert "[3/5] Ejecutando análisis estático" in script
    assert "[4/5] Ejecutando suites de tests" in script
    assert "[5/5] Delegando al hook pre-push" in script
    assert "ruff" in script
    assert "npm test" in script
    assert "go test" in script
    assert "cargo test" in script


def test_python_runner_prefers_repository_virtualenv():
    script = generate_canonical_pre_push_script()
    assert script.index('[ -x "$REPO_ROOT/.venv/bin/pytest" ]') < script.index("command -v pytest")


def test_hook_clears_inherited_git_environment_after_finding_root():
    script = generate_canonical_pre_push_script()
    assert script.index('cd "$REPO_ROOT" || exit 1') < script.index(
        "unset $(git rev-parse --local-env-vars)"
    )


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
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))

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


def test_cli_manage_hooks_run_and_test(monkeypatch):
    import workspace_engine.cli.manage_hooks as mh

    called = []

    def mock_run_qg(target_dir=None, scope="all", skip=None, timeout=900, commit_style=None):
        called.append((target_dir, scope, skip, timeout, commit_style))
        return 0

    monkeypatch.setattr(mh, "run_quality_gate", mock_run_qg)

    code = mh.main(["run", "--scope", "changed", "--skip", "gitleaks", "--timeout", "300"])
    assert code == 0
    assert len(called) == 1
    assert called[0][1] == "changed"
    assert called[0][2] == "gitleaks"
    assert called[0][3] == 300

    code = mh.main(["test"])
    assert code == 0
    assert len(called) == 2
