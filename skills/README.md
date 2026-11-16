# Personal skills

Personal third-party skills live here (`skills/<name>/SKILL.md`, plus optional scripts and
supporting files) and are **versioned in git**.

Each skill lives in this single directory and is exposed to every installed agent through a
directory symlink:

- Claude Code: `~/.claude/skills/<name>`
- Codex: `~/.agents/skills/<name>`
- Antigravity: `~/.gemini/config/skills/<name>`

## Boundaries (what stays out of this folder)

- **Corporate skills never go in git.** Company-specific skills belong in
  `packages/corporate-rules/<company>/skills/<name>/` (gitignored, alongside company rules
  and scripts).
- **Orca skills stay with Orca.** `orchestration`, `orca-cli`, `orca-computer-use` and
  `computer-use` are maintained by Orca outside this repository and are ignored by
  `ai-governance skills` (they cannot be added or migrated here).
- **Bundled skills** (`taskflow`, `test-audit`) ship inside the `ai-governance` package.

## Commands

Install the CLI in editable mode so it reads this checkout directly (or point
`AI_GOVERNANCE_PERSONAL_DIR` at another parent holding `skills/`):

```bash
uv tool install --editable ./packages/ai-governance
ai-governance skills list
ai-governance skills add ./path/to/skill
ai-governance skills sync
ai-governance skills migrate --dry-run
ai-governance skills rm <name>
```
