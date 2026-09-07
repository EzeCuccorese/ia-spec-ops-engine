# Spec Governance for Coding Agents

## ⚡ Agent Post-Clone Bootstrap Protocol (Run Once After Git Clone)
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

<!-- spec:governance -->
@.spec/governance.md
<!-- /spec:governance -->
