# Corporate rules

Company-specific, always-on rules, scripts and skills. Store each company folder outside Git
(by default under `~/.config/ai-governance/corporate-rules/`), or in a git-ignored, untracked
directory such as `config/ai-governance/corporate-rules/` when running an editable checkout. Set
`AI_GOVERNANCE_CORPORATE_DIR` to another private directory when needed. The installer rejects
tracked or unignored locations inside a repository. Every company folder in the selected directory
is installed by the regular user install, with no flag to pass.

```bash
ai-governance install --scope user --agent claude --agent antigravity
```

Packs live outside the repository and are never added to or published with it. Company work
artifacts must describe only the company product, behavior, and code changes. Third-party skills
live versioned in [`skills/`](../../skills). Changing companies means selecting the relevant
private directory and running the install again: the old pack's files are removed, the new one's
added.
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
  or delete the private source directory, the links break. Codex receives corporate rules linked into
  `$CODEX_HOME/ai-governance/company/<company>-<name>.md`; its `AGENTS.md` block instructs
  Codex to read `company/` once per session.
- `scripts/*` — files linked into `~/.local/bin` (override with `AI_GOVERNANCE_BIN_DIR`);
  they are removed when the last installed agent is uninstalled. If two packs ship a script
  with the same name, the first pack alphabetically wins and the install warns.
- `skills/<name>/SKILL.md` — company-specific skills (plus optional scripts/files), synced as
  managed directory copies into `~/.claude/skills/<name>`, `~/.agents/skills/<name>` (Codex) and
  `~/.gemini/config/skills/<name>` (Antigravity). Edit the source in the private directory and
  run `ai-governance skills sync` to update the copies. Corporate skills must never enter git.
  Third-party skills supplied with the project live in [`skills/`](../../skills).

Packs never hold credentials: tokens, passwords and personal data stay in the environment or
the OS keychain.

Context budget & language hygiene: write every corporate rule and skill in **English**—including
filenames, skill folder names, and frontmatter `name:` slugs—for lower token cost and consistent
cross-agent adherence (user-facing chat replies still follow the user's language). Keep
`rules/*.md` for short, always-on invariants (security, approvals, communication, surgical diffs).
Put reference manuals, glossaries, runbooks, and repo- or tool-specific guides into
`skills/<name>/SKILL.md` so they load on demand across Claude Code, Antigravity, and Codex.
`ai-governance install`, `skills sync`, and `doctor` warn if always-on rules exceed 40 KB (~10k
tokens) per agent or if the installed skill catalog metadata grows past the safe threshold.
