# Changelog

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

