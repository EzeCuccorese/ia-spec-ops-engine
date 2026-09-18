# Progress Workflow — Portable Task State Management

This document defines the universal protocol for tracking and restoring task state across coding sessions using the `progress` CLI. It works across any AI coding agent (Antigravity, Codex, Claude Code, Cursor, Windsurf, Aider, terminal).

> **Announce:** print one line — `⚙ progress <subcommand>` — before each call to the `progress` CLI. See rule `00-deterministic-first`.

## Core Principles
1. **Zero Provider Coupling:** Operates strictly via the deterministic `progress` CLI and disk state (`~/.specops/progress/` or local repository state).
2. **Verified Facts:** Record evidence and its context. Recheck facts when code, branches, configuration, or external state have changed.
3. **Traceability:** Tasks link related Git repositories, Jira tickets, and external documentation without mutating external trackers implicitly.

---

## 1. Save Progress

Save or update the state of the active task.

```bash
# 1. Identify active task context
progress here --json

# 2. If no active task exists, initialize only with explicit user confirmation
progress new "<task-id>" --title "<Short Title>"

# 3. Update task details
progress summary "<task-id>" "<High-level summary of changes and current status>"
progress step "<task-id>" add "<Completed or pending step>"
progress step "<task-id>" done "<Completed or pending step>"
progress fact "<task-id>" "<Verified fact or invariant discovered>"
progress link "<task-id>" "<Document title>" "https://example.com/document"

# 4. Confirm state
progress view "<task-id>" --json
```

**Invariants:**
- Never fabricate a Jira issue or transition external ticket state as an implicit side effect of saving progress.
- Record pending roadblocks explicitly in the task steps.

---

## 2. List Tasks (`progress list`)

Discover pending or recently updated tasks in the current environment.

```bash
# List open/active tasks
progress list --json

# List all tasks including completed
progress list --all --json
```

---

## 3. Resume Task (`progress resume`)

Restore full context from a prior session.

```bash
# 1. Load full task state and verified facts
progress view "<task-id>" --json

# 2. Mark task as active in the current session
progress resume "<task-id>"
```

**Context Restoration Protocol:**
1. Review recorded facts, their evidence, and whether their context is still current.
2. Review pending steps and resume execution from the first uncompleted step.
3. Verify Git repository worktree status against the repositories listed in the task metadata.

---

## 4. Close Task (`progress close`)

Finalize a task upon verified completion and human sign-off.

```bash
# Complete any remaining steps and close
progress close "<task-id>" --reason "<Final completion note or PR link>"
```

**Invariants:**
- Do not close tasks with unverified or failing test suites.
