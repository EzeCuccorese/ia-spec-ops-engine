# Changelog

## 1.9.2 - 2026-11-12

### Fixes
- Remove interactive TUIs and legacy packages, fix gate and hygiene bugs.
- Address PR review feedback on check cache, git -z paths, and todo hygiene.
- Tokenize comments with lizard and harden check cache.

## 1.9.1 - 2026-11-12

### Features
- Add ws design --stats and --suggest flags.
- Scope quality gate tests stage in yarn and pnpm monorepos.
- Unify config file handling with 3 layers and personal override.

### Fixes
- Fix PHP args calculation and pin lizard for Dart support.
- Handle PHP 8 trailing comma in parameter list.
- Format monorepo test plan for shell and guard against unscoped fallback.
- Redirect stdin from /dev/null in monorepo scoped test run.
- Make design exclude additive and apply to all checks.
- Resolve design blocking violations in settings and tests.
- Address review feedback on design stats and exclude matching.
- Resolve relative root paths across design checks and add tests.

## 1.9.0 - 2026-11-12

### Features
- Add cross-examination rounds, launch receipt check, CHANGE lines and scratch in taskflow.

### Fixes
- Bind the launch receipt to its dispatch and read Orca's real schema in taskflow.
- Keep receipt fields on a partial launch override and harden scratch and rebut reads in taskflow.
- Avoid direct index on round file and cover error paths in taskflow.

## 1.8.0 - 2026-11-06

### Features
- personal rules CLI, deploy approval policy and audit follow-ups (#61)

## 1.7.0 - 2026-11-06

### Features
- Comprehensive v1.6 audit implementation.
- Phase 1 - personal layer governance and origin frontmatter guarantee.
- Phase 2 - always-on rules separation and corporate index.
- Phase 3 - measure actual session reads for codex and user content.
- Phase 4 - session-start hooks for codex and antigravity.
- Phase 5 - audit polish and minor engine improvements.
- Add provider-agnostic deploy approvals rule and decouple circleci.
- Add production risk window rule and update manifests.
- Make production risk window cutoff hours configurable.

### Fixes
- Phase 4 correction - report antigravity session-start gap in doctor.

## 1.6.0 - 2026-11-06

### Features
- Relax tri-agent hints for frictionless local workflows.

## 1.5.0 - 2026-11-04

### Features
- Layered user rules for every agent.
- General tool rules into engine catalog for Phase A.
- Add personal rules pack mirrored from corporate.
- Add user-scope entry files and doctor check for Claude.
- Add personal and corporate rules pointer and update docs.
- Complete the tool rules with gotchas, tokens and gate policy.

### Fixes
- Keep corporate entries and warn when corporate directory is missing.
- Precisely identify corporate rule links by path and target.
- Add missing 17-quality-gate rule file.
- Format codebase with ruff and adjust test limits.
- Silence corporate warning when no prior entries and filter md files.

## Unreleased

### Features
- General tool rules into the engine catalog (Phase A): `circleci`, `13-atlassian`, `14-taskflow`, `15-tool-confidentiality`, `16-git-branch-ownership`, `17-quality-gate` with user-scope always-on installation for Claude, Antigravity, and Codex.
- personal: add personal preferences pack support (`$AI_GOVERNANCE_PERSONAL_DIR` or `~/.config/ai-governance/personal/`), installed as symlinks for Claude, Antigravity, and Codex, with missing directory safety.
- install: add Claude user-scope entry files (`~/.claude/CLAUDE.md` and `~/.claude/AGENTS.md`) using marker blocks to preserve existing content outside markers.
- codex: instruct Codex in its AGENTS.md block to read both `company/` and `personal/` rule directories once per session.

### Fixes
- corporate: preserve previously installed corporate rules and scripts when the corporate root directory does not exist, warning instead of removing them.

## 1.4.0 - 2026-11-04

### Breaking changes
- Remove the subprocess agent path.

### Features
- Per-repo allowed agents and provider independence.
- Dispatch, collect and abort for Orca-run reader rounds.
- Judge rounds are readers; the engine runs the checks.
- Pull request model, GitHub reader and deterministic status.
- PR add/rm/sync/list, subtask aggregation and a one-line PR summary.
- Register pull requests created with gh pr create.

### Fixes
- A bound repo missing on disk no longer blocks commands.
- Load the config without Orca and hide the run stub from usage.
- Parse the real Orca envelope and harden collect integrity.
- Accept gh -R in the PR hook and fix the PR test fixtures.
- Resolve the PR #49 review findings.
- Address the automated review comments.

## 1.3.0 - 2026-11-03

### Features
- Layered configuration, repo-priority controls with trust, and module splits.
- Read the repo and user config files in the quality gate.
- Repo config can replace or disable controls.

### Fixes
- Reject unknown Atlassian profiles, unify run_local defaults, lazy config.
- Address review findings.
- Legacy judges follow config precedence.
- Trust and approval for repo controls.
- Harden repo trust.
- Trust the ordered execution plan.
- Untrusted repo configs are ignored entirely.
- Keep legacy call signatures.
- Correct config types and cover service selection.
- Address PR review threads.
- Empty env values are unset unless the setting opts in.

## 1.2.0 - 2026-10-29

### Features
- Retire spend tracking, add user-scope language rules and the TriAgentTaskFlow plan.

### Fixes
- Resolve PR #38 follow-up regressions and PID/CLI edge cases.

## 1.1.3 - 2026-10-21

### Fixes
- Resolve audit bugs, unify CLI dispatch and harden state.
- Handle Gemini review timeouts, retries and large diffs gracefully.
- Never treat the repo root as a sibling worktree.

## 1.1.2 - 2026-10-20

### Fixes
- Refresh lockfiles after the version bump.

## 1.1.1 - 2026-10-20

### Fixes
- Base the next version on the last release commit.

## 1.1.0 - 2026-10-20

### Features
- Calibrate takes the amount first and flexible local dates.
- Add a runner subagent for noisy commands.

### Fixes
- Run pytest and ruff from the Poetry env when there is no .venv.
- Find the Poetry env when env info cannot.
- Never fall back to a global tool that cannot work.
- Calibrate accepts comma decimals and pasted amounts.

## 1.0.0 - 2026-10-17

### Features
- Single project version with PR-based releases (#27).
- Schedule the daily price refresh as a LaunchAgent (#26).
- Install corporate rules as symlinks (#17).

### Fixes
- Take the newest subjects for the AI notes.
- Set the work directory in a step, not a job env.
- Rebuild the release branch with a plain force push.
- Keep generated release files out of the checkout.
- Confluence read keeps code blocks and list numbering (#25).
- Keep pending steps and report entries moved to the log (#24).
- Convert Markdown to ADF with marklas, fix jira search, add jira edit (#20).

