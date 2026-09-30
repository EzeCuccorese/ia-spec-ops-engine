import os
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
    assert "[4/5] Checking design limits" in script
    assert "[5/5] Running test suites" in script
    assert "core.hooksPath ~/" not in script
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


def test_install_git_hooks_local():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)

        res = install_git_hooks(target_dir=project_dir, is_global=False, force=True)
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


def test_uninstall_git_hooks_local_only_removes_gate_keys():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        subprocess.run(["git", "config", "hook.other.event", "pre-push"], cwd=project_dir)
        subprocess.run(["git", "config", "hook.other.command", "true"], cwd=project_dir)

        install_git_hooks(target_dir=project_dir, is_global=False, force=True)
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


def test_install_git_hooks_global(monkeypatch, tmp_path: Path):
    home_path = tmp_path / "home"
    home_path.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_path)
    monkeypatch.setenv("HOME", str(home_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_path / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))

    res = install_git_hooks(is_global=True, force=True)
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


def test_install_git_hooks_local_existing_without_force():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        install_git_hooks(target_dir=project_dir, is_global=False, force=True)

        res = install_git_hooks(target_dir=project_dir, is_global=False, force=False)
        assert res["success"] is False
        assert "already exists" in res["message"]


def test_install_git_hooks_global_existing_without_force(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))

        install_git_hooks(is_global=True, force=True)
        res = install_git_hooks(is_global=True, force=False)
        assert res["success"] is False
        assert "already exists" in res["message"]


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
            skip="gitleaks,commits,lint,tests,repohooks",
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
        install_git_hooks(target_dir=project_dir, is_global=False, force=True)

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
        install_git_hooks(target_dir=project_dir, is_global=False, force=True)

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests,repohooks",
        )
        assert code == 0


def test_run_quality_gate_uses_installed_global_hook_when_no_local(monkeypatch):
    with tempfile.TemporaryDirectory() as mock_home, tempfile.TemporaryDirectory() as tmp:
        home_path = Path(mock_home)
        monkeypatch.setattr(Path, "home", lambda: home_path)
        monkeypatch.setenv("HOME", str(mock_home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home_path / ".gitconfig"))
        install_git_hooks(is_global=True, force=True)

        project_dir = Path(tmp)
        _init_test_git_repo(project_dir)
        _commit_fixture(project_dir)

        code = run_quality_gate(
            target_dir=project_dir,
            scope="none",
            skip="gitleaks,commits,lint,tests,repohooks",
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
            skip="gitleaks,commits,lint,tests,repohooks",
        )
        assert isinstance(code, int)


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


def test_commit_msg_hook_enforces_conventional_commits(tmp_path: Path):
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


def test_design_stage_fails_on_complex_new_function(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _init_test_git_repo(project_dir)
    _commit_fixture(project_dir)
    assert install_git_hooks(target_dir=project_dir)["success"] is True
    bin_dir = tmp_path / "bin"
    _write_ws_shim(bin_dir)
    _commit_complex_function(project_dir, "test(fixture): add complex function")

    proc = _push_with_gate_custom(
        project_dir, skip="gitleaks,commits,lint,tests", extra_path=bin_dir
    )

    combined = proc.stdout + proc.stderr
    assert "[4/5] Checking design limits" in combined
    assert "✘ Design limits: FAIL" in combined
    assert proc.returncode != 0


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
