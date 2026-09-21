# Deterministic First

## 1. Deterministic first
- Before doing by hand anything a harness tool already covers — task state, searching state,
  worktrees, git hooks status, Jira/Confluence, test summaries, usage — check the "Harness
  Tools" table in this file's host (`AGENTS.md`) first.
- If a listed tool covers the need, use it instead of reading files, grepping logs, or calling
  raw APIs yourself.

## 2. Announce
- When you use a harness tool, print exactly one line before the call:
  `⚙ <tool-id> <args>` (e.g. `⚙ progress here`). No explanation.
- If no tool covers the need, say so in one line — `⚙ none — doing it manually` — and proceed.
- Never block on a missing tool.

## 3. Output discipline
- Tools run in agent mode automatically (non-TTY). Never force TTY output.
- Prefer `--json` when you need to parse the result.
- Never request `--full` unless the compact output was insufficient.
- Never re-read output a tool already condensed. If a tool cites `full: <path>` or
  `more: <cmd>`, use that only when you actually need the extra detail.

## 4. Context frugality
These practices apply everywhere, tool or no tool:
- **APIs/JSON**: pipe through `jq` with the minimal projection; never dump raw JSON.
- **Logs/builds**: use the quietest runner flag plus `2>&1 | tail -40`; widen only on failure.
- **Tests**: run normally — the `frugal` hook keeps only the result and the failing block.
  Don't re-run `test`/`lint`/`types` by hand if the pre-push hook already ran them; don't
  re-read a saved output file once the push confirmed success.
- **Git**: `git diff --stat` before `git diff`; `git log --oneline -n 10`; `git status --porcelain`.
- **Files**: use `Read` with offset/limit on large files; don't re-read what's already in
  context; don't `Read` to verify an `Edit`/`Write`.
- Never print lockfiles, minified bundles, or generated files in full.
- **Subagents**: delegate only when input is small, work is large, and required output is
  small. Don't delegate when you'll need the file contents afterward. Every delegation prompt
  ends with an explicit budget: "return ≤N lines, absolute paths, no code dumps".
- **Delegation tiers**: when executing an approved plan, the orchestrating (top-tier) model
  does not do the typing. Heavy implementation → a mid-tier model subagent (e.g. Claude
  Sonnet); tests, docs, and mechanical changes → the cheapest tier (e.g. Claude Haiku). The
  orchestrator coordinates, reviews each delivery, and runs the final verification. Work one
  phase at a time and run the project's quality gates (lint, types, tests) between phases.

## 5. Context window
- Your host may warn when context usage grows; it never blocks.
- Save progress (`progress step`/`progress fact`/`progress note`) before `/compact` or `/clear`.

## 6. Wording
- Never use the word "honest" or its variants — "honestly", "to be honest", "honest warning"
  — in any language (es: "honesto", "honestamente", "aviso honesto"), neither in replies nor in
  generated documents. State caveats directly instead: "note that…", "keep in mind…".
