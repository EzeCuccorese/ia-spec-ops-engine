"""Tests for output budget limits when CLIs run in agent mode."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_governance.rules.cli import main as rules_main
from ai_governance.session.cli import main as session_main


def _seed_task_with_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, num_steps: int = 30
) -> None:
    """Create a task with many steps to trigger truncation in list/view commands."""
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")

    result = session_main(["new", "T-1", "--title", "Budget task"])
    assert result == 0

    for i in range(num_steps):
        result = session_main(["step", "T-1", "add", f"step {i}"])
        assert result == 0


class TestProgressListBudget:
    """Test that progress list output stays within budget."""

    def test_progress_list_budget_1500_chars(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """progress list output in agent mode must be <= 1500 chars."""
        _seed_task_with_steps(monkeypatch, tmp_path)

        session_main(["list"])
        out = capsys.readouterr().out

        assert len(out) <= 1500
        assert "\x1b" not in out


class TestProgressViewBudget:
    """Test that progress view output stays within budget."""

    def test_progress_view_budget_1500_chars(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """progress view output in agent mode must be <= 1500 chars."""
        _seed_task_with_steps(monkeypatch, tmp_path)

        session_main(["show", "T-1"])
        out = capsys.readouterr().out

        assert len(out) <= 1500
        assert "\x1b" not in out

    def test_progress_view_json_budget_4000_chars(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """progress view --json output in agent mode must be <= 4000 chars."""
        _seed_task_with_steps(monkeypatch, tmp_path)

        session_main(["show", "T-1", "--json"])
        out = capsys.readouterr().out

        assert len(out) <= 4000
        assert "\x1b" not in out


class TestRulesListBudget:
    """Test that rules list output stays within budget."""

    def test_rules_list_budget_1500_chars(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """rules list output in agent mode must be <= 1500 chars."""
        monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
        monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "usage"))

        rules_main(["list"])
        out = capsys.readouterr().out

        assert len(out) <= 1500
        assert "\x1b" not in out


@pytest.mark.parametrize(
    "argv,budget",
    [
        (["list"], 1500),
        (["show", "T-1"], 1500),
        (["show", "T-1", "--json"], 4000),
    ],
)
def test_progress_commands_stay_in_budget(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argv: list[str],
    budget: int,
) -> None:
    """Parametrized test: various progress commands must stay in budget."""
    _seed_task_with_steps(monkeypatch, tmp_path)

    session_main(argv)
    out = capsys.readouterr().out

    assert len(out) <= budget, f"Output for {argv} is {len(out)} chars, budget {budget}"
    assert "\x1b" not in out
