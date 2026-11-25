# Changelog

## 4.2.0 - 2026-11-25

### Features
- Support checkout-local config and Antigravity subagents.

### Fixes
- Move and fix config.
- Harden symlink checks, hook binary lookup, and config tests.

## 4.1.0 - 2026-11-20

### Features
- Add user-communication rule and working agreements.

### Fixes
- Unwrap chained launchers in the Antigravity noisy-command check.

## 4.0.0 - 2026-11-20

### Breaking changes
- Harden workspace/governance checks, consolidate rules, and add cross-agent brain (#85).
- Consolidate rules and protect company policies.

### Features
- Add cross-agent PARA second brain store, search, archive, and import.
- Add bundled slack-formatting skill.
- Route user reports to a private Slack channel.

### Fixes
- Close false-pass checks, rule duplication, and Atlassian/hook gaps.
- Harden design checks, quoting, timeouts, and scan.
- Harden taskflow locking, installer/personal safety, config coercion, and review rules.
- Tighten core taskflow and review-ready rules within codex budget.
- Normalize wrapped rich output in personal sync warning test.
- Enforce secret guard on archive, guard repo path, and dedupe batch imports.
- Handle Linux process-group reap timing in timeout test.
- Keep KeyError uncaught at top-level CLI entrypoint.
- Keep migration and catalog checks green.
- Retain runs with zero or missing cost.
- Handle missing cost_usd in per_condition_stats and fix empty-cost test.
- Harden store atomicity, secret detection, archive collisions, safe edit, and search.
- Address PR #85 review findings.
- Address PR #85 review findings and add regression tests.
- Isolate PATH from system cargo in missing-tool hook test.
- Isolate HOME in missing-tool hook test to avoid runner ~/.cargo/bin.
- Clean up interrupted subprocesses, preserve failure progress lines, and guard workflow_dispatch.
- Address remaining PR #85 review comments and update tests.

## Unreleased

### Fixes
- Antigravity pre-tool hook: catch chained launchers such as `uv run python -m pytest` and drop the unused `NOISY_COMMAND` regex.

### Features
- Add `22-user-communication` rule (reply language, plain explanations, drafts for others, writing as the user).
- Add owning-branch fixes, post-push CI follow-through and Jira scope placement to the surgical-changes, pull-requests and Atlassian rules.

### Breaking changes
- Retire `ai-governance personal` and remove managed personal-rule links on upgrade.

### Fixes
- corporate: preserve previously installed corporate rules and scripts when the corporate root directory does not exist, warning instead of removing them.

## 3.0.0 - 2026-11-18

### Breaking changes
- Layer rule budgets, decompress rules, and slim engine for Orca.

### Features
- Add review lessons on deadlines, cleanup errors, URLs, logs, quotas and tests.
- Add incremental PR reviews and workflow concurrency.

### Fixes
- Use mocked approval clock in cmd_approve and drop stale judge text.
- Drop dead helpers left after slimming and test error contracts.
- Harden hunk parsing, empty valid lines, and network fallback.

## 2.4.0 - 2026-11-17

### Features
- Add review-ready code rule and Python review invariants.
- Support native SessionStart for Antigravity.

### Fixes
- Skip test suite on pre-push when there are no new commits.
- Keep review-ready and python rules within 1KB budget.

### Performance
- Parallelize pytest with xdist and cache template git repos.

## 2.3.0 - 2026-11-17

### Features
- add design debate mode, evidence flags, effort, and model deny-list (#78)

## 2.2.0 - 2026-11-16

### Features
- Add skills CLI, test-audit review mode, and changed-scope gate defaults.

## 2.1.0 - 2026-11-13

### Features
- Add surgical-changes and pull-requests core rules.

### Fixes
- Add run timeout, domain exceptions, and complexity cleanup.

## 2.0.0 - 2026-11-12

### Breaking changes
- Remove interactive TUIs and legacy packages, slim down engine for AI agents.

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

