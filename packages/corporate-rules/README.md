# Corporate rules

Company-specific packs installed at user scope only when requested. Packs are gitignored:
they live only in the local checkout, read by an editable install
(`uv tool install --editable ./packages/ai-governance`) or from `AI_GOVERNANCE_CORPORATE_DIR`,
so company content never reaches this repository.


```bash
ai-governance install --scope user --agent claude --corporate <pack>
ai-governance uninstall --scope user --corporate <pack>   # removes the whole pack
```

Each pack is a folder named after the company:

- `rules/*.md` — always-on instructions, installed as
  `~/.claude/rules/ai-governance-<pack>-<name>.md` (Claude Code) and
  `~/.gemini/config/rules/ai-governance-<pack>-<name>.md` (Antigravity). Codex has a single
  global instructions block, so packs are not rendered for it.
- `scripts/*` — executables linked into `~/.local/bin` (override with `AI_GOVERNANCE_BIN_DIR`).

Packs never hold credentials: tokens, passwords and personal data stay in the environment or the
OS keychain.
