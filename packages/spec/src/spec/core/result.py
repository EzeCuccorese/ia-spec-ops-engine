from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: CheckStatus
    required: bool = True
    summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationReport:
    checks: tuple[CheckResult, ...]

    @property
    def status(self) -> CheckStatus:
        required = tuple(check for check in self.checks if check.required)
        if not required:
            return CheckStatus.INCOMPLETE
        if any(check.status is CheckStatus.ERROR for check in required):
            return CheckStatus.ERROR
        if any(check.status is CheckStatus.FAIL for check in required):
            return CheckStatus.FAIL
        if any(
            check.status in {CheckStatus.INCOMPLETE, CheckStatus.SKIPPED} for check in required
        ):
            return CheckStatus.INCOMPLETE
        if all(check.status is CheckStatus.PASS for check in required):
            return CheckStatus.PASS
        return CheckStatus.INCOMPLETE

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "passed": self.passed,
            "checks": [
                {
                    "id": check.id,
                    "status": check.status.value,
                    "required": check.required,
                    "summary": check.summary,
                    "evidence": check.evidence,
                }
                for check in self.checks
            ],
        }
