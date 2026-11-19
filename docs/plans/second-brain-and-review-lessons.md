# Plan: second brain + three new review lessons

Status: proposal, nothing implemented. Date: 2026-11-19.

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
  - Personal rules (`~/.config/ai-governance/personal/rules`, 10 files) are the only layer
    deliberately shared by all three agents.
  - No human-facing notes system (no Obsidian, no `~/notes`).
- **Recurring kinds of knowledge:** working-style feedback (largest), gotchas (node version,
  VPN before staging, editable install), architecture decisions per service,
  references (chat channels, registries, service archetypes, PR/ticket links), process
  conventions.
- **Pain points:** each new worktree starts blind; Orca worker briefs paste context instead of
  pointing to it; a preference learned in Codex never reaches Claude; stale active tasks.

## 2. Second brain (PARA) design

PARA mapping onto what already exists — no duplication:

| PARA | Source of truth | New work |
|---|---|---|
| Projects | Taskflow tasks (unchanged) | none |
| Areas | Personal + corporate rules (unchanged) | none |
| Resources | **new** `brain` notes | store + CLI |
| Archive | **new** archive note written on `taskflow close` | close hook |

### Storage

- `data_dir()/brain/` (`~/.local/share/ai-governance/brain/`), outside any cwd, so every
  agent and every worktree sees the same notes.
- Two namespaces, same split as rules: `personal/` and `<company>/`.
  Company notes never enter git (same treatment as `packages/corporate-rules/*/`).
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
- **Claude native memory:** not removed. Once import is done, a personal rule points Claude to
  `brain add` for cross-agent facts; native memory stays for cwd-only details.
- **Orca:** v2 only — worker briefs include `brain search` hits instead of pasted context;
  optional panel to browse notes.

### Phases

1. Store + `add/search/show/list` + tests (no hooks). Measure with real use for a week.
2. `taskflow close` → archive; `brain archive` for the 36 already-closed tasks (dry-run first).
3. SessionStart line + agent rule; check the rendered context budget tests.
4. Curated import from Claude and Codex memories; dedup.
5. Optional: Orca brief integration and panel; stale-task review (`brain list --stale`,
   `taskflow list` of active tasks untouched for N days).

### Open questions for the user

- Location: `~/.local/share/...` (engine default) or a visible folder like `~/second-brain`?
- Should `taskflow close` archive automatically or ask?
- Which Codex/Antigravity knowledge is worth importing, if any?

### Risks / counter-metrics

- Notes nobody reads → measure: `brain search` hits per week; prune with `--stale`.
- Context bloat → hook budget stays at 400 chars, enforced by test.
- Company data leaking into personal/public → scope split + secret check + gitignore.

## 3. Three new review lessons

Constraint: the review-ready rule (`catalog/1-core/20-review-ready-code.md`) is always-on,
1426 of 1500 bytes (74 left). The corporate pack is gitignored and has no size test.

| # | Lesson | Target | Proposed wording |
|---|---|---|---|
| 1 | Format values (currency, units) travel as explicit data, never inferred from locale | `20-review-ready-code.md`, Types & API | "Send currency and units as explicit fields (ISO codes), never derived from locale or language." |
| 2 | "Create only if absent" across services = conditional write enforced by the owner | `20-review-ready-code.md`, Errors & Timeouts | "Enforce create-if-absent across services with a conditional write in the owner service (409 on conflict), never a caller-side GET then POST." |
| 3 | No `async` function without `await` (Sonar S7503) | `2-stacks/python-async.md` (1609/2000, scoped) | "Do not declare a function `async` unless it awaits; make it sync and drop `await` at call sites." |

- To fit 1 and 2 (~230 bytes) in the always-on rule, tighten existing sentences
  (~160 bytes) without dropping any invariant; if that is not possible, move "PR Hygiene"
  to a scoped rule. The budget test must stay green.
- The engine rules stay company-agnostic. Company-specific details (which service owns the
  currency, which API returns 409) go only in the company pack, which is gitignored and
  never published from this repo.
- Company artifacts (rules for the corporate pack, PRs in company repos) never mention the
  engine.
- Ship as its own PR, separate from the second brain.
