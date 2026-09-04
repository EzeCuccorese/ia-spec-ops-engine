import json
from pathlib import Path

import pytest

from spec.core.result import CheckStatus
from spec.verify.engine import (
    CommandCheck,
    ConfigurationError,
    ProcessOutcome,
    VerificationEngine,
    load_checks,
)


class FakeRunner:
    def __init__(self, outcomes: dict[str, ProcessOutcome | FileNotFoundError]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[tuple[str, ...], Path, int]] = []

    def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome:
        self.calls.append((command, cwd, timeout_seconds))
        outcome = self.outcomes[command[0]]
        if isinstance(outcome, FileNotFoundError):
            raise outcome
        return outcome


def test_successful_command_is_pass_with_bounded_evidence(tmp_path: Path) -> None:
    runner = FakeRunner({"pytest": ProcessOutcome(0, "ok\n", "", 12)})
    check = CommandCheck(id="tests", command=("pytest", "-q"), timeout_seconds=30)

    report = VerificationEngine(tmp_path, runner=runner).run((check,))

    assert report.status is CheckStatus.PASS
    assert report.checks[0].evidence["command"] == ["pytest", "-q"]
    assert report.checks[0].evidence["exit_code"] == 0
    assert runner.calls == [(check.command, tmp_path.resolve(), 30)]


def test_nonzero_required_command_fails_report(tmp_path: Path) -> None:
    runner = FakeRunner({"pytest": ProcessOutcome(1, "", "failed", 8)})

    report = VerificationEngine(tmp_path, runner=runner).run(
        (CommandCheck(id="tests", command=("pytest",)),)
    )

    assert report.status is CheckStatus.FAIL
    assert report.checks[0].status is CheckStatus.FAIL


def test_missing_required_executable_is_incomplete_not_pass(tmp_path: Path) -> None:
    runner = FakeRunner({"ruff": FileNotFoundError("ruff")})

    report = VerificationEngine(tmp_path, runner=runner).run(
        (CommandCheck(id="lint", command=("ruff", "check", ".")),)
    )

    assert report.status is CheckStatus.INCOMPLETE
    assert report.checks[0].status is CheckStatus.INCOMPLETE


def test_empty_check_set_is_incomplete(tmp_path: Path) -> None:
    report = VerificationEngine(tmp_path, runner=FakeRunner({})).run(())

    assert report.status is CheckStatus.INCOMPLETE
    assert report.checks[0].id == "configuration"


def test_load_checks_rejects_shell_string_and_duplicate_ids(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {"id": "tests", "command": "pytest -q"},
                    {"id": "tests", "command": ["pytest"]},
                ],
            }
        )
    )

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_parses_explicit_argv(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "tests",
                        "command": ["python", "-m", "pytest", "-q"],
                        "required": True,
                        "timeout_seconds": 45,
                    }
                ],
            }
        )
    )

    assert load_checks(tmp_path) == (
        CommandCheck(
            id="tests",
            command=("python", "-m", "pytest", "-q"),
            required=True,
            timeout_seconds=45,
        ),
    )
