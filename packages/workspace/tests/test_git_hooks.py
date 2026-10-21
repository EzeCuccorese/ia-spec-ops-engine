import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from workspace_engine.cli.manage_hooks import main as manage_hooks_cli
from workspace_engine.services.git_hooks import (
    generate_canonical_pre_push_script,
    get_hooks_status,
    install_git_hooks,
    local_hook_path,
    run_quality_gate,
    supports_config_hooks,
    uninstall_git_hooks,
)

requires_config_hooks = pytest.mark.skipif(
    not supports_config_hooks(),
    reason="this Git does not run config-based hooks (hook.<name>.command)",
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


def _run_generated_hook(
    project_dir: Path,
    *,
    output: str = "errors",
    skip: str = "gitleaks,commits,lint",
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    hook = project_dir / "quality-gate-pre-push"
    hook.write_text(generate_canonical_pre_push_script(), encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    head = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    env = {k: v for k, v in os.environ.items() if not k.startswith("QG_")}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "QG_OUTPUT": output,
            "QG_SKIP": skip,
        }
    )
    env.update(env_overrides or {})
    return subprocess.run(
        [str(hook), "origin"],
        cwd=project_dir,
        input=f"refs/heads/feature {head} refs/heads/feature {head}\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _prepended_path(bin_dir: Path) -> dict[str, str]:
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def _commit_fixture(project_dir: Path) -> None:
    marker = project_dir / "README.md"
    marker.write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project_dir), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "commit", "-m", "test(fixture): initialize"],
        check=True,
        capture_output=True,
    )


def _write_fake_pytest(project_dir: Path, *, exit_code: int, detail_lines: int = 0) -> None:
    pytest_exe = project_dir / ".venv" / "bin" / "pytest"
    pytest_exe.parent.mkdir(parents=True)
    pytest_exe.write_text(
        "#!/bin/sh\n"
        "echo PYTEST_STDOUT_SENTINEL\n"
        "echo PYTEST_STDERR_SENTINEL >&2\n"
        f'i=1; while [ "$i" -le {detail_lines} ]; do echo DETAIL_$i; i=$((i + 1)); done\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    pytest_exe.chmod(pytest_exe.stat().st_mode | stat.S_IXUSR)
    (project_dir / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")


def test_generate_canonical_pre_push_script():
    script = generate_canonical_pre_push_script()
    assert "#!/usr/bin/env bash" in script
    assert "[1/5] Checking for secrets" in script
    assert "[2/5] Checking commit policies" in script
    assert "[3/5] Running static analysis" in script
    assert "[4/5] Checking design limits" in script
    assert "[5/5] Running test suites" in script
    assert "core.hooksPath ~/" not in script
    assert "ruff" in script
    assert '"$JS_PM" test' in script
    assert "go test" in script
    assert "cargo test" in script


def _write_exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_poetry_env(
    project_dir: Path, tools_dir: Path, *, bin_dir: Path | None = None
) -> None:
    """A Poetry project whose env lives outside the repo, as Poetry does by default."""
    env_dir = tools_dir / "poetry-env"
    _write_exe(env_dir / "bin" / "pytest", "echo POETRY_PYTEST_SENTINEL\nexit 7")
    # `env info -p` fails like it does when Poetry now picks another Python;
    # only `env list` knows the env.
    _write_exe(
        (bin_dir or tools_dir / "bin") / "poetry",
        f'[ "$2" = info ] && exit 1\necho "{env_dir} (Activated)"',
    )
    (project_dir / "poetry.lock").write_text("", encoding="utf-8")
    (project_dir / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")


def _hook_in_fixture_repo(tmp: str) -> Path:
    project_dir = Path(tmp)
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    return project_dir


def test_python_tests_run_with_the_poetry_env_when_there_is_no_venv():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        _write_fake_poetry_env(project_dir, Path(tools))

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(Path(tools) / "bin"))

        assert "POETRY_PYTEST_SENTINEL" in proc.stdout + proc.stderr
        assert proc.returncode == 1


def test_poetry_project_without_env_asks_to_install_instead_of_running_global_pytest():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "poetry.lock").write_text("", encoding="utf-8")
        (project_dir / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")
        bin_dir = Path(tools) / "bin"
        _write_exe(bin_dir / "poetry", "exit 1")
        _write_exe(bin_dir / "pytest", "echo GLOBAL_PYTEST_SENTINEL")

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(bin_dir))

        out = proc.stdout + proc.stderr
        assert "Run: poetry install" in out
        assert "GLOBAL_PYTEST_SENTINEL" not in out
        assert proc.returncode == 1


def test_ruff_runs_the_lockfile_version_when_the_env_is_not_installed():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "poetry.lock").write_text(
            '[[package]]\nname = "ruff"\nversion = "0.16.8"\n', encoding="utf-8"
        )
        (project_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        bin_dir = Path(tools) / "bin"
        _write_exe(bin_dir / "poetry", "exit 1")
        _write_exe(bin_dir / "uv", 'echo "UV_SENTINEL $*"\nexit 1')

        proc = _run_generated_hook(
            project_dir, skip="gitleaks,commits,tests", env_overrides=_prepended_path(bin_dir)
        )

        assert "UV_SENTINEL tool run ruff@0.16.8 check ." in proc.stdout + proc.stderr


def test_pipenv_env_is_used_for_python_tests():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "Pipfile.lock").write_text("{}", encoding="utf-8")
        (project_dir / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")
        env_dir = Path(tools) / "pipenv-env"
        _write_exe(env_dir / "bin" / "pytest", "echo PIPENV_PYTEST_SENTINEL\nexit 7")
        _write_exe(Path(tools) / "bin" / "pipenv", f'echo "{env_dir}"')

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(Path(tools) / "bin"))

        assert "PIPENV_PYTEST_SENTINEL" in proc.stdout + proc.stderr


def test_missing_module_is_reported_as_an_environment_problem():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (project_dir / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")
        bin_dir = Path(tools) / "bin"
        _write_exe(
            bin_dir / "pytest",
            "echo \"E   ModuleNotFoundError: No module named 'fastapi'\"\nexit 4",
        )

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(bin_dir))

        out = proc.stdout + proc.stderr
        assert "environment problem (No module named 'fastapi')" in out
        assert "Install it: pip install -r requirements.txt" in out


def test_hook_finds_user_tools_when_launched_without_the_login_path():
    """An IDE runs the hook with a bare PATH; ~/.local/bin still has poetry."""
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
        project_dir = _hook_in_fixture_repo(tmp)
        _write_fake_poetry_env(project_dir, Path(home), bin_dir=Path(home) / ".local" / "bin")

        proc = _run_generated_hook(
            project_dir, env_overrides={"HOME": home, "PATH": "/usr/bin:/bin"}
        )

        assert "POETRY_PYTEST_SENTINEL" in proc.stdout + proc.stderr


requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@requires_node
def test_js_project_without_node_modules_asks_to_install():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "package.json").write_text(
            '{"scripts": {"test": "jest"}, "devDependencies": {"jest": "1"}}', encoding="utf-8"
        )
        (project_dir / "package-lock.json").write_text("{}", encoding="utf-8")
        bin_dir = Path(tools) / "bin"
        _write_exe(bin_dir / "npm", "echo NPM_SENTINEL")

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(bin_dir))

        out = proc.stdout + proc.stderr
        assert "Run: npm ci" in out
        assert "NPM_SENTINEL" not in out
        assert proc.returncode == 1


@requires_node
def test_js_tests_run_with_the_lockfile_package_manager():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "package.json").write_text('{"scripts": {"test": "x"}}', encoding="utf-8")
        (project_dir / "pnpm-lock.yaml").write_text("", encoding="utf-8")
        (project_dir / "node_modules").mkdir()
        bin_dir = Path(tools) / "bin"
        _write_exe(bin_dir / "pnpm", 'echo "PNPM_SENTINEL $*"\nexit 1')

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(bin_dir))

        assert "PNPM_SENTINEL test" in proc.stdout + proc.stderr


@requires_node
def test_pinned_node_version_is_taken_from_nvm():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as nvm:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "package.json").write_text('{"scripts": {"test": "x"}}', encoding="utf-8")
        (project_dir / ".nvmrc").write_text("7\n", encoding="utf-8")
        _write_exe(Path(nvm) / "versions" / "node" / "v7.10.1" / "bin" / "node", "echo v7.10.1")

        proc = _run_generated_hook(project_dir, env_overrides={"NVM_DIR": nvm})

        assert "Using Node 7 from nvm (.nvmrc pins it)" in proc.stdout


def test_php_project_without_vendor_asks_to_install():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tools:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "composer.json").write_text(
            '{"require": {"php": ">=8"}, "scripts": {"test": "phpunit"}}', encoding="utf-8"
        )
        bin_dir = Path(tools) / "bin"
        _write_exe(bin_dir / "composer", "echo COMPOSER_SENTINEL")

        proc = _run_generated_hook(project_dir, env_overrides=_prepended_path(bin_dir))

        out = proc.stdout + proc.stderr
        assert "Run: composer install" in out
        assert "COMPOSER_SENTINEL" not in out


def test_maven_tests_prefer_the_repository_wrapper():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "pom.xml").write_text("<project/>", encoding="utf-8")
        _write_exe(project_dir / "mvnw", "echo MVNW_SENTINEL\nexit 1")

        proc = _run_generated_hook(project_dir)

        assert "MVNW_SENTINEL" in proc.stdout + proc.stderr


def test_flutter_tests_use_the_fvm_pinned_sdk():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = _hook_in_fixture_repo(tmp)
        (project_dir / "pubspec.yaml").write_text("name: fixture\n", encoding="utf-8")
        (project_dir / ".fvmrc").write_text('{"flutter": "3.0.0"}', encoding="utf-8")
        _write_exe(
            project_dir / ".fvm" / "flutter_sdk" / "bin" / "flutter",
            "echo FVM_FLUTTER_SENTINEL\nexit 1",
        )

        proc = _run_generated_hook(project_dir)

        assert "FVM_FLUTTER_SENTINEL" in proc.stdout + proc.stderr


def test_hook_clears_inherited_git_environment_after_finding_root():
    script = generate_canonical_pre_push_script()
    assert script.index('cd "$REPO_ROOT" || exit 1') < script.index(
        "unset $(git rev-parse --local-env-vars)"
    )


def test_compact_output_hides_successful_command_output():
    # @s1
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        _write_fake_pytest(project_dir, exit_code=0)

        proc = _run_generated_hook(project_dir)

        assert proc.returncode == 0
        assert "Test Suites: PASS" in proc.stdout
        assert "PYTEST_STDOUT_SENTINEL" not in proc.stdout
        assert "PYTEST_STDERR_SENTINEL" not in proc.stderr


def test_compact_output_shows_failed_command_and_preserves_full_log():
    # @s2
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        _write_fake_pytest(project_dir, exit_code=7)

        proc = _run_generated_hook(project_dir)

        assert proc.returncode == 1
        combined = proc.stdout + proc.stderr
        assert "PYTEST_STDOUT_SENTINEL" in combined
        assert "PYTEST_STDERR_SENTINEL" in combined
        assert "Test Suites: FAIL" in combined
        failure_log = project_dir / ".git" / "workspace" / "quality-gate" / "latest.log"
        assert failure_log.is_file()
        assert stat.S_IMODE(failure_log.stat().st_mode) == 0o600
        log_text = failure_log.read_text(encoding="utf-8")
        assert "PYTEST_STDOUT_SENTINEL" in log_text
        assert "PYTEST_STDERR_SENTINEL" in log_text


def test_compact_failure_is_bounded_while_full_log_is_complete():
    # @s2
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        _write_fake_pytest(project_dir, exit_code=7, detail_lines=250)

        proc = _run_generated_hook(project_dir)

        combined = proc.stdout + proc.stderr
        assert proc.returncode == 1
        assert "output truncated:" in combined
        assert "DETAIL_100" not in combined
        failure_log = project_dir / ".git" / "workspace" / "quality-gate" / "latest.log"
        assert "DETAIL_100" in failure_log.read_text(encoding="utf-8")


def test_verbose_output_streams_successful_command_output():
    # @s3
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        _write_fake_pytest(project_dir, exit_code=0)

        proc = _run_generated_hook(project_dir, output="verbose")

        assert proc.returncode == 0
        assert "PYTEST_STDOUT_SENTINEL" in proc.stdout
        assert "PYTEST_STDERR_SENTINEL" in proc.stderr


def _push_with_gate(project_dir: Path) -> subprocess.CompletedProcess[str]:
    """Pushes to a bare remote with the gate's stages skipped (only wiring is under test)."""
    remote = project_dir.parent / f"{project_dir.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project_dir, check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        QG_SKIP="gitleaks,commits,lint,tests",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
    )
    return subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/feature"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def _write_hook(path: Path, sentinel: str, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {sentinel}\nexit {exit_code}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@requires_config_hooks
@pytest.mark.parametrize("repo_exit", [0, 3])
def test_gate_runs_before_repository_hook_without_shadowing_it(tmp_path: Path, repo_exit: int):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    _write_hook(project_dir / ".git" / "hooks" / "pre-push", "REPO_HOOK_SENTINEL", repo_exit)
    assert install_git_hooks(target_dir=project_dir)["success"] is True

    proc = _push_with_gate(project_dir)

    combined = proc.stdout + proc.stderr
    assert "Quality Gate" in combined or "All good" in combined
    assert "REPO_HOOK_SENTINEL" in combined
    assert combined.index("All good") < combined.index("REPO_HOOK_SENTINEL")
    assert (proc.returncode == 0) is (repo_exit == 0)


@requires_config_hooks
def test_gate_also_runs_when_repository_uses_local_hooks_path(tmp_path: Path):
    """Husky-style repos (local core.hooksPath) keep their hook and still get the gate."""
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    _write_hook(project_dir / ".husky" / "_" / "pre-push", "HUSKY_SENTINEL")
    subprocess.run(["git", "config", "core.hooksPath", ".husky/_"], cwd=project_dir, check=True)
    assert install_git_hooks(target_dir=project_dir)["success"] is True

    proc = _push_with_gate(project_dir)

    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert "All good" in combined
    assert "HUSKY_SENTINEL" in combined


@requires_config_hooks
def test_install_git_hooks_local():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)

        res = install_git_hooks(target_dir=project_dir, is_global=False)
        assert res["success"] is True
        assert res["is_global"] is False

        hook_file = local_hook_path(project_dir)
        assert hook_file.exists()
        assert hook_file.stat().st_mode & stat.S_IXUSR
        assert not (project_dir / ".githooks").exists()
        hooks_path = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"], cwd=project_dir, capture_output=True
        )
        assert hooks_path.returncode != 0

        status = get_hooks_status(target_dir=project_dir)
        assert status["local"]["hook_exists"] is True
        assert status["local"]["is_executable"] is True
        assert status["local"]["is_active"] is True


@requires_config_hooks
def test_uninstall_git_hooks_local_only_removes_gate_keys():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        subprocess.run(["git", "config", "hook.other.event", "pre-push"], cwd=project_dir)
        subprocess.run(["git", "config", "hook.other.command", "true"], cwd=project_dir)

        install_git_hooks(target_dir=project_dir, is_global=False)
        hook_file = local_hook_path(project_dir)
        assert hook_file.exists()

        uninst = uninstall_git_hooks(target_dir=project_dir, is_global=False)
        assert uninst["success"] is True
        assert not hook_file.exists()
        other = subprocess.run(
            ["git", "config", "--get", "hook.other.command"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        assert other.stdout.strip() == "true"

        status = get_hooks_status(target_dir=project_dir)
        assert status["local"]["hook_exists"] is False
        assert status["local"]["is_active"] is False


@requires_config_hooks
def test_install_git_hooks_global(monkeypatch, tmp_path: Path):
    home_path = tmp_path / "home"
    home_path.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_path)
    monkeypatch.setenv("HOME", str(home_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_path / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))

    res = install_git_hooks(is_global=True)
    assert res["success"] is True
    assert res["is_global"] is True

    global_hook = home_path / ".config" / "workspace" / "hooks" / "pre-push"
    assert global_hook.exists()
    assert global_hook.stat().st_mode & stat.S_IXUSR
    config = (home_path / ".gitconfig").read_text()
    assert "workspace-gate" in config
    assert "hooksPath" not in config
    assert get_hooks_status(tmp_path)["global"]["is_active"] is True

    uninst = uninstall_git_hooks(is_global=True)
    assert uninst["success"] is True
    assert not global_hook.exists()
    assert "workspace-gate" not in (home_path / ".gitconfig").read_text()


@requires_config_hooks
def test_reinstall_refreshes_the_local_scripts():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        install_git_hooks(target_dir=project_dir, is_global=False)
        hook_file = local_hook_path(project_dir)
        hook_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        res = install_git_hooks(target_dir=project_dir, is_global=False)
        assert res["success"] is True
        assert hook_file.read_text(encoding="utf-8") == generate_canonical_pre_push_script()


@requires_config_hooks
def test_reinstall_refreshes_the_global_scripts(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))
        install_git_hooks(is_global=True)
        hook_file = home_path / ".config" / "workspace" / "hooks" / "pre-push"
        hook_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        res = install_git_hooks(is_global=True)
        assert res["success"] is True
        assert hook_file.read_text(encoding="utf-8") == generate_canonical_pre_push_script()


def test_cli_hooks_install_has_no_force_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        manage_hooks_cli(["install", "--force"])
    assert exc.value.code == 2
    assert "unrecognized arguments: --force" in capsys.readouterr().err


def test_uninstall_git_hooks_local_no_hook_present():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        # No hook was ever installed: unlink is skipped, but the call still succeeds.
        res = uninstall_git_hooks(target_dir=project_dir, is_global=False)
        assert res["success"] is True


def test_uninstall_git_hooks_global_no_hook_present(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))

        res = uninstall_git_hooks(is_global=True)
        assert res["success"] is True


def test_run_quality_gate_writes_temp_hook_when_none_installed(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home, tempfile.TemporaryDirectory() as tmp:
        # Neither a local nor a (fake) global hook exists, so a temp hook is written,
        # used, and then cleaned up.
        monkeypatch.setattr(Path, "home", lambda: Path(mock_home))

        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests",
            output="errors",
        )
        assert code == 0


def test_run_quality_gate_without_skip_arg_omits_qg_skip_env(monkeypatch):
    import workspace_engine.services.git_hooks as git_hooks_mod

    with tempfile.TemporaryDirectory() as mock_home, tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(Path, "home", lambda: Path(mock_home))

        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        install_git_hooks(target_dir=project_dir, is_global=False)

        real_run = subprocess.run
        captured_env = {}

        def fake_run(args, *a, **kwargs):
            if args and "pre-push" in str(args[0]):
                captured_env.update(kwargs.get("env") or {})
                return subprocess.CompletedProcess(args=args, returncode=0)
            return real_run(args, *a, **kwargs)

        monkeypatch.setattr(git_hooks_mod.subprocess, "run", fake_run)

        code = run_quality_gate(target_dir=project_dir, skip=None)
        assert code == 0
        assert "QG_SKIP" not in captured_env


def test_run_quality_gate_uses_installed_local_hook():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        install_git_hooks(target_dir=project_dir, is_global=False)

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests",
        )
        assert code == 0


def test_run_quality_gate_uses_installed_global_hook_when_no_local(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home, tempfile.TemporaryDirectory() as tmp:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))
        install_git_hooks(is_global=True)

        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests",
            commit_style="conventional",
        )
        assert code == 0


def test_run_quality_gate_without_prior_commit_uses_zero_sha():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        # No commits at all: `git rev-parse HEAD` and `HEAD~1` both fail.

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests",
        )
        assert isinstance(code, int)


@requires_config_hooks
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
        assert local_hook_path(project_dir).exists()

        # Test uninstall CLI
        code = manage_hooks_cli(["uninstall", "--dir", str(project_dir)])
        assert code == 0
        assert not local_hook_path(project_dir).exists()


def test_cli_manage_hooks_run_and_test(monkeypatch):
    # @s5
    import workspace_engine.cli.manage_hooks as mh

    called = []

    def mock_run_qg(target_dir=None, **options):
        called.append({"target_dir": target_dir, **options})
        return 0

    monkeypatch.setattr(mh, "run_quality_gate", mock_run_qg)

    code = mh.main(
        [
            "run",
            "--scope",
            "changed",
            "--skip",
            "gitleaks",
            "--timeout",
            "300",
            "--output",
            "verbose",
        ]
    )
    assert code == 0
    assert len(called) == 1
    assert called[0]["scope"] == "changed"
    assert called[0]["skip"] == "gitleaks"
    assert called[0]["timeout"] == 300
    assert called[0]["output"] == "verbose"

    code = mh.main(["test"])
    assert code == 0
    assert len(called) == 2
    # `test` leaves output to run_quality_gate's own default ("errors").
    assert called[1]["timeout"] == 120 and "output" not in called[1]

    with pytest.raises(SystemExit):
        mh.main(["run", "--output", "unsupported"])


@requires_config_hooks
def test_commit_msg_hook_enforces_conventional_commits_when_opted_in(tmp_path: Path):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@e.x",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@e.x",
    )

    def commit(message: str) -> int:
        return subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", message],
            cwd=project_dir,
            env=env,
            capture_output=True,
        ).returncode

    # Opt-in: without a configured style any message is accepted.
    assert commit("added stuff before opting in") == 0
    subprocess.run(
        ["git", "config", "workspace.commitStyle", "conventional"], cwd=project_dir, check=True
    )
    assert commit("added stuff") != 0
    assert commit("feat(core): add stuff") == 0
    uninstall_git_hooks(target_dir=project_dir)
    assert commit("added stuff without hook") == 0


# --- [4/5] Design limits stage --------------------------------------------------


def _push_with_gate_custom(
    project_dir: Path, *, skip: str, extra_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Pushes to a bare remote with a chosen QG_SKIP, optionally prepending to PATH."""
    remote = project_dir.parent / f"{project_dir.name}-design-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project_dir, check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        QG_SKIP=skip,
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
    )
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/feature"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def _write_ws_shim(bin_dir: Path) -> None:
    """A tiny 'ws' on PATH that runs the real CLI through the current interpreter."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "ws"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -m workspace_engine.cli.main "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)


def _complex_python_function(name: str, branches: int = 12) -> str:
    """A Python function whose cyclomatic complexity exceeds the default limit (10)."""
    lines = [f"def {name}(x):"]
    for i in range(branches):
        keyword = "if" if i == 0 else "elif"
        lines.append(f"    {keyword} x == {i}:")
        lines.append(f"        return {i}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


def _commit_complex_function(project_dir: Path, message: str) -> None:
    (project_dir / "bad.py").write_text(_complex_python_function("legacy_complex"))
    subprocess.run(["git", "-C", str(project_dir), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "commit", "-m", message],
        check=True,
        capture_output=True,
    )


@requires_config_hooks
def test_design_stage_fails_on_complex_new_function(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    bin_dir = tmp_path / "bin"
    _write_ws_shim(bin_dir)
    # the function must be new relative to the merge-base with the default branch
    subprocess.run(["git", "-C", str(project_dir), "checkout", "-q", "-b", "feature"], check=True)
    _commit_complex_function(project_dir, "test(fixture): add complex function")

    proc = _push_with_gate_custom(
        project_dir, skip="gitleaks,commits,lint,tests", extra_path=bin_dir
    )

    combined = proc.stdout + proc.stderr
    assert "[4/5] Checking design limits" in combined
    assert "✘ Design limits: FAIL" in combined
    assert proc.returncode != 0


@requires_config_hooks
def test_design_stage_skipped_via_qg_skip(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    bin_dir = tmp_path / "bin"
    _write_ws_shim(bin_dir)
    _commit_complex_function(project_dir, "test(fixture): add complex function")

    proc = _push_with_gate_custom(
        project_dir, skip="gitleaks,commits,lint,tests,design", extra_path=bin_dir
    )

    combined = proc.stdout + proc.stderr
    assert "Design limits: skipped by QG_SKIP" in combined
    assert proc.returncode == 0


@requires_config_hooks
def test_design_stage_passes_in_warn_mode(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    bin_dir = tmp_path / "bin"
    _write_ws_shim(bin_dir)
    (project_dir / ".ai-governance").mkdir()
    (project_dir / ".ai-governance" / "config.toml").write_text('[design]\nmode = "warn"\n')
    _commit_complex_function(project_dir, "test(fixture): add complex function, warn mode")

    proc = _push_with_gate_custom(
        project_dir, skip="gitleaks,commits,lint,tests", extra_path=bin_dir
    )

    combined = proc.stdout + proc.stderr
    assert "✔ Design limits: PASS" in combined
    assert proc.returncode == 0


def test_pre_push_reads_the_commit_style_from_repo_config():
    script = generate_canonical_pre_push_script()
    assert "git config --get workspace.commitStyle" in script


def test_cli_skip_help_lists_the_stages_the_gate_knows(capsys):
    script = generate_canonical_pre_push_script()
    stages = re.findall(r"^if skipped (\w+); then", script, re.MULTILINE)
    with pytest.raises(SystemExit):
        manage_hooks_cli(["run", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert f"({','.join([*stages, 'all'])})" in help_text


# --- workspace.skip repo default ------------------------------------------------


def _push_without_qg_skip(project_dir: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    remote = project_dir.parent / f"{project_dir.name}-skipcfg-remote.git"
    if not remote.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project_dir, check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "QG_"))}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", **extra_env)
    return subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/feature"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
    )


@requires_config_hooks
def test_workspace_skip_config_skips_stage_and_env_wins(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    subprocess.run(
        ["git", "config", "workspace.skip", "gitleaks,commits,lint,design,tests"],
        cwd=project_dir,
        check=True,
    )

    proc = _push_without_qg_skip(project_dir)
    combined = proc.stdout + proc.stderr
    assert "Test Suites: skipped by workspace.skip (repo config)" in combined
    assert proc.returncode == 0

    # QG_SKIP=none overrides the repo default: the test stage runs again.
    proc = _push_without_qg_skip(project_dir, QG_SKIP="none")
    assert "Test Suites: skipped" not in proc.stdout + proc.stderr


@requires_config_hooks
def test_skip_command_sets_shows_and_clears(tmp_path: Path, capsys) -> None:
    from workspace_engine.cli.manage_hooks import main as hooks_main

    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)

    assert hooks_main(["skip", "set", "tests", "--dir", str(project_dir)]) == 0
    assert hooks_main(["skip", "show", "--dir", str(project_dir)]) == 0
    assert "tests" in capsys.readouterr().out
    assert hooks_main(["skip", "set", "bogus", "--dir", str(project_dir)]) == 1
    assert hooks_main(["skip", "clear", "--dir", str(project_dir)]) == 0
    got = subprocess.run(
        ["git", "config", "--get", "workspace.skip"], cwd=project_dir, capture_output=True
    )
    assert got.returncode != 0


def test_run_quality_gate_passes_step_timeout_via_env_without_subprocess_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_test_git_repo(tmp_path)
    _commit_fixture(tmp_path)
    recorded_kwargs: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        recorded_kwargs.clear()
        recorded_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    captured: list[str] = []
    assert run_quality_gate(tmp_path, timeout=900, capture=captured) == 0
    assert captured == ["ok\n"]
    assert "timeout" not in recorded_kwargs
    assert recorded_kwargs["env"]["QG_TIMEOUT"] == "900"
