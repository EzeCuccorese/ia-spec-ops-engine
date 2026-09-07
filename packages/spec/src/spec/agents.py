from __future__ import annotations

import re
from pathlib import Path

from spec.core.ownership import DeleteResult, FileChangedError, OwnershipManifest, sha256_file
from spec.core.paths import PathBoundary
from spec.core.write import SafeWriter, WriteResult

START_MARKER = "<!-- spec:governance -->"
END_MARKER = "<!-- /spec:governance -->"
PATTERN = re.compile(
    rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)

_CONSUMER_WORKFLOW = """# Spec Governance for Coding Agents

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

## Universal Agent Standard (AGENTS.md)
This repository follows the universal `AGENTS.md` open standard for all AI coding agents (Antigravity, Claude Code, Cursor, Windsurf, Aider, Copilot, Gemini, etc.). All agents read and execute instructions directly from this single file.

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

_CONTRIBUTOR_BOOTSTRAP = """## ⚡ Agent Post-Clone Bootstrap Protocol (Run Once After Git Clone)
Any AI coding agent (Antigravity, Claude Code, Cursor, Windsurf, Aider, or custom) that clones this repository MUST execute the following 4-step bootstrap:

1. **Install dependencies in editable mode**:
   ```bash
   uv pip install -e ".[dev]"
   # or: pip install -e ".[dev]"
   ```
2. **Initialize project configuration**:
   ```bash
   specops config init --local --yes
   # or: ./bin/specops config init --local --yes
   ```
3. **Configure your AI agent governance adapter**:
   ```bash
   specops agent install
   # or: specops agent install antigravity
   ```
4. **Verify environment health**:
   ```bash
   specops doctor && specops audit
   # or: ./bin/specops doctor && ./bin/specops audit
   ```
"""


def render_consumer() -> str:
    """Pure SDD engineering workflow for third-party consumer projects."""
    return _CONSUMER_WORKFLOW


def render_contributor() -> str:
    """Contains the 4-step bootstrap protocol for contributors to cucco-specops-engine."""
    header = "# Spec Governance for Coding Agents\n\n"
    remainder = _CONSUMER_WORKFLOW[len(header) :]
    return f"{header}{_CONTRIBUTOR_BOOTSTRAP}\n{remainder}"


class AgentsAdapter:
    """Generate and inject the repository-level governance reference into AGENTS.md."""

    target = "AGENTS.md"
    claude_target = "CLAUDE.md"
    governance_file = ".spec/governance.md"

    def __init__(
        self,
        root: str | Path,
        target: str | None = None,
        agent: str | None = None,
    ) -> None:
        self.root = root
        if target:
            self.target = target
        self.agent = agent.lower().strip() if agent else None
        self.boundary = PathBoundary(root)

    def install(self) -> WriteResult:
        manifest = OwnershipManifest(self.root)
        writer_res = SafeWriter(self.root, manifest).write(
            self.governance_file,
            self.render(),
            mode=0o644,
        )

        agents_path = self.boundary.resolve(self.target)
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        content = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        block = f"{START_MARKER}\n@{self.governance_file}\n{END_MARKER}\n"

        if START_MARKER in content and END_MARKER in content:
            new_content = PATTERN.sub(block, content)
        else:
            stripped = content.rstrip()
            new_content = f"{stripped}\n\n{block}" if stripped else block

        agents_path.write_text(new_content, encoding="utf-8")

        if self.agent == "claude":
            self.install_claude_pointer()

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

        if self.agent == "claude":
            claude_res = self.uninstall_claude_pointer(dry_run=dry_run)
            if not del_res.deleted and not del_res.would_delete:
                return claude_res

        return del_res

    def install_claude_pointer(self) -> WriteResult:
        manifest = OwnershipManifest(self.root)
        claude_path = self.boundary.resolve(self.claude_target)
        claude_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_ref = f"@{self.target}"
        block = f"{START_MARKER}\n{pointer_ref}\n{END_MARKER}\n"

        if not claude_path.exists() or manifest.get(self.claude_target) is not None:
            return SafeWriter(self.root, manifest).write(self.claude_target, block, mode=0o644)

        content = claude_path.read_text(encoding="utf-8")
        if START_MARKER in content and END_MARKER in content:
            new_content = PATTERN.sub(block, content)
        else:
            stripped = content.rstrip()
            new_content = f"{stripped}\n\n{block}" if stripped else block

        claude_path.write_text(new_content, encoding="utf-8")
        record = manifest.record(self.claude_target, sha256_file(claude_path))
        return WriteResult(
            path=self.claude_target,
            sha256=record.sha256,
            created=False,
            updated=True,
        )

    def uninstall_claude_pointer(self, *, dry_run: bool = True) -> DeleteResult:
        manifest = OwnershipManifest(self.root)
        claude_path = self.boundary.resolve(self.claude_target)
        if not claude_path.exists():
            if manifest.get(self.claude_target) is not None and not dry_run:
                del manifest._records[manifest.boundary.relative(self.claude_target)]
                manifest._save()
            return DeleteResult(path=self.claude_target, deleted=False, would_delete=False)

        content = claude_path.read_text(encoding="utf-8")
        if START_MARKER in content and END_MARKER in content:
            cleaned = PATTERN.sub("", content)
            if not cleaned.strip():
                if manifest.get(self.claude_target) is not None:
                    try:
                        return manifest.delete_owned(self.claude_target, dry_run=dry_run)
                    except FileChangedError:
                        if not dry_run:
                            claude_path.unlink(missing_ok=True)
                            del manifest._records[manifest.boundary.relative(self.claude_target)]
                            manifest._save()
                        return DeleteResult(
                            path=self.claude_target,
                            deleted=not dry_run,
                            would_delete=dry_run,
                        )
                else:
                    if not dry_run:
                        claude_path.unlink(missing_ok=True)
                    return DeleteResult(
                        path=self.claude_target,
                        deleted=not dry_run,
                        would_delete=dry_run,
                    )
            else:
                if not dry_run:
                    claude_path.write_text(cleaned.rstrip() + "\n", encoding="utf-8")
                    if manifest.get(self.claude_target) is not None:
                        del manifest._records[manifest.boundary.relative(self.claude_target)]
                        manifest._save()
                return DeleteResult(path=self.claude_target, deleted=False, would_delete=False)

        return DeleteResult(path=self.claude_target, deleted=False, would_delete=False)

    @staticmethod
    def render_consumer() -> str:
        return render_consumer()

    @staticmethod
    def render_contributor() -> str:
        return render_contributor()

    def render(
        self_or_root: AgentsAdapter | str | Path | None = None,
        root: str | Path | None = None,
    ) -> str:
        target_root: str | Path | None = None
        if isinstance(self_or_root, AgentsAdapter):
            target_root = root if root is not None else getattr(self_or_root, "root", None)
        elif isinstance(self_or_root, (str, Path)):
            target_root = self_or_root
        elif root is not None:
            target_root = root

        if target_root is not None and (Path(target_root) / "packages" / "spec").exists():
            return render_contributor()
        return render_consumer()


class ClaudeAdapter(AgentsAdapter):
    """Adapter for Claude Code configuring AGENTS.md and discovery pointer CLAUDE.md."""

    def __init__(self, root: str | Path, target: str | None = None) -> None:
        super().__init__(root, target=target, agent="claude")


RECOGNIZED_AGENTS = {
    "agents": "Universal AGENTS.md Standard (AGENTS.md)",
    "antigravity": "Universal AGENTS.md Standard (AGENTS.md)",
    "claude": "Universal AGENTS.md Standard (AGENTS.md)",
    "cursor": "Universal AGENTS.md Standard (AGENTS.md)",
    "windsurf": "Universal AGENTS.md Standard (AGENTS.md)",
    "aider": "Universal AGENTS.md Standard (AGENTS.md)",
    "copilot": "Universal AGENTS.md Standard (AGENTS.md)",
    "gemini": "Universal AGENTS.md Standard (AGENTS.md)",
    "codex": "Universal AGENTS.md Standard (AGENTS.md)",
    "custom": "Universal AGENTS.md Standard (AGENTS.md)",
}

CodexAdapter = AgentsAdapter

__all__ = [
    "RECOGNIZED_AGENTS",
    "AgentsAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "render_consumer",
    "render_contributor",
]
