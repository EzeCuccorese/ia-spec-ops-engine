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
- spec-new <name>: Execute spec preflight "<name>" --json, which verifies the baseline and creates the spec (run spec new "<name>" only without preflight), work from the worktree_path it reports, stop immediately, conduct the mandatory requirements interview, then write .spec/specs/<slug>/spec.md with @s tagged Gherkin scenarios.
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
- **Anti-Telephone (Disk-First Memory)**:
  - During `spec work`, log TDD cycles and scenario mappings in `.spec/specs/<slug>/work.md`.
  - Keep chat responses concise with single-line references to disk artifacts instead of dumping voluminous diffs or logs into the context window.
- **The Judge (Pruning Over Drafting)**:
  - Generating code is cheap; judgment is the scarce resource. Prune speculative abstractions, dead code, and unrequested scope before requesting verification.

## Universal Agent Standard (AGENTS.md)
This repository follows the universal `AGENTS.md` open standard for all AI coding agents (Antigravity, Claude Code, Cursor, Windsurf, Aider, Copilot, Gemini, etc.). All agents read and execute instructions directly from this single file.

## Agent Tooling for Autonomous TDD Loop
- Run `spec test-assist --next`: Returns the exact next uncovered `@s` scenario to implement with TDD.

## Human Gates & User Alignment
- Spec Phase: Clarify ambiguities, user intent, and design requirements using the host agent's standard question or interaction mechanism. Never proceed on unclear assumptions; obtain explicit user alignment before drafting `spec.md`.
- Plan Phase: Detail architecture, affected files, and test-first strategy. Resolve technical tradeoffs with the user. Never start coding without explicit user sign-off.
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
   ./install.sh
   source .venv/bin/activate
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
    """Contains the 4-step bootstrap protocol for ia-spec-ops-engine contributors."""
    header = "# Spec Governance for Coding Agents\n\n"
    remainder = _CONSUMER_WORKFLOW[len(header) :]
    return f"{header}{_CONTRIBUTOR_BOOTSTRAP}\n{remainder}"


def get_bundled_skills() -> dict[str, str]:
    """Retrieve bundled skill name -> content mapping."""
    skills: dict[str, str] = {}
    names = ["spec-new", "spec-plan", "spec-verify", "spec-finish"]
    try:
        from importlib.resources import files

        base = files("spec").joinpath("skills")
        for name in names:
            skill_file = base.joinpath(name, "SKILL.md")
            if skill_file.is_file():
                skills[name] = skill_file.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError, AttributeError, UnicodeDecodeError):
        # Fall back to the filesystem-based lookup below if the package resources
        # API is unavailable or the bundled skills cannot be read this way.
        pass
    if not skills:
        skills_dir = Path(__file__).parent / "skills"
        for name in names:
            skill_file = skills_dir / name / "SKILL.md"
            if skill_file.is_file():
                skills[name] = skill_file.read_text(encoding="utf-8")
    return skills


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

    def _skill_destinations(self) -> list[str]:
        """Return relative directory paths where skills should be installed for this agent."""
        dests = [".agents/skills"]
        if self.agent == "claude":
            dests.append(".claude/skills")
        elif self.agent == "antigravity":
            dests.append(".gemini/skills")
        elif self.agent == "codex":
            dests.append(".codex/skills")
        return dests

    def install_skills(self) -> list[WriteResult]:
        manifest = OwnershipManifest(self.root)
        writer = SafeWriter(self.root, manifest)
        bundled = get_bundled_skills()
        results: list[WriteResult] = []
        for dest_base in self._skill_destinations():
            for name, content in bundled.items():
                rel_path = f"{dest_base}/{name}/SKILL.md"
                results.append(writer.write(rel_path, content, mode=0o644))
        return results

    def uninstall_skills(self, *, dry_run: bool = True) -> list[DeleteResult]:
        manifest = OwnershipManifest(self.root)
        bundled = get_bundled_skills()
        results: list[DeleteResult] = []
        for dest_base in self._skill_destinations():
            for name in bundled:
                rel_path = f"{dest_base}/{name}/SKILL.md"
                if manifest.get(rel_path) is not None:
                    res = manifest.delete_owned(rel_path, dry_run=dry_run)
                    results.append(res)
                    if not dry_run:
                        skill_dir = self.boundary.resolve(f"{dest_base}/{name}")
                        if skill_dir.is_dir() and not any(skill_dir.iterdir()):
                            skill_dir.rmdir()
                        base_dir = self.boundary.resolve(dest_base)
                        if base_dir.is_dir() and not any(base_dir.iterdir()):
                            base_dir.rmdir()
        return results

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

        self.install_skills()

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

        claude_res = self.uninstall_claude_pointer(dry_run=dry_run)
        if not del_res.deleted and not del_res.would_delete:
            del_res = claude_res

        self.uninstall_skills(dry_run=dry_run)

        return del_res

    def uninstall_claude_pointer(self, *, dry_run: bool = True) -> DeleteResult:
        """Removes the CLAUDE.md block an earlier Spec install wrote; AGENTS.md is the only file now."""
        manifest = OwnershipManifest(self.root)
        claude_path = self.boundary.resolve(self.claude_target)
        if not claude_path.exists():
            if manifest.get(self.claude_target) is not None and not dry_run:
                del manifest._records[manifest.boundary.relative(self.claude_target)]
                manifest._save()
            return DeleteResult(path=self.claude_target, deleted=False, would_delete=False)

        content = claude_path.read_text(encoding="utf-8")
        is_owned = manifest.get(self.claude_target) is not None

        if START_MARKER in content and END_MARKER in content:
            match = PATTERN.search(content)
            if match and not is_owned:
                inner = match.group(0)
                extracted = inner.replace(START_MARKER, "").replace(END_MARKER, "").strip()
                valid_pointers = {
                    f"@{self.target}",
                    f"@{self.governance_file}",
                    f"@{self.boundary.relative(self.target)}",
                    f"@{self.boundary.relative(self.governance_file)}",
                    f"@{self.boundary.root / self.governance_file}",
                }
                if extracted not in valid_pointers:
                    from spec.core.ownership import FileChangedError

                    raise FileChangedError(
                        f"Uninstall aborted: Block in '{self.claude_target}' was modified by user. File preserved."
                    )

            cleaned = PATTERN.sub("", content)
            if not cleaned.strip():
                if is_owned:
                    return manifest.delete_owned(self.claude_target, dry_run=dry_run)
                else:
                    if not dry_run:
                        claude_path.write_text("", encoding="utf-8")
                    return DeleteResult(
                        path=self.claude_target,
                        deleted=False,
                        would_delete=False,
                    )
            else:
                if not dry_run:
                    claude_path.write_text(cleaned.rstrip() + "\n", encoding="utf-8")
                    if is_owned:
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

    def render(self, root: str | Path | None = None) -> str:
        target_root: str | Path | None = root if root is not None else self.root

        if target_root is not None:
            root_path = Path(target_root)
            spec_init = root_path / "packages" / "spec" / "src" / "spec" / "__init__.py"
            pyproject = root_path / "pyproject.toml"
            if spec_init.is_file() and pyproject.is_file():
                try:
                    pyproject_content = pyproject.read_text(encoding="utf-8")
                    if "ia-spec-ops-engine" in pyproject_content:
                        return render_contributor()
                except OSError:
                    pass
        return render_consumer()


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

__all__ = [
    "RECOGNIZED_AGENTS",
    "AgentsAdapter",
    "render_consumer",
    "render_contributor",
]
