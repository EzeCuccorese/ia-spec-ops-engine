# Corporate rules

Company-specific, always-on rules, scripts and skills. A company is just a folder here: every
folder present is installed by the regular user install, with no flag to pass.

```bash
ai-governance install --scope user --agent claude --agent antigravity   # the engine and every pack below
```

Packs are gitignored: they live only in the local checkout (read by the editable install,
`uv tool install --editable ./packages/ai-governance`) or in `AI_GOVERNANCE_CORPORATE_DIR`,
so company rules, scripts and corporate skills never reach git (unlike personal skills, which
live versioned in [`skills/`](../../skills)). Changing companies means swapping the
folder and running the install again: the old pack's files are removed, the new one's added.
Only the agents named in that install are refreshed, so pass every agent you use; the others
keep the previous pack's rules until their next install.

Layout of `<company>/`:

- `rules/*.md` — always-on instructions, installed as **symlinks** to the source file, so you
  edit them in one place only:
  `~/.claude/rules/ai-governance-<company>-<name>.md` (Claude Code) and
  `~/.gemini/config/rules/ai-governance-<company>-<name>.md` (Antigravity). Because a link
  cannot add anything, each file carries the front matter itself (Antigravity needs it,
  Claude Code ignores the unknown key):

  ```markdown
  ---
  trigger: always_on
  ---
  # Title of the rule

  Body...
  ```

  Old copies made by earlier versions are replaced by links on the next install. If you move
  or delete the checkout, the links break. Codex receives corporate rules linked into
  `$CODEX_HOME/ai-governance/company/<company>-<name>.md`; its `AGENTS.md` block instructs
  Codex to read `company/` once per session.
- `scripts/*` — files linked into `~/.local/bin` (override with `AI_GOVERNANCE_BIN_DIR`);
  they are removed when the last installed agent is uninstalled. If two packs ship a script
  with the same name, the first pack alphabetically wins and the install warns.
- `skills/<name>/SKILL.md` — company-specific skills (plus optional scripts/files), synced as
  managed directory copies into `~/.claude/skills/<name>`, `~/.agents/skills/<name>` (Codex) and
  `~/.gemini/config/skills/<name>` (Antigravity). Edit the source here and run
  `ai-governance skills sync` to update the copies. Corporate skills stay gitignored inside this
  folder and must never exist in git (use [`skills/`](../../skills) at the repo root only for
  personal skills).

Packs never hold credentials: tokens, passwords and personal data stay in the environment or
the OS keychain.
