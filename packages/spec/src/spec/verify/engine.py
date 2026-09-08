from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from spec.core.paths import PathBoundary
from spec.core.result import CheckResult, CheckStatus, VerificationReport


class ConfigurationError(ValueError):
    """Verification configuration is invalid or unsafe to interpret."""


@dataclass(frozen=True)
class CommandCheck:
    id: str
    command: tuple[str, ...]
    required: bool = True
    timeout_seconds: int = 300


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class Runner(Protocol):
    def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome: ...


class SubprocessRunner:
    """Execute explicit argv without a shell or inherited stdin."""

    def run(self, command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> ProcessOutcome:
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return ProcessOutcome(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
        )


class VerificationEngine:
    max_output_chars = 250_000

    def __init__(
        self,
        root: str | Path,
        *,
        runner: Runner | None = None,
        max_output_chars: int | None = None,
    ) -> None:
        self.root = PathBoundary(root).root
        self.runner = runner or SubprocessRunner()
        if max_output_chars is not None:
            self.max_output_chars = max_output_chars

    def run(self, checks: tuple[CommandCheck, ...]) -> VerificationReport:
        if not checks:
            return VerificationReport(
                checks=(
                    CheckResult(
                        id="configuration",
                        status=CheckStatus.INCOMPLETE,
                        summary="No verification checks are configured",
                    ),
                )
            )
        return VerificationReport(checks=tuple(self._run_one(check) for check in checks))

    def _run_one(self, check: CommandCheck) -> CheckResult:
        evidence: dict[str, object] = {
            "command": list(check.command),
            "cwd": str(self.root),
            "timeout_seconds": check.timeout_seconds,
        }
        try:
            outcome = self.runner.run(check.command, self.root, check.timeout_seconds)
        except FileNotFoundError:
            return CheckResult(
                id=check.id,
                status=CheckStatus.INCOMPLETE,
                required=check.required,
                summary=f"Executable is unavailable: {check.command[0]}",
                evidence=evidence,
            )
        except subprocess.TimeoutExpired as exc:
            evidence.update(
                {
                    "stdout": self._bounded(_text(exc.stdout)),
                    "stderr": self._bounded(_text(exc.stderr)),
                }
            )
            return CheckResult(
                id=check.id,
                status=CheckStatus.ERROR,
                required=check.required,
                summary=f"Command timed out after {check.timeout_seconds} seconds",
                evidence=evidence,
            )
        except OSError as exc:
            evidence["error_type"] = type(exc).__name__
            return CheckResult(
                id=check.id,
                status=CheckStatus.ERROR,
                required=check.required,
                summary=f"Command could not be executed: {exc}",
                evidence=evidence,
            )

        evidence.update(
            {
                "exit_code": outcome.exit_code,
                "duration_ms": outcome.duration_ms,
                "stdout": self._bounded(outcome.stdout),
                "stderr": self._bounded(outcome.stderr),
            }
        )
        status = CheckStatus.PASS if outcome.exit_code == 0 else CheckStatus.FAIL
        summary = "Command passed" if status is CheckStatus.PASS else "Command exited non-zero"
        return CheckResult(
            id=check.id,
            status=status,
            required=check.required,
            summary=summary,
            evidence=evidence,
        )

    def _bounded(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        removed = len(value) - self.max_output_chars
        return f"{value[: self.max_output_chars]}\n...[truncated {removed} characters]"


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def load_checks(root: str | Path) -> tuple[CommandCheck, ...]:
    boundary = PathBoundary(root)
    config_path = boundary.resolve(".spec/verification.json")
    if not config_path.exists():
        return ()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read verification config: {config_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigurationError("Verification config requires schema_version 1")
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, list):
        raise ConfigurationError("Verification config checks must be a list")

    checks: list[CommandCheck] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_checks):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Check {index} must be an object")
        check_id = raw.get("id")
        command = raw.get("command")
        required = raw.get("required", True)
        timeout = raw.get("timeout_seconds", 300)
        if not isinstance(check_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", check_id):
            raise ConfigurationError(f"Check {index} has an invalid id")
        if check_id in seen:
            raise ConfigurationError(f"Duplicate verification check id: {check_id}")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(arg, str) or not arg for arg in command)
        ):
            raise ConfigurationError(f"Check {check_id} command must be a non-empty argv list")
        if not isinstance(required, bool):
            raise ConfigurationError(f"Check {check_id} required must be boolean")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ConfigurationError(f"Check {check_id} timeout_seconds must be between 1 and 3600")
        seen.add(check_id)
        checks.append(
            CommandCheck(
                id=check_id,
                command=tuple(command),
                required=required,
                timeout_seconds=timeout,
            )
        )
    return tuple(checks)
