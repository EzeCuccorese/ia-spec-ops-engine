"""Phase 3: the gate reads the repo/user config files with env > git config > repo > user."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from workspace_engine.cli import manage_hooks
from workspace_engine.services.gate_config import shell_assignments
from workspace_engine.settings import effective

HOOKS = Path(manage_hooks.__file__).parents[1] / "resources" / "hooks"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.delenv("WORKSPACE_CONFIG_DIR", raising=False)
    for name in ("QG_SKIP", "QG_PROTECTED", "QG_TIMEOUT", "QG_COMMIT_STYLE"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    return root


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True)


def test_defaults_equal_the_values_the_script_always_used(repo: Path) -> None:
    gate = effective(repo)
    assert gate["gate.timeout_seconds"].value == 900
    assert gate["gate.protected_branches"].value == "^(main|master|develop|staging)$"
    assert gate["gate.skip"].value == [] and gate["gate.commit_style"].value == ""
    assert {gate[k].origin for k in gate if k.startswith("gate.")} == {"default"}


def test_precedence_env_git_repo_user_default(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = "gate.timeout_seconds"
    _write(Path.home() / ".config" / "workspace" / "config.toml", "[gate]\ntimeout_seconds = 100\n")
    assert (effective(repo)[key].value, effective(repo)[key].origin) == (100, "user")
    _write(repo / ".workspace" / "config.toml", "[gate]\ntimeout_seconds = 200\n")
    assert (effective(repo)[key].value, effective(repo)[key].origin) == (200, "repo")
    _git(repo, "config", "workspace.timeout", "300")
    assert (effective(repo)[key].value, effective(repo)[key].origin) == (300, "git")
    monkeypatch.setenv("QG_TIMEOUT", "400")
    found = effective(repo)[key]
    assert (found.value, found.origin, found.source) == (400, "env", "QG_TIMEOUT")


def test_existing_git_config_keys_still_work(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(repo, "config", "workspace.skip", "tests,design")
    _git(repo, "config", "workspace.commitStyle", "conventional")
    gate = effective(repo)
    assert gate["gate.skip"].value == ["tests", "design"] and gate["gate.skip"].origin == "git"
    assert gate["gate.commit_style"].value == "conventional"
    monkeypatch.setenv("QG_SKIP", "")  # defined but empty still wins over git config
    assert effective(repo)["gate.skip"].value == []


def test_shell_assignments_only_cover_what_a_file_decides(repo: Path) -> None:
    _write(
        repo / ".workspace" / "config.toml",
        '[gate]\nskip = ["tests"]\ncommit_style = "conventional"\ntimeout_seconds = 50\n',
    )
    _git(repo, "config", "workspace.timeout", "70")  # git config outranks the repo file
    lines = shell_assignments(repo).splitlines()
    assert "QG_SKIP=tests" in lines and "QG_COMMIT_STYLE=conventional" in lines
    assert "QG_TIMEOUT=70" in lines
    assert any(line.startswith("QG_SKIP_SOURCE=") and "config file" in line for line in lines)
    assert not any(line.startswith("QG_PROTECTED") for line in lines)


def _ws_shim(directory: Path) -> Path:
    shim = directory / "ws"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m workspace_engine.cli.main "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return directory


def _commit_msg(repo: Path, tmp_path: Path, message: str) -> int:
    msg = tmp_path / "MSG"
    msg.write_text(message, encoding="utf-8")
    env = {**os.environ, "PATH": f"{_ws_shim(tmp_path / 'bin')}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(HOOKS / "commit-msg"), str(msg)], cwd=repo, env=env, capture_output=True
    ).returncode


def test_commit_msg_hook_follows_the_repo_file(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    assert _commit_msg(repo, tmp_path, "whatever you like\n") == 0  # no style configured
    _write(repo / ".workspace" / "config.toml", '[gate]\ncommit_style = "conventional"\n')
    assert _commit_msg(repo, tmp_path, "whatever you like\n") != 0
    assert _commit_msg(repo, tmp_path, "fix(core): a real subject\n") == 0


def test_hooks_status_warns_when_the_gate_is_not_active(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manage_hooks.render_hooks_status(repo)
    assert "gate settings" not in capsys.readouterr().err
    _write(repo / ".workspace" / "config.toml", "[gate]\ntimeout_seconds = 50\n")
    manage_hooks.render_hooks_status(repo)
    captured = capsys.readouterr()
    assert "gate.timeout_seconds" in captured.out + captured.err
    assert "ws hooks install" in captured.out + captured.err


def test_git_config_winners_are_emitted_but_the_environment_still_wins(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(repo, "config", "workspace.protected", "^(release)$")
    _git(repo, "config", "workspace.timeout", "70")
    lines = shell_assignments(repo).splitlines()
    assert "QG_TIMEOUT=70" in lines and "QG_PROTECTED='^(release)$'" in lines
    monkeypatch.setenv("QG_TIMEOUT", "5")
    monkeypatch.setenv("QG_SKIP", "")  # defined but empty: nothing is skipped, nothing emitted
    _git(repo, "config", "workspace.skip", "tests")
    lines = shell_assignments(repo).splitlines()
    assert not any(line.startswith(("QG_TIMEOUT", "QG_SKIP")) for line in lines)


def test_hooks_find_ws_in_the_user_bin_when_path_is_minimal(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    _ws_shim(home / ".local" / "bin")
    _write(repo / ".workspace" / "config.toml", '[gate]\ncommit_style = "conventional"\n')
    msg = tmp_path / "MSG"
    msg.write_text("not conventional at all\n", encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}
    bad = subprocess.run(["bash", str(HOOKS / "commit-msg"), str(msg)], cwd=repo, env=env)
    assert bad.returncode != 0  # the repo file was loaded although ws was not on PATH
    msg.write_text("fix(core): a real subject\n", encoding="utf-8")
    assert (
        subprocess.run(["bash", str(HOOKS / "commit-msg"), str(msg)], cwd=repo, env=env).returncode
        == 0
    )


def test_without_ws_anywhere_the_hooks_fall_back_silently(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    _write(repo / ".workspace" / "config.toml", '[gate]\ncommit_style = "conventional"\n')
    msg = tmp_path / "MSG"
    msg.write_text("anything\n", encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(
        ["bash", str(HOOKS / "commit-msg"), str(msg)], cwd=repo, env=env, capture_output=True
    )
    assert done.returncode == 0 and done.stderr == b""


@pytest.mark.parametrize("hook", ["pre-push", "pre-commit", "commit-msg"])
def test_every_hook_looks_for_ws_before_loading_the_config(hook: str) -> None:
    script = (HOOKS / hook).read_text(encoding="utf-8")
    assert script.index('"$HOME/.local/bin"') < script.index("ws hooks gate-config")


def test_gate_env_values_keep_the_shell_semantics_of_the_hooks() -> None:
    from workspace_engine._config_core import Layers, resolve
    from workspace_engine.settings import SETTINGS

    def resolved(key: str, value: str):
        setting = next(s for s in SETTINGS if s.key == key)
        return resolve([setting], Layers({}, {}, {}, {}), environ={setting.env: value})[key]

    # ${QG_PROTECTED:-default}, ${QG_COMMIT_STYLE:-...} and the timeout: "" means unset ...
    for key in ("gate.protected_branches", "gate.commit_style", "gate.timeout_seconds"):
        assert resolved(key, "").origin == "default", key
    assert resolved("gate.commit_style", "conventional").value == "conventional"
    # ... while a defined-but-empty QG_SKIP is an explicit "skip nothing".
    skip = resolved("gate.skip", "")
    assert (skip.value, skip.origin) == ([], "env")
