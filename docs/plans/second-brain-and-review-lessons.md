# Plan: second brain + three new review lessons

Status: the second-brain implementation, review lessons, and adapted review skills are in PR #85.
Optional Orca brief and panel work is deferred. The original survey is historical context.
Date: 2026-11-19.

## 1. How the user works today (survey)

- **Three agents, one person.** Claude Code, Codex and Antigravity are used together
  (Antigravity plans, Claude validates/implements, Codex judges), often dispatched as
  Orca workers in throwaway worktrees.
- **Knowledge is siloed per agent and per directory:**
  - Claude memory: 45 notes across 16 of 62 project dirs, keyed by cwd. The same note is
    re-saved per worktree (8+ duplicated names, e.g. two near-identical worktrees of one repo with 15 each).
  - Codex memory: `~/.codex/memories/MEMORY.md` is 263 KB plus 143 rollout summaries —
    too big to load, never curated, invisible to the other agents.
  - Antigravity: its own `brain/` and `knowledge/` stores, separate again.
  - Taskflow: 88 tasks (50 active, 36 closed, 1 paused). `facts[]` is unused; decisions and
    lessons stay buried in `log.md` and `rounds/`. Closing a task moves nothing.
  - Working preferences are now maintained as versioned, shared engineering rules in the
    engine catalog. Company policies remain in private external packs.
  - No human-facing notes system (no Obsidian, no `~/notes`).
- **Recurring kinds of knowledge:** working-style feedback (largest), gotchas (node version,
  VPN before staging, editable install), architecture decisions per service,
  references (chat channels, registries, service archetypes, PR/ticket links), process
  conventions.
- **Pain points:** each new worktree starts blind; Orca worker briefs paste context instead of
  pointing to it, plus stale active tasks.

## 2. Second brain (PARA) design

PARA mapping onto what already exists — no duplication:

| PARA | Source of truth | New work |
|---|---|---|
| Projects | Taskflow tasks (unchanged) | none |
| Areas | Engine catalog + active private corporate pack | none |
| Resources | **new** `brain` notes | store + CLI |
| Archive | **new** archive note written on `taskflow close` | close hook |

### Storage

- `data_dir()/brain/` (`~/.local/share/ai-governance/brain/`), outside any cwd, so every
  agent and every worktree sees the same notes.
- Two namespaces for notes: `personal/` and `<company>/`. Company notes never enter git.
- One Markdown file per note with front matter: `title`, `kind`
  (`gotcha|reference|decision|howto|archive`), `tags`, `scope` (`personal|<company>`),
  `repos` (optional), `source` (task id, PR, session), `created`, `updated`.
- Plain files on purpose: grep-able, editable by hand, viewable later from an Orca panel.

### CLI (`ai-governance brain`, new module `ai_governance/brain/cli.py`)

- `brain add "<text>" [--kind] [--tag] [--scope] [--repo]` — quick capture. Defaults the
  scope from the current repo (company repo → company scope) and the kind to `gotcha`.
  Rejects content that looks like a secret (reuse existing secret patterns).
- `brain search "<query>" [--kind] [--scope]` — one search over brain notes, taskflow
  (title, summary, facts, decisions, links) and rules. Returns titles + paths + one line,
  capped output (frugal). Plain text match first; no embeddings in v1.
- `brain show <slug>`, `brain list [--kind] [--stale]`, `brain edit <slug>`.
- `brain archive <task-id>` — writes the archive note (summary, decisions, facts, links)
  from a task; called automatically by `taskflow close`, idempotent.
- `brain import --from claude|codex [--dry-run]` — one-off, curated migration: lists
  candidate notes (dedup by name/title), the user picks, nothing is imported blindly.

### Integration

- **Taskflow:** `cmd_close` calls `brain archive` (best effort; a failure is reported, never
  blocks the close). Encourage `fact`/`decide` use so archives carry content.
- **SessionStart hook:** stays inside the 400-char budget. Adds at most one line: the count
  of notes tagged for the current repo and the search command. No note bodies by default.
- **Rule:** small always-on rule (or a line in `14-taskflow`) telling agents: search the brain
  before asking the user something already answered; save durable lessons with `brain add`
  instead of agent-native memory.
- **Claude native memory:** not removed. The shared engine catalog points agents to
  `brain add` for cross-agent facts; native memory stays for cwd-only details.
- **Orca:** v2 only — worker briefs include `brain search` hits instead of pasted context;
  optional panel to browse notes.

### Delivery status

The Brain store, CLI, task-close archive, SessionStart digest, and curated import are implemented
and covered in PR #85. The optional Orca brief integration and panel remain deferred.

### Risks / counter-metrics

- Notes nobody reads → measure: `brain search` hits per week; prune with `--stale`.
- Context bloat → hook budget stays at 400 chars, enforced by test.
- Company data leaking across scopes → explicit private pack roots, scope checks, secret checks,
  and repository/package publication guards.

## 3. Three new review lessons

The three review lessons below are implemented in the always-on review-ready and Python async
catalog rules. Each rule remains within its context budget. Company policies load only from an
external private directory and are excluded from repository and package publication.

| # | Lesson | Target | Shipped behavior |
|---|---|---|---|
| 1 | Format values (currency, units) travel as explicit data, never inferred from locale | `20-review-ready-code.md`, Types & API | Currency and units are explicit fields |
| 2 | "Create only if absent" across services = conditional write enforced by the owner | `20-review-ready-code.md`, Errors & Timeouts | Owner service enforces conditional write and conflict response |
| 3 | No `async` function without `await` (Sonar S7503) | `2-stacks/python-async.md` | Unused async functions are synchronous |

## 4. Review skills adapted from a shared bundle

The bundled `test-audit` skill requires a concrete contract, regression, and coverage gap before
adding a test. It asks reviewers to cite the existing assertion that already covers a request
when declining duplicate coverage. It audits assertions before recommending suite changes.

The bundled `code-simplifier` skill limits edits to the current diff, protects behavior and error
handling, checks truthiness and shared argument mutations, and asks for relevant checks after a
simplification. It does not commit or publish changes.

Cross-model review uses existing task debates. Reviewers examine distinct dimensions, findings
are verified against current code, and the verdict appears before observations. The borrowed
workflow's fixed model assumptions and company-specific examples were not adopted.
