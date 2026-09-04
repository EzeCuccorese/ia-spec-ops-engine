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
3. Follow Test-First methodology (Uncle Bob's Three Laws of TDD): write/update unit and integration tests before or alongside logic.
4. Execute verification using explicit commands from `.spec/verification.json` (e.g. `spec verify`).
5. `SKIPPED`, `INCOMPLETE`, and `ERROR` are never considered `PASS`.
6. Run `spec finish` only after recorded verification status is `PASS`, scenario traceability is complete, and user authorizes.

## Recognized SDD Commands & Workflows
When the user mentions or asks for spec-new, spec-plan, spec-verify, or spec-finish:
- spec-new <name>: Execute spec new "<name>", stop immediately, conduct the mandatory requirements interview, then write .spec/specs/<slug>/spec.md with @s tagged Gherkin scenarios.
- spec-plan: Execute spec plan and spec tasks, stop immediately, conduct the architectural review, then write plan.md and tasks.md.
- spec-verify: Execute spec verify and audit the verification evidence.
- spec-finish: Upon verified PASS status and explicit human sign-off, execute spec finish.

## Craftsmanship Disciplines (Uncle Bob Principles)
- **Three Laws of TDD**:
  1. Do not write production code unless it is to pass a failing unit test.
  2. Do not write more of a unit test than is sufficient to fail (compilation/import errors count as failure).
  3. Do not write more production code than is sufficient to pass the one failing unit test.
- **Gherkin as Executable Contract**:
  - Acceptance criteria in `spec.md` must be tagged with `@s1`, `@s2`...
  - Every `@s<n>` scenario must map to at least one test. `spec verify` audits coverage and `spec finish` blocks if scenarios lack test mapping.
- **Anti-Teléfono-Descompuesto (Disk-First Memory)**:
  - During `spec work`, log TDD cycles and scenario mappings in `.spec/specs/<slug>/work.md`.
  - Keep chat responses concise with single-line references to disk artifacts instead of dumping voluminous diffs or logs into the context window.
- **The Judge (Pruning Over Drafting)**:
  - Generating code is cheap; judgment is the scarce resource. Prune speculative abstractions, dead code, and unrequested scope before requesting verification.

## Platform Support & Priority
1. **Google Antigravity**: Primary runtime (Skills, subagent teams, interactive question modals `ask_question`).
2. **Anthropic Claude Code**: Secondary runtime (`CLAUDE.md`, `.claude/agents/`, `AskFollowupQuestion`).
3. **Codex / Universal Agents**: Tertiary runtime (`AGENTS.md` standard).

## Agent Tooling for Autonomous TDD Loop
- Run `spec test-assist --next`: Returns the exact next uncovered `@s` scenario to implement with TDD.
- Run `spec mutate <file>`: Validates that unit tests detect bugs (killing mutants) without false positives.
- Run `spec judge`: Prepares the craftsmanship audit context for reviewing code bloat and scenario coverage.

## Mandatory Human Gates & Inquiry (Modal Popups)
- Spec Phase: Conduct the requirements interview using the platform's interactive modal tool (`ask_question` / `AskFollowupQuestion`). Never dump open questions as chat text or assume default designs. Wait for modal submission before drafting spec.md.
- Plan Phase: Detail architecture, affected files, and test-first strategy. Resolve technical tradeoffs via interactive modal. Never start coding without explicit user sign-off.
- Verify & Finish: Never seal features without recorded PASS status and user authorization.

## Safety & Invariants
- Treat `.spec/evidence/` as immutable execution evidence.
- Do not edit `.spec/state.json` or `.spec/ownership.json` by hand.
- Do not add AI attribution, robot emojis, or AI-generated mentions to commit messages or PRs.
- Never modify files outside the agreed specification scope without user confirmation.
"""
