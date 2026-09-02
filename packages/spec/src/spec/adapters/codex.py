from __future__ import annotations

import re
from pathlib import Path

from spec.core.ownership import DeleteResult, OwnershipManifest
from spec.core.paths import PathBoundary
from spec.core.write import SafeWriter, WriteResult

START_MARKER = "<!-- spec:governance -->"
END_MARKER = "<!-- /spec:governance -->"
PATTERN = re.compile(
    rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)


class CodexAdapter:
    """Generate and inject the repository-level governance reference into AGENTS.md."""

    target = "AGENTS.md"
    governance_file = ".spec/governance.md"

    def __init__(self, root: str | Path) -> None:
        self.root = root
        self.boundary = PathBoundary(root)

    def install(self) -> WriteResult:
        manifest = OwnershipManifest(self.root)
        writer_res = SafeWriter(self.root, manifest).write(
            self.governance_file,
            self.render(),
            mode=0o644,
        )

        agents_path = self.boundary.resolve(self.target)
        content = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        block = f"{START_MARKER}\n@.spec/governance.md\n{END_MARKER}\n"

        if START_MARKER in content and END_MARKER in content:
            new_content = PATTERN.sub(block, content)
        else:
            stripped = content.rstrip()
            new_content = f"{stripped}\n\n{block}" if stripped else block

        agents_path.write_text(new_content, encoding="utf-8")
        return writer_res

    def uninstall(self, *, dry_run: bool = True) -> DeleteResult:
        manifest = OwnershipManifest(self.root)
        if manifest.get(self.governance_file) is not None:
            del_res = manifest.delete_owned(self.governance_file, dry_run=dry_run)
        else:
            del_res = DeleteResult(path=self.governance_file, deleted=False, would_delete=False)

        agents_path = self.boundary.resolve(self.target)
        if agents_path.exists() and not dry_run:
            content = agents_path.read_text(encoding="utf-8")
            if START_MARKER in content and END_MARKER in content:
                cleaned = PATTERN.sub("", content)
                if not cleaned.strip():
                    agents_path.unlink(missing_ok=True)
                else:
                    agents_path.write_text(cleaned.rstrip() + "\n", encoding="utf-8")

        return del_res

    @staticmethod
    def render() -> str:
        return """# Spec Governance for Coding Agents

## Required Workflow
1. Read `.spec/state.json` and active artifacts under `.spec/specs/` before changing code.
2. Keep implementation strictly inside the active spec, plan, and task scope.
3. Follow Test-First methodology: write/update unit and integration tests before or alongside logic.
4. Execute verification using explicit commands from `.spec/verification.json` (e.g. `spec verify`).
5. `SKIPPED`, `INCOMPLETE`, and `ERROR` are never considered `PASS`.
6. Run `spec finish` only after recorded verification status is `PASS` and user authorizes.

## Recognized SDD Commands & Workflows
When the user mentions or asks for spec-new, spec-plan, spec-verify, or spec-finish:
- spec-new <name>: Execute spec new "<name>", stop immediately, conduct the mandatory requirements interview, then write .spec/specs/<slug>/spec.md.
- spec-plan: Execute spec plan and spec tasks, stop immediately, conduct the architectural review, then write plan.md and tasks.md.
- spec-verify: Execute spec verify and audit the verification evidence.
- spec-finish: Upon verified PASS status and explicit human sign-off, execute spec finish.

## Mandatory Human Gates & Inquiry
- Spec Phase: Conduct an incisive requirements interview covering edge cases, failure modes, and data contracts. Never assume defaults or advance to planning without explicit user approval.
- Plan Phase: Detail architecture, affected files, and test-first strategy. Never start coding without explicit user sign-off.
- Verify & Finish: Never seal features without recorded PASS status and user authorization.

## Safety & Invariants
- Treat `.spec/evidence/` as immutable execution evidence.
- Do not edit `.spec/state.json` or `.spec/ownership.json` by hand.
- Do not add AI attribution, robot emojis, or AI-generated mentions to commit messages or PRs.
- Never modify files outside the agreed specification scope without user confirmation.
"""
