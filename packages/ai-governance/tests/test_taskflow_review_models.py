"""Model of review rounds: an empty or blank model launches with the provider's default.

Hermetic: same fakes as ``test_taskflow_review`` (no ``gh``, fake Orca CLI).
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import shlex

import pytest
from orca_fakes import TASK, OrcaWorld, flag, world
from test_taskflow_review import PR_ONE, REVIEW, _settle, github


def _launched(output: str) -> list[str]:
    lines = [line for line in output.strip().splitlines() if "worker-start" in line]
    assert len(lines) == 1, output
    return shlex.split(lines[0])


def _model_flag(argv: list[str]) -> str:
    return flag(argv, "--model") if "--model" in argv else ""


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        pytest.param((), "gpt-6.2-sol", id="no-model-takes-provider-default"),
        pytest.param(("--model", "   "), "gpt-6.2-sol", id="blank-model-counts-as-empty"),
        pytest.param(("--model", "gpt-other"), "gpt-other", id="explicit-model-is-kept"),
    ],
)
def test_reviewer_round_launches_with_a_model(
    world: OrcaWorld, github, extra: tuple[str, ...], expected: str
) -> None:
    result = world.run("review", TASK, "open", "--pr", PR_ONE, "--agent", "codex", *extra)
    assert result.code == 0, result.text
    assert world.dispatch_json(1)["model"] == expected
    assert _model_flag(_launched(result.out)) == expected


def test_reviewer_of_a_provider_without_default_stays_empty(world: OrcaWorld, github) -> None:
    result = world.run("review", TASK, "open", "--pr", PR_ONE, "--agent", "claude")
    assert result.code == 0, result.text
    assert world.dispatch_json(1)["model"] == ""
    assert _model_flag(_launched(result.out)) == ""


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        pytest.param((), "gpt-6.2-sol", id="no-model-takes-provider-default"),
        pytest.param(("--model", " "), "gpt-6.2-sol", id="blank-model-counts-as-empty"),
        pytest.param(("--model", "gpt-other"), "gpt-other", id="explicit-model-is-kept"),
    ],
)
def test_judge_round_launches_with_a_model(
    world: OrcaWorld, github, extra: tuple[str, ...], expected: str
) -> None:
    opened = world.run("review", TASK, "open", "--pr", PR_ONE, "--agent", "claude")
    assert opened.code == 0, opened.text
    _settle(world, 1, "claude", REVIEW)
    result = world.run("review", TASK, "judge", "--agent", "codex", *extra)
    assert result.code == 0, result.text
    assert world.dispatch_json(2)["model"] == expected
    assert _model_flag(_launched(result.out)) == expected
