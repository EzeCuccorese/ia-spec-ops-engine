from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from spec.core.ownership import sha256_file
from spec.core.paths import PathBoundary
from spec.core.result import CheckResult, CheckStatus, VerificationReport


class WorkflowError(RuntimeError):
    """Base error for specification lifecycle operations."""


class InvalidTransitionError(WorkflowError):
    """The requested transition lacks required state or artifacts."""


class ArtifactExistsError(WorkflowError):
    """Creating an artifact would overwrite existing user content."""


class CorruptStateError(WorkflowError):
    """Persisted workflow state is invalid or unsupported."""


class Stage(StrEnum):
    SPEC = "spec"
    PLAN = "plan"
    TASKS = "tasks"
    WORK = "work"
    VERIFY = "verify"
    COMPLETE = "complete"


@dataclass(frozen=True)
class WorkflowSnapshot:
    feature: str
    stage: Stage
    updated_at: str
    verification_status: CheckStatus | None = None
    evidence_path: str | None = None


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    if not slug:
        raise ValueError("Feature name must contain at least one letter or number")
    return slug


def compute_tree_fingerprint(root: str | Path) -> str:
    """Computes deterministic SHA-256 fingerprint of repository tree, excluding volatile paths."""
    root_path = Path(root).resolve()
    if not root_path.exists():
        return hashlib.sha256(b"").hexdigest()

    excluded_dirs = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".specops",
    }

    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        rel_dir = Path(dirpath).relative_to(root_path)

        if rel_dir == Path(".spec") and "evidence" in dirnames:
            dirnames.remove("evidence")

        for f in filenames:
            full_path = Path(dirpath, f)
            rel_file = full_path.relative_to(root_path).as_posix()
            if rel_file == ".spec/state.json" or (
                rel_dir == Path(".spec") and (f.startswith(".state-") or f.startswith(".state."))
            ):
                continue
            if rel_file == ".spec/evidence" or rel_file.startswith(".spec/evidence/"):
                continue

            if full_path.is_file():
                entries.append((rel_file, sha256_file(full_path)))

    entries.sort(key=lambda item: item[0])
    hasher = hashlib.sha256()
    for rel_path, file_hash in entries:
        hasher.update(f"{rel_path}:{file_hash}\n".encode())
    return hasher.hexdigest()


class Workflow:
    schema_version = 1

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.state_path = self.boundary.resolve(".spec/state.json")

    def status(self) -> WorkflowSnapshot | None:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != self.schema_version:
                raise CorruptStateError("Unsupported workflow state schema")
            return WorkflowSnapshot(
                feature=str(data["active_feature"]),
                stage=Stage(data["stage"]),
                updated_at=str(data["updated_at"]),
                verification_status=(
                    CheckStatus(data["verification_status"])
                    if data.get("verification_status") is not None
                    else None
                ),
                evidence_path=(
                    str(data["evidence_path"]) if data.get("evidence_path") is not None else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptStateError(f"Invalid workflow state: {self.state_path}") from exc

    def feature_dir(self, feature: str) -> Path:
        return self.boundary.resolve(f".spec/specs/{slugify(feature)}")

    def create_spec(self, name: str, description: str = "") -> WorkflowSnapshot:
        feature = slugify(name)
        directory = self.feature_dir(feature)
        spec_path = directory / "spec.md"
        current = self.status()
        if current is not None and current.stage is not Stage.COMPLETE:
            if current.feature != feature:
                raise InvalidTransitionError(
                    f"Feature {current.feature} is already active at stage {current.stage}"
                )
            raise ArtifactExistsError(
                f"Spec already exists and will not be overwritten: {spec_path}"
            )
        if spec_path.exists():
            if current is None:
                self._require_nonempty(spec_path, "spec.md")
                return self._persist(feature, Stage.SPEC)
            raise ArtifactExistsError(
                f"Spec already exists and will not be overwritten: {spec_path}"
            )
        content = (
            f"# Spec: {name.strip()}\n\n"
            "## Purpose\n\n"
            f"{description.strip() or 'Describe the intended outcome.'}\n\n"
            "## Requirements\n\n"
            "- REQ-001: Define the observable behavior.\n\n"
            "## Acceptance criteria\n\n"
            "- [ ] AC-001: Add a verifiable acceptance criterion.\n\n"
            "## Out of scope\n\n"
            "- Document behavior intentionally excluded from this change.\n"
        )
        self._create_artifact(spec_path, content)
        return self._persist(feature, Stage.SPEC)

    def create_plan(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None:
            raise InvalidTransitionError("Cannot create a plan without an active spec")
        if current.stage is not Stage.SPEC:
            raise InvalidTransitionError(
                f"Plan requires stage spec, current stage is {current.stage}"
            )
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "spec.md", "spec.md")
        plan_path = directory / "plan.md"
        if plan_path.exists():
            self._require_nonempty(plan_path, "plan.md")
            return self._persist(current.feature, Stage.PLAN)
        content = (
            f"# Plan: {current.feature}\n\n"
            "## Approach\n\nDescribe the smallest viable implementation.\n\n"
            "## Contracts\n\nList changed interfaces, schemas, commands, and files.\n\n"
            "## Verification\n\nMap each requirement to executable evidence.\n\n"
            "## Risks and rollback\n\nDocument failure modes and recovery.\n"
        )
        self._create_artifact(plan_path, content)
        return self._persist(current.feature, Stage.PLAN)

    def create_tasks(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage is not Stage.PLAN:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(f"Tasks require an active plan; current stage is {actual}")
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "plan.md", "plan.md")
        tasks_path = directory / "tasks.md"
        if tasks_path.exists():
            self._require_nonempty(tasks_path, "tasks.md")
            return self._persist(current.feature, Stage.TASKS)
        content = (
            f"# Tasks: {current.feature}\n\n"
            "- [ ] T-001: Add a failing test or executable reproduction.\n"
            "- [ ] T-002: Implement the smallest change that satisfies the contract.\n"
            "- [ ] T-003: Run required verification and record evidence.\n"
        )
        self._create_artifact(tasks_path, content)
        return self._persist(current.feature, Stage.TASKS)

    def begin_work(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage not in {Stage.TASKS, Stage.COMPLETE}:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(f"Work requires active tasks; current stage is {actual}")
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "tasks.md", "tasks.md")
        work_path = directory / "work.md"
        if not work_path.exists():
            content = (
                f"# Work Log: {current.feature}\n\n"
                "## TDD Cycles (Red -> Green -> Refactor)\n"
                "- [ ] Cycle 1 (@s1): Failing test -> Minimal code -> Refactor\n\n"
                "## Traceability (@s -> test)\n"
                "<!-- Map each scenario tag to its implementing test. -->\n"
            )
            self._create_artifact(work_path, content)
        return self._persist(current.feature, Stage.WORK)

    def validate_can_verify(self) -> None:
        current = self.status()
        allowed = {Stage.WORK, Stage.VERIFY}
        if current is None or current.stage not in allowed:
            actual = current.stage.value if current else "none"
            raise InvalidTransitionError(
                f"Verification requires active work; current stage is {actual}"
            )

    def record_verification(
        self,
        report: VerificationReport,
        *,
        tree_fingerprint: str | None = None,
        verification_status: CheckStatus | None = None,
        trace_info: dict | None = None,
    ) -> tuple[WorkflowSnapshot, Path]:
        self.validate_can_verify()
        current = self.status()
        assert current is not None
        recorded_at = datetime.now(UTC)
        relative_path = Path(
            ".spec",
            "evidence",
            current.feature,
            f"verification-{recorded_at.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.json",
        )
        evidence_path = self.boundary.resolve(relative_path)
        actual_tree_fingerprint = (
            tree_fingerprint
            if tree_fingerprint is not None
            else compute_tree_fingerprint(self.boundary.root)
        )
        config_path = self.boundary.resolve(".spec/verification.json")
        config_hash = sha256_file(config_path) if config_path.is_file() else None

        effective_status = verification_status if verification_status is not None else report.status
        report_payload = report.to_dict()
        if verification_status is not None:
            report_payload["status"] = effective_status.value
            report_payload["passed"] = effective_status is CheckStatus.PASS

        payload = {
            "schema_version": 1,
            "feature": current.feature,
            "recorded_at": recorded_at.isoformat(),
            "tree_fingerprint": actual_tree_fingerprint,
            "verification_config_hash": config_hash,
            "status": effective_status.value,
            "passed": (effective_status is CheckStatus.PASS),
            "report": report_payload,
        }
        if trace_info is not None:
            payload["traceability"] = trace_info

        self._create_artifact(evidence_path, json.dumps(payload, indent=2) + "\n")
        snapshot = self._persist(
            current.feature,
            Stage.VERIFY,
            verification_status=effective_status,
            evidence_path=str(relative_path),
        )
        return snapshot, evidence_path

    def finish(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage is not Stage.VERIFY:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(
                f"Finish requires a verification attempt; current stage is {actual}"
            )
        if current.verification_status is not CheckStatus.PASS:
            raise InvalidTransitionError("Finish requires verification status PASS")
        if current.evidence_path is None:
            raise InvalidTransitionError("Finish requires recorded verification evidence")
        evidence_file = self.boundary.resolve(current.evidence_path)
        self._require_nonempty(evidence_file, "verification evidence")
        try:
            evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise InvalidTransitionError(
                f"Corrupt or invalid verification evidence: {evidence_file}"
            ) from exc
        if not isinstance(evidence_data, dict):
            raise InvalidTransitionError(
                f"Verification evidence must be a JSON object, got {type(evidence_data).__name__}"
            )
        if evidence_data.get("schema_version") != 1:
            raise InvalidTransitionError(
                f"Unsupported verification evidence schema version: {evidence_data.get('schema_version')}"
            )
        if evidence_data.get("feature") != current.feature:
            raise InvalidTransitionError(
                f"Verification evidence feature mismatch: expected {current.feature}, got {evidence_data.get('feature')}"
            )
        recorded_fingerprint = evidence_data.get("tree_fingerprint")
        if not isinstance(recorded_fingerprint, str) or not recorded_fingerprint.strip():
            raise InvalidTransitionError(
                "Verification evidence missing required valid tree_fingerprint"
            )
        current_fingerprint = compute_tree_fingerprint(self.boundary.root)
        if current_fingerprint != recorded_fingerprint:
            raise InvalidTransitionError(
                "Finish rejected: Working tree was modified after recorded verification (fingerprint mismatch)"
            )
        report_data = evidence_data.get("report")
        if not isinstance(report_data, dict) or report_data.get("status") != CheckStatus.PASS.value:
            raise InvalidTransitionError(
                "Verification evidence report is missing, invalid, or did not PASS"
            )

        recorded_config_hash = evidence_data.get("verification_config_hash")
        config_path = self.boundary.resolve(".spec/verification.json")
        current_config_hash = sha256_file(config_path) if config_path.is_file() else None
        if recorded_config_hash is not None and recorded_config_hash != current_config_hash:
            raise InvalidTransitionError(
                "Finish rejected: Verification configuration was modified after recorded verification (config hash mismatch)"
            )

        feature_dir = self.feature_dir(current.feature)
        spec_file = feature_dir / "spec.md"
        if spec_file.is_file():
            from spec.spec.trace import extract_scenarios, find_test_mappings

            scenarios = extract_scenarios(spec_file.read_text(encoding="utf-8"))
            if scenarios:
                check_objs = [
                    CheckResult(
                        id=c.get("id", ""),
                        status=CheckStatus(c.get("status", CheckStatus.FAIL.value)),
                        required=c.get("required", True),
                        summary=c.get("summary", ""),
                        evidence=c.get("evidence", {}),
                    )
                    for c in report_data.get("checks", [])
                    if isinstance(c, dict)
                ]
                report = find_test_mappings(
                    scenarios,
                    self.boundary.root,
                    feature_dir=feature_dir,
                    check_results=check_objs,
                )
                if not report.is_complete:
                    missing = ", ".join(report.uncovered)
                    raise InvalidTransitionError(
                        f"Finish rejected: Scenarios lacking test mapping: {missing}"
                    )

        return self._persist(
            current.feature,
            Stage.COMPLETE,
            verification_status=current.verification_status,
            evidence_path=current.evidence_path,
        )

    @staticmethod
    def _require_nonempty(path: Path, label: str) -> None:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise InvalidTransitionError(f"Required artifact is missing or empty: {label}")

    @staticmethod
    def _create_artifact(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ArtifactExistsError(
                f"Artifact exists and will not be overwritten: {path}"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def save_state(self, snapshot: WorkflowSnapshot) -> None:
        payload = {
            "schema_version": self.schema_version,
            "active_feature": snapshot.feature,
            "stage": snapshot.stage.value,
            "updated_at": snapshot.updated_at,
            "verification_status": (
                snapshot.verification_status.value if snapshot.verification_status else None
            ),
            "evidence_path": snapshot.evidence_path,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file_path = self.state_path.parent / ".state.lock"
        with open(lock_file_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                fd, temporary_name = tempfile.mkstemp(prefix=".state-", dir=self.state_path.parent)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(payload, stream, indent=2)
                        stream.write("\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, self.state_path)
                finally:
                    temporary.unlink(missing_ok=True)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _persist(
        self,
        feature: str,
        stage: Stage,
        *,
        verification_status: CheckStatus | None = None,
        evidence_path: str | None = None,
    ) -> WorkflowSnapshot:
        snapshot = WorkflowSnapshot(
            feature=feature,
            stage=stage,
            updated_at=datetime.now(UTC).isoformat(),
            verification_status=verification_status,
            evidence_path=evidence_path,
        )
        self.save_state(snapshot)
        return snapshot
