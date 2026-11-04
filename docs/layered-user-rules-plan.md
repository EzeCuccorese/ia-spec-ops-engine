# Plan: build the user's rules from the engine

Status: implemented in PR #51 (phases A, B and C plus the corporate pack safety fix, in one PR).

## Context

Today the user-level instructions live in a hand-written `~/.claude/AGENTS.md` that mixes
three kinds of content:

1. **Personal preferences** (language, explanation style, voice, how to work with the user).
2. **Company rules**: already moved to the corporate pack
   (`packages/corporate-rules/<company>/rules/`, gitignored). Done by hand on 2026-11-04;
   the pack now ships `vpn-staging`, `admin-e2e`, `debug-logs`, `nube-portal`,
   `slack-pr-aviso` and `equipo`, besides the earlier five.
3. **General tool rules** that belong to the engine: CircleCI, Atlassian
   (`ai-governance jira|confluence`), taskflow, context frugality, quality gate, subagent
   delegation.

Problems:

- Claude is the only agent that gets the personal file in full. Codex receives only the short
  `ai-governance` block plus the copied rules, and Antigravity has no global personal file at all.
- The personal file is about 11 KB and is sent with every request.
- Rules about engine tools live outside the engine, so they drift from the tools they describe.

## Goal

Every agent (Claude Code, Codex, Antigravity) gets the same three layers, all rendered by
`ai-governance install`:

```
engine catalog (general tool rules)        -> packages/ai-governance/src/ai_governance/catalog/
corporate pack (company rules, gitignored) -> packages/corporate-rules/<company>/rules/
personal pack (user preferences, outside the repo) -> new, see Phase B
```

The hand-written `~/.claude/AGENTS.md` disappears. The file becomes generated output, or
shrinks to the stub that points at the rendered files.

## Phase A: general tool rules into the catalog

Move these sections out of the personal file into catalog rules. Each rule stays
company-agnostic; company specifics go to the corporate pack.

| Section today | Catalog rule (proposal) | Company-specific part (to the pack) |
|---|---|---|
| CircleCI: free reads, writes need approval | `3-infrastructure/circleci.md` | Job names such as `authorize-deploy-*`, project names |
| Atlassian: Jira and Confluence via `ai-governance` (+ read/write gotchas) | `1-core/atlassian.md` | None (URL comes from `$ATLASSIAN_URL`) |
| Task registry (taskflow) | `1-core/taskflow.md` | None |
| (new) Branch ownership: never touch branches that are not the user's | extend `1-core/05-git-commits.md` or add `1-core/git-branch-ownership.md` | None |
| Context frugality, quality gate, `QG_SKIP` | `1-core/frugality.md` (merge with the existing `ai-governance.md` rule) | None |
| Personal tools stay out of company artifacts | `1-core/tool-confidentiality.md`, worded generically ("engine tooling is never mentioned in tickets, PRs, commits, reviews or chat tools") | None |

Branch ownership rule (new, required, `user_scope: true` so every agent gets it):

- A branch is the user's only if the user created it or asked the agent to create it.
- On any other branch (`main`, shared branches, other people's branches) the agent never
  pushes, force-pushes, rebases, resets, deletes or commits.
- To do any of that the agent first shows the exact action and branch, then waits for the
  user's explicit authorization. One authorization covers one action on one branch only.
- When ownership is unclear, the branch counts as not the user's.
- Optional follow-up: a Claude `PreToolUse` hook that blocks `git push` to branches that
  are not the user's, so the rule is enforced and not only advisory.

Rules for the content:

- Name tokens only by variable (`CIRCLE_TOKEN`, `CIRCLE_TOKEN_RW`), never by value.
- The CircleCI rule keeps the hard rule: show the exact action and target, wait for approval
  before any POST or DELETE, never approve a deploy hold.
- Keep the wording short. These files are loaded on every request.

Steps:

1. Read `rules/catalog.py`, `install/installer.py` and `install/agents.py` to learn how
   catalog rules are selected and rendered per agent (Claude rules dir, Antigravity rules
   dir, Codex `ai-governance/` dir + `AGENTS.md` block).
2. Add the rule files with the front matter the catalog expects.
3. Tests: install, uninstall and idempotency for each agent (run the install twice and expect
   the same result); the rendered Codex block references the new rules.
4. Update the package README and the CHANGELOG.

## Phase B: personal pack

Mirror the corporate pack for personal preferences, so the personal layer is also built by
the engine instead of edited by hand per agent.

- Location: outside the repo, e.g. `~/.config/ai-governance/personal/rules/*.md`, overridable
  with `AI_GOVERNANCE_PERSONAL_DIR`. Never committed.
- Same install mechanics as corporate packs: symlinks into `~/.claude/rules/` and
  `~/.gemini/config/rules/`, and a Codex rendering. Prefix: `ai-governance-personal-<name>.md`.
- Content to move from `~/.claude/AGENTS.md`: language, explanation style, how to work with
  me (voice, third-party messages, fixes in the owning branch, tests), Jira scope
  conventions, the two `gh` accounts, the risk window (generic rule; company names already
  in the pack).
- Entry files (decided 2026-11-04). The engine generates both, as marker blocks
  (`install/blocks.py`), and **never overwrites existing content**: it appends its block,
  keeps everything outside the markers, and uninstall removes only the block.
  - `~/.claude/AGENTS.md`: a block with the personal rules and pointers to the three layers,
    shared text for Claude and Codex.
  - `~/.claude/CLAUDE.md`: a block that only contains `@AGENTS.md`, so Claude is guaranteed
    to load it. Do not `@`-import each rule: Claude already loads every file in
    `~/.claude/rules/`, and importing them again would load them twice.
  - Add a live probe (`install/probe.py`) that confirms Claude loads the user-level
    `AGENTS.md` through `CLAUDE.md`, and a `doctor` check for both blocks.
  - Project scope does not change: `AGENTS.md` stays the only project instructions file.

Precedence (document it in the README): repo rules > personal pack > corporate pack >
engine catalog, for conflicts. Repo files keep winning, as they do today.

## Phase C: Codex and Antigravity parity

- Codex already receives the corporate pack in `~/.codex/ai-governance/company/` (verified
  on 2026-11-04). `packages/corporate-rules/README.md` still says Codex packs are skipped:
  fix the README.
- Make sure the Codex `AGENTS.md` block tells the agent to read `company/` and the new
  `personal/` dirs every session.
- Antigravity: confirm that files in `~/.gemini/config/rules/` with `trigger: always_on`
  are enough, and that no global `GEMINI.md` is needed.

## Known trap found during the manual move

`ai-governance` is installed with `uv tool install <dir>` (not `--editable`), so
`corporate.py` resolves the pack dir to `site-packages/../corporate-rules`, which does not
exist. A plain `ai-governance install` then **removes** every installed company rule. It
only works with `AI_GOVERNANCE_CORPORATE_DIR` set. Options:

- reinstall with `--editable`, as the README says; or
- make the installer refuse to remove packs when the pack dir is missing, and print a warning
  instead (safer default); or
- persist the pack dir in the user config (`settings.py`) on first install.

The second option is recommended in any case: a missing dir should never mean "delete all".

## Done when

- `~/.claude/AGENTS.md` holds no hand-written rules (or no longer exists).
- `ai-governance install --scope user --agent claude --agent antigravity --agent codex`
  produces the same three layers for all three agents.
- Running the install without `AI_GOVERNANCE_CORPORATE_DIR` in a non-editable install
  removes nothing.
- Tests and README updated; one PR per phase (A, B, C), reviewed by the user before merge.
