# Corporate rules

Company-specific, always-on rules and scripts. A company is just a folder here: every
folder present is installed by the regular user install, with no flag to pass.

```bash
ai-governance install --scope user --agent claude --agent antigravity   # the engine and every pack below
```

Packs are gitignored: they live only in the local checkout (read by the editable install,
`uv tool install --editable ./packages/ai-governance`) or in `AI_GOVERNANCE_CORPORATE_DIR`,
so company content never reaches this repository. Changing companies means swapping the
folder and running the install again: the old pack's files are removed, the new one's added.
Only the agents named in that install are refreshed, so pass every agent you use; the others
keep the previous pack's rules until their next install.

Layout of `<company>/`:

- `rules/*.md` — always-on instructions, installed as
  `~/.claude/rules/ai-governance-<company>-<name>.md` (Claude Code, copied as is) and
  `~/.gemini/config/rules/ai-governance-<company>-<name>.md` (Antigravity, with
  `trigger: always_on` front matter added). Codex has no per-file global rules, so packs are
  not rendered for it; the install prints one warning naming the skipped packs.
- `scripts/*` — files linked into `~/.local/bin` (override with `AI_GOVERNANCE_BIN_DIR`);
  they are removed when the last installed agent is uninstalled. If two packs ship a script
  with the same name, the first pack alphabetically wins and the install warns.

Packs never hold credentials: tokens, passwords and personal data stay in the environment or
the OS keychain.
