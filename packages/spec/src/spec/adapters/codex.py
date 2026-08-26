from __future__ import annotations

from pathlib import Path

from spec.core.ownership import DeleteResult, OwnershipManifest
from spec.core.write import SafeWriter, WriteResult


class CodexAdapter:
    """Generate the repository-level file Codex actually discovers."""

    target = "AGENTS.md"

    def __init__(self, root: str | Path) -> None:
        self.root = root

    def install(self) -> WriteResult:
        manifest = OwnershipManifest(self.root)
        return SafeWriter(self.root, manifest).write(
            self.target,
            self.render(),
            mode=0o644,
        )

    def uninstall(self, *, dry_run: bool = True) -> DeleteResult:
        return OwnershipManifest(self.root).delete_owned(self.target, dry_run=dry_run)

    @staticmethod
    def render() -> str:
        return """# Spec governance for coding agents

## Product boundary

- This repository uses Spec for AI governance and Spec-Driven Development only.
- Do not introduce Kubernetes, workspace provisioning, local-service orchestration, or
  general DevOps behavior into the Spec core.

## Required workflow

1. Read `.spec/state.json` and the active artifacts under `.spec/specs/` before changing code.
2. Keep implementation inside the active spec, plan, and task scope.
3. Preserve unrelated user changes and never mutate global agent configuration.
4. Use explicit argv commands from `.spec/verification.json`; never reinterpret them as shell.
5. Run `spec verify` and report its exact status. `SKIPPED`, `INCOMPLETE`, and `ERROR` are not PASS.
6. Run `spec finish` only after recorded verification is PASS.

## Evidence and state

- Treat `.spec/evidence/` as immutable execution evidence.
- Do not edit `.spec/state.json` or `.spec/ownership.json` by hand.
- Do not claim tests, review, implementation, or cleanup happened without observable evidence.
"""
