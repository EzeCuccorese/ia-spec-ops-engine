"""Unit tests for evals/design-rules/summarize.py filtering and decision logic."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_summarize() -> ModuleType:
    path = REPO_ROOT / "evals" / "design-rules" / "summarize.py"
    spec = importlib.util.spec_from_file_location("evals_design_rules_summarize", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summarize = _load_summarize()


def _row(condition: str, **overrides: str) -> dict[str, str]:
    base = {
        "task": "payment_client",
        "condition": condition,
        "rep": "1",
        "model": "sonnet",
        "violations_total": "1",
        "violations_by_metric": '{"args": 1}',
        "added_lines": "200",
        "hidden_tests_passed": "4",
        "hidden_tests_total": "4",
        "cost_usd": "0.30",
        "num_turns": "10",
        "error": "",
    }
    base.update(overrides)
    return base


def _test_row(condition: str, **overrides: str) -> dict[str, str]:
    base = _row(
        condition,
        prod_loc_added="100",
        test_loc_added="60",
        test_functions_added="4",
        test_violations="0",
        mutants_killed="8",
        mutants_total="10",
    )
    base.update(overrides)
    return base


def test_per_condition_stats_filters_broken_and_incomplete_runs() -> None:
    without_cost = _row("rules+gate", hidden_tests_passed="1")
    del without_cost["cost_usd"]
    rows = [
        _row(
            "rules+gate", violations_total="1", added_lines="200", cost_usd="0.40", num_turns="20"
        ),
        _row("rules+gate", hidden_tests_passed="0", hidden_tests_total="0", cost_usd="0.16"),
        _row("rules+gate", hidden_tests_passed="0", hidden_tests_total="0", cost_usd="0"),
        _row("rules+gate", cost_usd="0", hidden_tests_passed="2"),
        _row("rules+gate", cost_usd="", hidden_tests_passed="1"),
        without_cost,
        _row("rules+gate", cost_usd="nan"),
        _row("rules+gate", cost_usd="-0.10"),
        _row("rules+gate", error="timeout"),
    ]
    stats = summarize.per_condition_stats(rows)
    assert stats["rules+gate"]["n_runs"] == 4
    assert stats["rules+gate"]["hidden_pass_rate"] == pytest.approx(8 / 16)
    assert stats["rules+gate"]["mean_cost_usd"] == pytest.approx(0.20)
    assert stats["rules+gate"]["mean_turns"] == pytest.approx(50 / 4)
    assert stats["rules+gate"]["violations_per_100_lines"] == pytest.approx(0.5)


def test_test_condition_stats_filters_broken_runs() -> None:
    without_cost = _test_row("tests-gate", hidden_tests_passed="1")
    del without_cost["cost_usd"]
    rows = [
        _test_row("tests-gate", cost_usd="0.15", num_turns="6"),
        _test_row("tests-gate", hidden_tests_passed="0", hidden_tests_total="0", cost_usd="0.10"),
        _test_row("tests-gate", cost_usd="0", hidden_tests_passed="2"),
        without_cost,
    ]
    stats = summarize.test_condition_stats(rows)
    assert stats["tests-gate"]["n_runs"] == 3
    assert stats["tests-gate"]["hidden_pass_rate"] == pytest.approx(7 / 12)
    assert stats["tests-gate"]["mean_cost_usd"] == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("gate_metrics", "rg_metrics", "expected_verdict"),
    [
        pytest.param(
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.357, "mean_turns": 16.6},
            {"violations_per_100_lines": 0.04, "mean_cost_usd": 0.369, "mean_turns": 14.6},
            "not worth it",
            id="higher-violations-and-higher-cost-despite-fewer-turns",
        ),
        pytest.param(
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.40, "mean_turns": 16.0},
            {"violations_per_100_lines": 0.05, "mean_cost_usd": 0.25, "mean_turns": 10.0},
            "not worth it",
            id="higher-violations-even-with-lower-cost",
        ),
        pytest.param(
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.40, "mean_turns": 16.0},
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.45, "mean_turns": 12.0},
            "not worth it",
            id="equal-violations-higher-cost-fewer-turns",
        ),
        pytest.param(
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.35, "mean_turns": 12.0},
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.35, "mean_turns": 12.0},
            "not worth it",
            id="equal-violations-and-equal-cost-tie",
        ),
        pytest.param(
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.40, "mean_turns": 16.0},
            {"violations_per_100_lines": 0.0, "mean_cost_usd": 0.30, "mean_turns": 18.0},
            "worth it",
            id="equal-violations-strictly-lower-cost",
        ),
        pytest.param(
            {"violations_per_100_lines": 1.0, "mean_cost_usd": 0.30, "mean_turns": 12.0},
            {"violations_per_100_lines": 0.70, "mean_cost_usd": 0.45, "mean_turns": 15.0},
            "worth it",
            id="thirty-percent-violation-reduction",
        ),
    ],
)
def test_decision_rules_gate_worth_it_contract(
    gate_metrics: dict[str, float],
    rg_metrics: dict[str, float],
    expected_verdict: str,
) -> None:
    lines = summarize.decision({"gate": gate_metrics, "rules+gate": rg_metrics})
    assert f"**Decision: rules are {expected_verdict} on top of the gate.**" in lines[1]
