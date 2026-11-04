"""PR #47 review threads: empty env values, --corporate "", trust prompt EOF, resolved paths."""

from __future__ import annotations

import argparse
import dataclasses
import os
import types
from pathlib import Path

import pytest
from ai_governance import corporate
from ai_governance._config_core import Layers, Setting, resolve
from ai_governance.taskflow import cli
from ai_governance.taskflow.config import PendingTrust, is_trusted, load_config

NO_LAYERS = Layers({}, {}, {}, {})


def _resolved(setting: Setting, value: str):
    return resolve([setting], NO_LAYERS, environ={"X": value})[setting.key]


@pytest.mark.parametrize(
    "default", [[], "text", True, 30, 2.5], ids=["list", "text", "bool", "int", "float"]
)
def test_an_empty_env_value_is_unset_by_default(default: object) -> None:
    found = _resolved(Setting("k", default, "X"), "")
    assert (found.value, found.origin) == (default, "default")


@pytest.mark.parametrize(
    ("default", "expected"), [([], []), ("text", ""), (True, False)], ids=["list", "text", "bool"]
)
def test_a_setting_that_opts_in_takes_an_empty_env_value(default: object, expected: object) -> None:
    found = _resolved(Setting("k", default, "X", empty_env_is_value=True), "")
    assert (found.value, found.origin, found.source) == (expected, "env", "X")


def test_only_the_selection_settings_opt_in() -> None:
    from ai_governance.settings import SETTINGS

    assert {s.key for s in SETTINGS if s.empty_env_is_value} == {"corporate.packs"}


@pytest.fixture
def empty_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    for name in (
        "AI_GOVERNANCE_GATE_COMMAND",
        "AI_GOVERNANCE_PLANNER_MODEL",
        "AI_GOVERNANCE_PLANNER_AGENT",
        "AI_GOVERNANCE_CODEX_SCOUT_MODEL",
        "AI_GOVERNANCE_SCHEDULE_LABEL",
    ):
        monkeypatch.setenv(name, "")
    return tmp_path


def test_empty_operational_env_values_keep_the_defaults(empty_env: Path) -> None:
    from ai_governance.settings import effective

    found = effective(empty_env)
    assert found["hooks.gate_command"].value == "ws check --changed --cache --json"
    assert found["agents.codex_scout_model"].value == "gpt-6-luna"
    assert found["taskflow.planner_model"].value == "gemini-4-argon-high"
    assert all(found[k].origin == "default" for k in found if k != "corporate.packs")


def test_an_empty_gate_command_env_still_runs_the_stop_gate(
    empty_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import subprocess

    from ai_governance import hooks

    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"status": "failed", "text": "x"}), stderr=""
        )

    monkeypatch.setattr(hooks.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(hooks.subprocess, "run", fake_run)
    monkeypatch.setattr(hooks, "_payload", lambda: {})
    assert hooks._claude_stop_gate() == 2  # the check ran and failed, as without the variable
    assert seen[0][0] == "/bin/ws"


@pytest.fixture
def packs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "packs"
    for name in ("acme", "globex"):
        (root / name / "rules").mkdir(parents=True)
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE_DIR", str(root))
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AI_GOVERNANCE_CORPORATE", raising=False)
    return root


def test_an_empty_corporate_flag_selects_no_pack(packs_dir: Path) -> None:
    assert corporate.selected_names("") == []
    assert corporate.packs(only=corporate.selected_names("")) == []
    assert [p.name for p in corporate.packs(only=corporate.selected_names("acme"))] == ["acme"]


def test_an_empty_corporate_env_selects_no_pack_and_unset_selects_all(
    packs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert corporate.selected_names() is None
    assert [p.name for p in corporate.packs()] == ["acme", "globex"]
    monkeypatch.setenv("AI_GOVERNANCE_CORPORATE", "")
    assert corporate.selected_names() == []
    assert corporate.packs() == []


def test_install_with_an_empty_corporate_flag_installs_no_pack(
    packs_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_governance.install import installer

    seen: list[list[str]] = []
    real = corporate.packs
    monkeypatch.setattr(
        installer.corporate, "packs", lambda **kw: seen.append(real(**kw)) or real(**kw)
    )
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AI_GOVERNANCE_LAUNCH_AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    installer.install_user(["claude"], dry_run=True, corporate_names=[])
    assert seen and seen[0] == []


def _terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in cli._agent_markers():
        monkeypatch.delenv(name)
    monkeypatch.setattr(cli.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    out = types.SimpleNamespace(isatty=lambda: True, write=lambda s: len(s), flush=lambda: None)
    monkeypatch.setattr(cli.sys, "stdout", out)


@pytest.fixture
def untrusted_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "real" / "repo"
    (repo / ".ai-governance").mkdir(parents=True)
    (repo / ".ai-governance" / "taskflow.toml").write_text('[checks]\ncommands = ["make evil"]\n')
    return repo


def _content(repo: Path) -> dict:
    import tomllib

    return tomllib.loads((repo / ".ai-governance" / "taskflow.toml").read_text())


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_closing_the_trust_prompt_is_a_refusal_not_a_traceback(
    untrusted_repo: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    _terminal(monkeypatch)

    def closed(prompt: str = "") -> str:
        raise error

    monkeypatch.setattr("builtins.input", closed)
    assert cli.cmd_trust(argparse.Namespace(repo=str(untrusted_repo), yes=False)) == 1
    assert not is_trusted(untrusted_repo, _content(untrusted_repo))


def test_trust_matches_the_pending_repo_by_resolved_path(
    untrusted_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _terminal(monkeypatch)
    link = tmp_path / "link"
    os.symlink(untrusted_repo, link)  # the macOS /var -> /private/var situation
    real = load_config([untrusted_repo])
    (waiting,) = real.pending_trust
    aliased = dataclasses.replace(
        real,
        pending_trust=(PendingTrust(str(link), waiting.digest, waiting.commands, waiting.config),),
    )
    monkeypatch.setattr(cli, "load_config", lambda repos: aliased)
    assert cli.cmd_trust(argparse.Namespace(repo=str(untrusted_repo), yes=True)) == 0
    assert is_trusted(untrusted_repo, _content(untrusted_repo))
