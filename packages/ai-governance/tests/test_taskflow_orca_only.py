"""Agents run only as Orca workers: the subprocess path is gone and every hint says so."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from ai_governance.install import content
from ai_governance.taskflow import config as flow_config
from ai_governance.taskflow import orca, prompts
from ai_governance.taskflow.cli import main
from ai_governance.taskflow.config import FlowConfig
from ai_governance.taskflow.guide import GUIDE
from orca_fakes import attach_orca

README = Path(__file__).resolve().parents[1] / "README.md"
FORBIDDEN = (
    "headless",
    "codex exec",
    "claude -p",
    "antigravity --print",
    "--dangerously-skip-permissions",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    for name in ("ORCA_CLI_COMMAND", "ORCA_DEV_REPO_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(orca, "MACOS_ORCA_APP_BIN", str(tmp_path / "no-such-orca-app"))


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("darwin", {}, "orca"),
        ("linux", {}, "orca-ide"),
        ("linux", {"ORCA_DEV_REPO_ROOT": "/src/orca"}, "orca-dev"),
        ("darwin", {"ORCA_DEV_REPO_ROOT": "/src/orca"}, "orca-dev"),
        ("linux", {"ORCA_CLI_COMMAND": "my-orca --x", "ORCA_DEV_REPO_ROOT": "/s"}, "my-orca --x"),
        ("darwin", {"ORCA_CLI_COMMAND": "  "}, "orca"),
        ("linux", {"ORCA_CLI_COMMAND": "", "ORCA_DEV_REPO_ROOT": " "}, "orca-ide"),
    ],
)
def test_orca_command_rule(
    monkeypatch: pytest.MonkeyPatch, platform: str, env: dict[str, str], expected: str
) -> None:
    monkeypatch.setattr(orca.sys, "platform", platform)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert orca.orca_command() == expected


def test_darwin_orca_app_binary_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_bin = tmp_path / "Orca.app" / "Contents" / "Resources" / "bin" / "orca"
    app_bin.parent.mkdir(parents=True)
    app_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    app_bin.chmod(0o755)
    monkeypatch.setattr(orca.sys, "platform", "darwin")
    monkeypatch.setattr(orca, "MACOS_ORCA_APP_BIN", str(app_bin))

    # 1. /usr/local/bin/orca exists on PATH but is an unreadable symlink -> fall back to Orca.app bin
    monkeypatch.setattr(orca.shutil, "which", lambda cmd: "/usr/local/bin/orca")
    monkeypatch.setattr(
        orca.os,
        "access",
        lambda path, mode: path in {str(app_bin), "/usr/local/bin/orca", "/opt/homebrew/bin/orca"},
    )
    monkeypatch.setattr(orca.os.path, "islink", lambda path: path == "/usr/local/bin/orca")
    monkeypatch.setattr(
        orca.os, "readlink", lambda path: (_ for _ in ()).throw(PermissionError("denied"))
    )
    assert orca.orca_command() == str(app_bin)
    argv = orca.worker_start_argv(orca.WorkerStart("s.md", "claude", "m", "/repo", "t"))
    assert argv[0] == str(app_bin)

    # 2. /usr/local/bin/orca is readable -> keep "orca"
    monkeypatch.setattr(orca.os, "readlink", lambda path: str(app_bin))
    assert orca.orca_command() == "orca"

    # 3. orca not on PATH -> fall back to Orca.app bin
    monkeypatch.setattr(orca.shutil, "which", lambda cmd: None)
    assert orca.orca_command() == str(app_bin)
    # Mocking shutil.which to return None still triggers missing-CLI problem
    assert orca.orca_problem() is not None

    # 4. orca found elsewhere on PATH -> keep "orca"
    monkeypatch.setattr(orca.shutil, "which", lambda cmd: "/opt/homebrew/bin/orca")
    assert orca.orca_command() == "orca"
    assert orca.orca_problem() is None


def test_config_loads_without_orca_and_debate_open_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    problem = orca.orca_problem()
    assert problem and f"Orca CLI '{orca.orca_command()}'" in problem
    assert "not found on PATH" in problem and "ORCA_CLI_COMMAND" in problem
    assert not [e for e in FlowConfig().validate() if "Orca" in e]
    with pytest.raises(orca.OrcaError) as raised:
        orca.require_orca()
    assert str(raised.value) == problem
    assert main(["new", "TASK-1", "--title", "t"]) == 0
    assert main(["config"]) == 0
    assert problem in capsys.readouterr().out
    topic = tmp_path / "topic.md"
    topic.write_text("Discuss design.\n", encoding="utf-8")
    assert (
        main(["debate", "TASK-1", "open", "--topic-file", str(topic), "--agents", "claude,codex"])
        == 1
    )
    assert "not found on PATH" in capsys.readouterr().err


def test_a_present_orca_cli_clears_the_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach_orca(tmp_path / "world", monkeypatch)
    assert orca.orca_problem() is None


def test_worker_row_running_only_for_known_running_states() -> None:
    for state in ("ready", "running", "starting", "stopping"):
        row = orca.WorkerRow("D1", state, "live", "claude")
        assert row.running is True
    for state in (
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
        "stopped",
        "abandoned",
        "timed_out",
        "completed",
        "error",
        "killed",
        "paused",
        "unseen",
    ):
        row = orca.WorkerRow("D1", state, "live", "claude")
        assert row.running is False


def test_the_subprocess_agent_path_is_gone() -> None:
    assert importlib.util.find_spec("ai_governance.taskflow.adapters") is None
    for mod in ("gates", "judge", "judge_flow", "risk", "tdd", "rounds", "policy"):
        assert importlib.util.find_spec(f"ai_governance.taskflow.{mod}") is None
    for name in ("run_agent", "build_command", "binary", "AgentRun", "RunResult", "AGENTS"):
        assert not hasattr(prompts, name), name
    for name in ("agent_binary", "AGENTS_WITH_BINARY"):
        assert not hasattr(flow_config, name), name
    assert not hasattr(FlowConfig, "_missing_binaries")
    assert {"READ_ONLY_LIMIT", "THESIS_INSTRUCTION", "CROSS_INSTRUCTION"} <= set(dir(prompts))
    assert not hasattr(prompts, "VERDICT_INSTRUCTION")
    assert not hasattr(prompts, "parse_verdict")


def test_no_removed_command_or_launch_in_hints() -> None:
    for text in (GUIDE, content.TASKFLOW_SKILL):
        assert not re.search(r"round (<ID>|<id>|\S+) (run|dispatch)\b", text), text[:80]
        assert "round run" not in text
        for banned in FORBIDDEN:
            assert banned not in text, banned
    readme = README.read_text(encoding="utf-8")
    for banned in FORBIDDEN:
        assert banned not in readme, banned


def test_help_of_round_lists_only_collect_and_abort(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["round", "TASK-1", "--help"])
    shown = capsys.readouterr().out
    assert "collect" in shown and "abort" in shown
    for removed in ("dispatch", "record", "start", "finish"):
        assert not re.search(rf"\b{removed}\b", shown), removed
    assert not re.search(r"\brun\b", shown)
    assert "SUPPRESS" not in shown


def test_guide_says_agents_never_run_from_the_engine() -> None:
    assert "Agents never run from the engine" in GUIDE
    assert "Never launch agent CLIs yourself" in GUIDE
    assert "END YOUR TURN" in GUIDE and "worker_done" in GUIDE
    assert "round <ID> collect" in GUIDE and "round <ID> abort" in GUIDE
