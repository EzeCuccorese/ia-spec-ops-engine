import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
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


def _run_generated_hook(
    project_dir: Path,
    *,
    output: str = "errors",
    skip: str = "gitleaks,commits,lint,repohooks",
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
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "QG_OUTPUT": output,
            "QG_SKIP": skip,
        }
    )
    return subprocess.run(
        [str(hook), "origin"],
        cwd=project_dir,
        input=f"refs/heads/feature {head} refs/heads/feature {head}\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


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
    assert "[4/5] Running test suites" in script
    assert "[5/5] Delegating to the repository's pre-push hook" in script
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
        failure_log = project_dir / ".git" / "specops" / "quality-gate" / "latest.log"
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
        failure_log = project_dir / ".git" / "specops" / "quality-gate" / "latest.log"
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


@pytest.mark.parametrize(
    ("exit_code", "sentinel_visible", "expected_gate_code"),
    [(0, False, 0), (9, True, 1)],
)
def test_compact_output_applies_to_delegated_repository_hook(
    exit_code: int, sentinel_visible: bool, expected_gate_code: int
):
    # @s4
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)
        delegated = project_dir / ".husky" / "pre-push"
        delegated.parent.mkdir()
        delegated.write_text(
            f"#!/bin/sh\necho DELEGATED_HOOK_SENTINEL\nexit {exit_code}\n",
            encoding="utf-8",
        )
        delegated.chmod(delegated.stat().st_mode | stat.S_IXUSR)

        proc = _run_generated_hook(
            project_dir,
            skip="gitleaks,commits,lint,tests",
        )

        assert proc.returncode == expected_gate_code
        combined = proc.stdout + proc.stderr
        assert ("DELEGATED_HOOK_SENTINEL" in combined) is sentinel_visible


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
    # @s5
    import workspace_engine.cli.manage_hooks as mh

    called = []

    def mock_run_qg(
        target_dir=None,
        scope="all",
        skip=None,
        timeout=900,
        commit_style=None,
        output="errors",
    ):
        called.append((target_dir, scope, skip, timeout, commit_style, output))
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
    assert called[0][1] == "changed"
    assert called[0][2] == "gitleaks"
    assert called[0][3] == 300
    assert called[0][5] == "verbose"

    code = mh.main(["test"])
    assert code == 0
    assert len(called) == 2
    assert called[1][5] == "errors"

    with pytest.raises(SystemExit):
        mh.main(["run", "--output", "unsupported"])
