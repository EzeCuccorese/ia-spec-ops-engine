"""
End-to-end dispatch tests for `ws <command>`: the real sub-`main` runs (only external
side effects are stubbed) so the arguments `ws` forwards are the ones each command parses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli.main import main


def _ws(*argv: str) -> int | str | None:
    """Runs `ws <argv>` and returns the exit code (None when the command just returns)."""
    with patch("sys.argv", ["ws", *argv]):
        try:
            main()
        except SystemExit as exc:
            return exc.code
    return None


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A generated-workspace layout (`workspaces/demo/repositories/svc`) used as cwd."""
    root = tmp_path / "workspaces" / "demo"
    (root / ".git").mkdir(parents=True)
    (root / "repositories" / "svc").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def test_generate_receives_the_workspace_name(workspace: Path, tmp_path: Path, capsys):
    toolkit = tmp_path / "toolkit"
    (toolkit / ".git").mkdir(parents=True)
    os.chdir(toolkit)

    assert _ws("generate", "demo", "svc") == 1
    assert "Workspace 'demo' already exists" in _output(capsys)


def test_edit_outside_a_workspace_fails(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    assert _ws("edit") == 1
    assert "must be run from inside a workspace" in _output(capsys)


def test_edit_help_is_its_own(capsys):
    assert _ws("edit", "--help") == 0
    assert "usage: ws edit" in _output(capsys)


def test_clean_removes_build_caches(workspace: Path):
    cache = workspace / "repositories" / "svc" / "node_modules"
    cache.mkdir()

    assert _ws("clean") == 0
    assert not cache.exists()


def test_stop_accepts_its_timeout(workspace: Path, capsys):
    assert _ws("stop", "--timeout", "0.1") == 0
    assert "No services running" in _output(capsys)


def test_reset_receives_only_the_repositories(workspace: Path, capsys):
    assert _ws("reset", "--dry-run", "svc") == 1
    assert "Not a git repository: svc" in _output(capsys)


def test_delete_removes_the_named_workspace(tmp_path: Path, monkeypatch):
    toolkit = tmp_path / "toolkit"
    (toolkit / ".git").mkdir(parents=True)
    target = tmp_path / "workspaces" / "old"
    target.mkdir(parents=True)
    (target / ".workspace_metadata").touch()
    monkeypatch.chdir(toolkit)

    assert _ws("delete", "--force", "old") == 0
    assert not target.exists()


def test_build_runs_in_the_given_directory(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "Cargo.toml").touch()
    monkeypatch.chdir(tmp_path)

    with patch("workspace_engine.cli.build_project.run_command", return_value="") as run:
        assert _ws("build", str(project)) == 0
    assert run.call_args_list[0].kwargs["cwd"] == project


def test_deps_receives_only_the_repositories(workspace: Path):
    with patch("workspace_engine.cli.install_deps.install_repo_deps", return_value=True) as inst:
        assert _ws("deps", "svc") == 0
    inst.assert_called_once_with(workspace / "repositories" / "svc")


def test_java_json_prints_the_environment(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    env = {"JAVA_HOME": "/opt/jdk-21", "PATH": "/opt/jdk-21/bin"}
    with patch("workspace_engine.cli.set_java.setups_java", return_value=env):
        assert _ws("java", "--json") is None
    assert json.loads(_output(capsys)) == env


def test_java_without_flag_prints_exports(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    env = {"JAVA_HOME": "/opt/jdk-21", "PATH": "/opt/jdk-21/bin"}
    with patch("workspace_engine.cli.set_java.setups_java", return_value=env):
        assert _ws("java") is None
    assert "export JAVA_HOME='/opt/jdk-21'" in _output(capsys)


def test_env_init_check_only(workspace: Path, capsys):
    config = workspace / "config"
    config.mkdir()
    (config / ".env.example").write_text("# Token\nTOKEN=\n", encoding="utf-8")
    (config / ".env").write_text("TOKEN=abc\n", encoding="utf-8")

    assert _ws("env-init", "--check-only") == 0
    assert "fully configured" in _output(capsys)


def test_env_load_updates_the_values_file(tmp_path: Path):
    values = tmp_path / "values.dev.yaml"
    values.write_text("apps:\n  - name: svc\n", encoding="utf-8")

    code = _ws(
        "env-load",
        "--envs",
        "dev",
        "--services",
        "svc",
        "--var",
        "LOG_LEVEL",
        "--values",
        "debug",
        "--root",
        str(tmp_path),
    )

    assert code is None
    assert "LOG_LEVEL: debug" in values.read_text(encoding="utf-8")


def test_benchmark_receives_only_the_repositories(workspace: Path, capsys):
    assert _ws("benchmark", "ghost") == 0
    assert "No repositories to benchmark" in _output(capsys)


def test_run_local_stop(tmp_path: Path, monkeypatch, capsys):
    from workspace_engine.run_local import constants

    monkeypatch.setattr(constants, "PIDS_DIR", tmp_path / "pids")

    assert _ws("run-local", "--stop") is None
    assert "No active services." in _output(capsys)


def test_env_load_fails_when_a_values_file_is_missing(tmp_path: Path, capsys):
    (tmp_path / "values.dev.yaml").write_text("apps:\n  - name: svc\n", encoding="utf-8")

    code = _ws(
        "env-load",
        "--envs",
        "dev,prod",
        "--services",
        "svc",
        "--var",
        "LOG_LEVEL",
        "--values",
        "debug,info",
        "--root",
        str(tmp_path),
    )

    assert code == 1
    assert "LOG_LEVEL: debug" in (tmp_path / "values.dev.yaml").read_text(encoding="utf-8")
    assert f"File not found: {tmp_path / 'values.prod.yaml'}" in _output(capsys)


def test_env_load_expands_a_tilde_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "gitops").mkdir()
    values = tmp_path / "gitops" / "values.dev.yaml"
    values.write_text("apps:\n  - name: svc\n", encoding="utf-8")
    args = ["--envs", "dev", "--services", "svc", "--var", "LOG_LEVEL", "--values", "debug"]

    assert _ws("env-load", *args, "--root=~/gitops") is None
    assert "LOG_LEVEL: debug" in values.read_text(encoding="utf-8")


def test_build_expands_a_tilde_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "Cargo.toml").touch()

    with patch("workspace_engine.cli.build_project.run_command", return_value="") as run:
        assert _ws("build", "~/project") == 0
    assert run.call_args_list[0].kwargs["cwd"] == (tmp_path / "project").resolve()
