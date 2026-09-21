import json
import subprocess
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


def test_command_timeout_is_error_with_bounded_evidence(tmp_path: Path) -> None:
    class TimeoutRunner:
        def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome:
            raise subprocess.TimeoutExpired(
                cmd=command, timeout=timeout_seconds, output=b"out", stderr=None
            )

    report = VerificationEngine(tmp_path, runner=TimeoutRunner()).run(
        (CommandCheck(id="tests", command=("pytest",), timeout_seconds=5),)
    )

    assert report.status is CheckStatus.ERROR
    assert report.checks[0].status is CheckStatus.ERROR
    assert "timed out after 5" in report.checks[0].summary
    assert report.checks[0].evidence["stdout"] == "out"
    assert report.checks[0].evidence["stderr"] == ""


def test_command_timeout_with_str_output_is_passed_through(tmp_path: Path) -> None:
    class TimeoutRunner:
        def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome:
            raise subprocess.TimeoutExpired(
                cmd=command, timeout=timeout_seconds, output="out", stderr="err"
            )

    report = VerificationEngine(tmp_path, runner=TimeoutRunner()).run(
        (CommandCheck(id="tests", command=("pytest",)),)
    )

    assert report.checks[0].evidence["stdout"] == "out"
    assert report.checks[0].evidence["stderr"] == "err"


def test_command_os_error_is_error(tmp_path: Path) -> None:
    class BrokenRunner:
        def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome:
            raise OSError("boom")

    report = VerificationEngine(tmp_path, runner=BrokenRunner()).run(
        (CommandCheck(id="tests", command=("pytest",)),)
    )

    assert report.status is CheckStatus.ERROR
    assert report.checks[0].evidence["error_type"] == "OSError"
    assert "could not be executed" in report.checks[0].summary


def test_output_is_truncated_beyond_max_output_chars(tmp_path: Path) -> None:
    runner = FakeRunner({"pytest": ProcessOutcome(0, "x" * 20, "", 1)})

    report = VerificationEngine(tmp_path, runner=runner, max_output_chars=5).run(
        (CommandCheck(id="tests", command=("pytest",)),)
    )

    stdout = report.checks[0].evidence["stdout"]
    assert stdout.startswith("xxxxx\n...[truncated")
    assert "15 characters" in stdout


def test_load_checks_returns_empty_tuple_when_config_absent(tmp_path: Path) -> None:
    assert load_checks(tmp_path) == ()


def test_load_checks_rejects_unreadable_json(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text("{not json")

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_missing_schema_version(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"checks": []}))

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_non_list_checks(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"schema_version": 1, "checks": "nope"}))

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_non_dict_check(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"schema_version": 1, "checks": ["nope"]}))

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_invalid_id(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"schema_version": 1, "checks": [{"id": "Bad Id", "command": ["x"]}]})
    )

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_empty_command(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"schema_version": 1, "checks": [{"id": "a", "command": []}]}))

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_non_bool_required(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [{"id": "a", "command": ["x"], "required": "yes"}],
            }
        )
    )

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_out_of_range_timeout(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [{"id": "a", "command": ["x"], "timeout_seconds": 0}],
            }
        )
    )

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_bool_timeout(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [{"id": "a", "command": ["x"], "timeout_seconds": True}],
            }
        )
    )

    with pytest.raises(ConfigurationError):
        load_checks(tmp_path)


def test_load_checks_rejects_duplicate_ids(tmp_path: Path) -> None:
    config = tmp_path / ".spec/verification.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {"id": "tests", "command": ["pytest"]},
                    {"id": "tests", "command": ["pytest", "-q"]},
                ],
            }
        )
    )

    with pytest.raises(ConfigurationError, match="Duplicate"):
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
