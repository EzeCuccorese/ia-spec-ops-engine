"""Agents run only as Orca workers: the subprocess path is gone and every hint says so."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from ai_governance.install import content
from ai_governance.taskflow import config as flow_config
from ai_governance.taskflow import gates, orca, prompts, rounds
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


def test_config_loads_without_orca_and_dispatch_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    problem = orca.orca_problem()
    assert problem and f"Orca CLI '{orca.orca_command()}'" in problem
    assert "not found on PATH" in problem and "ORCA_CLI_COMMAND" in problem
    assert not [e for e in FlowConfig().validate() if "Orca" in e]  # loading never needs Orca
    with pytest.raises(orca.OrcaError) as raised:  # dispatch and judge use this check
        orca.require_orca()
    assert str(raised.value) == problem
    assert main(["new", "ONB-1", "--title", "t"]) == 0
    assert main(["config"]) == 0  # a notice line, not an error
    assert problem in capsys.readouterr().out
    dispatch = ["round", "ONB-1", "dispatch", "--role", "planner", "--agent", "claude"]
    assert main([*dispatch, "--prompt", "x"]) == 1
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


def test_doctor_taskflow_rows_check_orca_and_emit_notice_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_governance.install import doctor

    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("ORCA_CLI_COMMAND", raising=False)
    rows = doctor._taskflow_rows(None)
    assert ("taskflow", doctor.OK, "roles and judges OK") in rows
    orca_rows = [r for r in rows if r[0] == "taskflow:orca"]
    assert len(orca_rows) == 1
    assert orca_rows[0][1] == doctor.WARN
    assert "not found on PATH" in orca_rows[0][2]

    attach_orca(tmp_path / "world", monkeypatch)
    rows_present = doctor._taskflow_rows(None)
    assert rows_present == [("taskflow", doctor.OK, "roles, judges and the Orca CLI OK")]


def test_the_subprocess_agent_path_is_gone() -> None:
    assert importlib.util.find_spec("ai_governance.taskflow.adapters") is None
    for name in ("run_round", "RoundRequest", "_run_reserved", "_abort_round", "_record"):
        assert not hasattr(rounds, name), name
    for name in ("run_agent", "build_command", "binary", "AgentRun", "RunResult", "AGENTS"):
        assert not hasattr(prompts, name), name
    for name in ("agent_binary", "AGENTS_WITH_BINARY"):
        assert not hasattr(flow_config, name), name
    assert not hasattr(FlowConfig, "_missing_binaries")
    assert {"READ_ONLY_LIMIT", "VERDICT_INSTRUCTION", "parse_verdict"} <= set(dir(prompts))


def test_the_writer_lease_and_manual_record_survive() -> None:
    for name in ("writer_lease", "active_lease", "LeaseError", "record_manual", "LEASE_ENV"):
        assert hasattr(rounds, name), name


def test_no_removed_command_or_launch_in_hints() -> None:
    hints = [GUIDE, content.TASKFLOW_SKILL, *gates.NEXT_COMMAND.values()]
    for text in hints:
        assert not re.search(r"round (<ID>|<id>|\S+) run\b", text), text[:80]
        assert "round run" not in text
        for banned in FORBIDDEN:
            assert banned not in text, banned
    readme = README.read_text(encoding="utf-8")
    for banned in FORBIDDEN:
        assert banned not in readme, banned
    assert "round <id> dispatch" in readme and "agents.<name>_binary" in readme


def test_help_of_round_lists_no_run_action(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["round", "ONB-1", "--help"])
    shown = capsys.readouterr().out
    assert "dispatch" in shown and "collect" in shown and "abort" in shown
    assert not re.search(r"\brun\b", shown)  # no run action, no ==SUPPRESS== entry
    assert "SUPPRESS" not in shown


def test_guide_and_skill_say_agents_never_run_from_the_engine() -> None:
    assert "Agents never run from the engine" in GUIDE
    assert "Never launch agent CLIs yourself" in GUIDE
    assert "The builder is YOU (the coordinating session)" in GUIDE
    assert "different Orca sessions" in GUIDE
    assert "A judge is a reader" in GUIDE
    assert "END YOUR TURN" in GUIDE and "worker_done" in GUIDE
    skill = content.TASKFLOW_SKILL
    assert "never run from the engine" in skill and "end the turn" in skill
    assert "You are the builder" in skill and "dispatch" in skill and "collect" in skill
