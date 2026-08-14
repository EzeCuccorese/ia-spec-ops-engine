"""
Multi-Agent Execution Harness Invariants & Immutability Contracts.

Defines immutable data structures, constants, and metric evaluation routines
for the SDD multi-agent execution harness.
"""

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
import time
from typing import List, Dict, Any, Iterable, Union, Set

# Core Harness Constants
DEFAULT_MAX_STEPS: int = 25
DEFAULT_DRIFT_PENALTY_THRESHOLD: float = 0.35
DEFAULT_TIMEOUT_SECONDS: int = 300


@dataclass(frozen=True)
class HarnessConfig:
    """
    Immutable configuration for the multi-agent execution harness.
    """
    max_steps: int = DEFAULT_MAX_STEPS
    drift_penalty_threshold: float = DEFAULT_DRIFT_PENALTY_THRESHOLD
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    allowed_tool_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HarnessConfig":
        return cls(
            max_steps=int(data.get("max_steps", DEFAULT_MAX_STEPS)),
            drift_penalty_threshold=float(data.get("drift_penalty_threshold", DEFAULT_DRIFT_PENALTY_THRESHOLD)),
            timeout_seconds=int(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            allowed_tool_actions=list(data.get("allowed_tool_actions", [])),
        )


@dataclass(frozen=True)
class VerificationPayload:
    """
    Immutable payload representing automated verification statuses across static and dynamic checks.
    """
    passed: bool = False
    linter_status: str = "PENDING"
    test_status: str = "PENDING"
    confirmation_read_status: str = "PENDING"
    security_status: str = "PENDING"
    remediation_instructions: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationPayload":
        return cls(
            passed=bool(data.get("passed", False)),
            linter_status=str(data.get("linter_status", "PENDING")),
            test_status=str(data.get("test_status", "PENDING")),
            confirmation_read_status=str(data.get("confirmation_read_status", "PENDING")),
            security_status=str(data.get("security_status", "PENDING")),
            remediation_instructions=str(data.get("remediation_instructions", "")),
            details=dict(data.get("details", {})),
        )


@dataclass(frozen=True)
class TaskResult:
    """
    Immutable task execution result recorded by worker or QA agents.
    """
    task_id: str
    role: str = "WORKER"
    status: str = "PASS"  # "SUCCESS", "PASS", "FAIL", "REMEDIATION_REQUIRED"
    executed_steps: int = 0
    scope_drift_penalty: float = 0.0
    summary: str = ""
    details: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        valid_statuses = {"SUCCESS", "PASS", "FAIL", "REMEDIATION_REQUIRED"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status '{self.status}'. Must be one of {valid_statuses}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        return cls(
            task_id=str(data["task_id"]),
            role=str(data.get("role", "WORKER")),
            status=str(data.get("status", "PASS")),
            executed_steps=int(data.get("executed_steps", 0)),
            scope_drift_penalty=float(data.get("scope_drift_penalty", 0.0)),
            summary=str(data.get("summary", "")),
            details=str(data.get("details", "")),
            timestamp=float(data.get("timestamp", time.time())),
        )


def _normalize_path(p: Union[str, Path]) -> str:
    path_obj = Path(p)
    return str(path_obj.as_posix())


def calculate_scope_drift_penalty(
    modified_files: Iterable[Union[str, Path]],
    expected_files: Iterable[Union[str, Path]],
    executed_steps: int,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> float:
    """
    Calculates the Scope Drift Penalty metric (between 0.0 and 1.0+).

    Evaluation breakdown:
    - Unexpected Modified Files Penalty: Ratio of unexpected files modified relative to total modified files.
    - Executed Steps Overhead Penalty: Penalty imposed when executed steps exceed standard limits.

    Returns:
        float: Scope drift penalty score (0.0 to 1.0+). Scores > 0.35 fail the invariant check.
    """
    mod_set: Set[str] = {_normalize_path(f) for f in modified_files}
    exp_set: Set[str] = {_normalize_path(f) for f in expected_files} if expected_files is not None else set()

    # 1. Unexpected files penalty
    if mod_set and exp_set:
        unexpected = mod_set - exp_set
        file_drift = len(unexpected) / len(mod_set)
    elif mod_set and not exp_set:
        file_drift = 1.0 if expected_files is not None else 0.0
    else:
        file_drift = 0.0

    # 2. Executed steps overhead penalty
    half_steps = max(1, max_steps / 2.0)
    if executed_steps > half_steps:
        step_excess = (executed_steps - half_steps) / half_steps
        step_penalty = max(0.0, step_excess * 0.25)
    else:
        step_penalty = 0.0

    # Combine file drift (weight 0.75) and step penalty (weight 0.25+)
    total_penalty = (file_drift * 0.75) + step_penalty

    # If steps exceed max_steps completely, impose an immediate penalty bump
    if executed_steps > max_steps:
        total_penalty += 0.5

    return round(total_penalty, 4)
