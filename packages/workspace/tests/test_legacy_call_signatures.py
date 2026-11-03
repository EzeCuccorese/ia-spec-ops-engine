"""The original calling conventions of run_quality_gate and panel_monitor still work."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from workspace_engine.run_local import tui, tui_monitor
from workspace_engine.services import git_hooks


@pytest.fixture
def gate_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 3, stdout="out\n", stderr="err\n")

    monkeypatch.setattr(git_hooks.subprocess, "run", fake_run)
    monkeypatch.setattr(git_hooks, "_resolve_hook_to_run", lambda root: (root / "hook", None))
    monkeypatch.setattr(git_hooks, "_push_ref_line", lambda root: "refs\n")
    for name in ("QG_SKIP", "QG_TIMEOUT", "QG_COMMIT_STYLE"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_run_quality_gate_accepts_every_argument_positionally(
    tmp_path: Path, gate_calls: list[dict]
) -> None:
    captured: list[str] = []
    code = git_hooks.run_quality_gate(
        tmp_path, "changed", "tests,lint", 120, "conventional", "verbose", captured
    )
    assert code == 3
    env = gate_calls[0]["env"]
    assert (env["QG_SCOPE"], env["QG_SKIP"], env["QG_TIMEOUT"]) == ("changed", "tests,lint", "120")
    assert (env["QG_COMMIT_STYLE"], env["QG_OUTPUT"]) == ("conventional", "verbose")
    assert captured == ["out\nerr\n"] and gate_calls[0]["capture_output"] is True


def test_run_quality_gate_positional_scope_and_keyword_rest(
    tmp_path: Path, gate_calls: list[dict]
) -> None:
    git_hooks.run_quality_gate(tmp_path, "changed", timeout=7)
    env = gate_calls[0]["env"]
    assert (env["QG_SCOPE"], env["QG_TIMEOUT"]) == ("changed", "7")
    assert gate_calls[0]["cwd"] == tmp_path.resolve()


def test_run_quality_gate_defaults_and_keywords_only(
    tmp_path: Path, gate_calls: list[dict]
) -> None:
    git_hooks.run_quality_gate(target_dir=tmp_path, skip="tests")
    env = gate_calls[0]["env"]
    assert (env["QG_SCOPE"], env["QG_OUTPUT"], env["QG_SKIP"]) == ("all", "errors", "tests")
    assert "QG_TIMEOUT" not in env and gate_calls[0]["capture_output"] is False


def test_run_quality_gate_still_rejects_wrong_calls(tmp_path: Path, gate_calls: list[dict]) -> None:
    with pytest.raises(TypeError):
        git_hooks.run_quality_gate(tmp_path, "all", scope="changed")  # given twice
    with pytest.raises(TypeError):
        git_hooks.run_quality_gate(tmp_path, bogus=1)
    with pytest.raises(TypeError):
        git_hooks.run_quality_gate(*range(8))
    assert not gate_calls


@pytest.fixture
def monitor_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake_run(self) -> str:
        calls.append(
            (self.tty_fd, self.results, self.launch_configs, self.db_cfg, self.cooked_attrs)
        )
        return "quit"

    monkeypatch.setattr(tui_monitor._MonitorScreen, "run", fake_run)
    return calls


def test_panel_monitor_takes_the_original_positional_arguments(monitor_calls: list[tuple]) -> None:
    results, configs, db = [{"name": "a"}], [{"name": "a"}], {"x": 1}
    assert tui_monitor.panel_monitor("tty", results, configs, db) == "quit"
    assert tui_monitor.panel_monitor("tty", results, configs, db, "attrs") == "quit"
    assert monitor_calls[0] == ("tty", results, configs, db, None)
    assert monitor_calls[1][4] == "attrs"


def test_panel_monitor_takes_the_original_keywords(monitor_calls: list[tuple]) -> None:
    tui_monitor.panel_monitor(
        "tty", results=[1], launch_configs=[2], db_cfg={}, cooked_attrs="attrs"
    )
    assert monitor_calls == [("tty", [1], [2], {}, "attrs")]


def test_panel_monitor_still_takes_a_session_and_is_reexported(monitor_calls: list[tuple]) -> None:
    session = tui_monitor.MonitorSession([1], [2], {"d": 3})
    assert tui.panel_monitor("tty", session, cooked_attrs="attrs") == "quit"
    assert tui.panel_monitor("tty", session) == "quit"
    assert monitor_calls == [
        ("tty", [1], [2], {"d": 3}, "attrs"),
        ("tty", [1], [2], {"d": 3}, None),
    ]
    assert tui.panel_monitor is tui_monitor.panel_monitor


def test_panel_monitor_rejects_incomplete_calls(monitor_calls: list[tuple]) -> None:
    with pytest.raises(TypeError):
        tui_monitor.panel_monitor("tty", [1], [2])  # db_cfg missing
    assert not monitor_calls
