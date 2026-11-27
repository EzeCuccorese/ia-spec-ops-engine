# Changelog

## Unreleased

### Features
- pr-watch: detect bot authors and add `--ignore-authors` and `--ignore-draft-bots` filters for comment alerts.
- slack-notify: accept user tokens (`xoxp-`), add `--attach` file uploads and `--token-env`; failed upload steps raise a clear error with the Slack error code.
- slack-notify: read defaults from the user-level `[slack]` config table (`--channel default|dm` aliases) and add `slack-notify replies` to read a thread as JSON lines.
- personal: add personal preferences pack support (`$AI_GOVERNANCE_PERSONAL_DIR` or `~/.config/ai-governance/personal/`), installed as symlinks for Claude, Antigravity, and Codex, with missing directory safety.
- install: add Claude user-scope entry files (`~/.claude/CLAUDE.md` and `~/.claude/AGENTS.md`) using marker blocks to preserve existing content outside markers.
- codex: instruct Codex in its AGENTS.md block to read both `company/` and `personal/` rule directories once per session.

### Fixes
- corporate: preserve previously installed corporate rules and scripts when the corporate root directory does not exist, warning instead of removing them.
