from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

from spec.core.ownership import OwnershipManifest
from spec.core.paths import PathBoundary
from spec.core.write import SafeWriter

if TYPE_CHECKING:
    from spec.governance.audit import AuditReport


@dataclass(frozen=True)
class InitializationResult:
    created: tuple[str, ...]
    existing: tuple[str, ...]


class ProjectGovernance:
    """Initialize only the repository-local sources of governance truth."""

    policy_path = ".spec/policy.json"
    verification_path = ".spec/verification.json"

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)

    def initialize(self) -> InitializationResult:
        manifest = OwnershipManifest(self.boundary.root)
        writer = SafeWriter(self.boundary.root, manifest)
        created: list[str] = []
        existing: list[str] = []
        documents = (
            (self.policy_path, self._policy()),
            (self.verification_path, {"schema_version": 1, "checks": []}),
        )
        for relative, document in documents:
            target = self.boundary.resolve(relative)
            if target.exists():
                existing.append(relative)
                continue
            writer.write(relative, json.dumps(document, indent=2) + "\n")
            created.append(relative)
        return InitializationResult(created=tuple(created), existing=tuple(existing))

    def audit(self) -> AuditReport:
        from spec.governance.audit import ProjectAuditor

        return ProjectAuditor(self.boundary.root).audit()

    @staticmethod
    def _policy() -> dict[str, object]:
        return {
            "schema_version": 1,
            "scope": "ai-governance-and-sdd",
            "workflow": ["spec", "plan", "tasks", "work", "verify", "finish"],
            "invariants": {
                "preserve_unrelated_user_changes": True,
                "require_explicit_scope": True,
                "require_recorded_verification": True,
                "allow_global_configuration_mutation": False,
                "allow_skipped_required_checks_to_pass": False,
            },
            "excluded_domains": [
                "kubernetes",
                "workspace-provisioning",
                "local-service-orchestration",
                "devops-automation",
            ],
        }
