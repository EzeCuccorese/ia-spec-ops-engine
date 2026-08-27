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
        return """# Spec Governance for Coding Agents

## Required Workflow
1. Read `.spec/state.json` and active artifacts under `.spec/specs/` before changing code.
2. Keep implementation strictly inside the active spec, plan, and task scope.
3. Follow Test-First methodology: write/update unit and integration tests before or alongside logic.
4. Execute verification using explicit commands from `.spec/verification.json` (e.g. `spec verify`).
5. `SKIPPED`, `INCOMPLETE`, and `ERROR` are never considered `PASS`.
6. Run `spec finish` only after recorded verification status is `PASS`.

## Safety & Invariants
- Treat `.spec/evidence/` as immutable execution evidence.
- Do not edit `.spec/state.json` or `.spec/ownership.json` by hand.
- Do not add AI attribution, robot emojis, or AI-generated mentions to commit messages or PRs.
- Never modify files outside the agreed specification scope without user confirmation.
"""
