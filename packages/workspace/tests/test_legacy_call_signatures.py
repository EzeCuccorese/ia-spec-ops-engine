"""The original calling conventions of run_quality_gate still work."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
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
