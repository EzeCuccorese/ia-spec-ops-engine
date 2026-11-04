# Changelog

## Unreleased

### Features
- personal: add personal preferences pack support (`$AI_GOVERNANCE_PERSONAL_DIR` or `~/.config/ai-governance/personal/`), installed as symlinks for Claude, Antigravity, and Codex, with missing directory safety.
- install: add Claude user-scope entry files (`~/.claude/CLAUDE.md` and `~/.claude/AGENTS.md`) using marker blocks to preserve existing content outside markers.
- codex: instruct Codex in its AGENTS.md block to read both `company/` and `personal/` rule directories once per session.

### Fixes
- corporate: preserve previously installed corporate rules and scripts when the corporate root directory does not exist, warning instead of removing them.
