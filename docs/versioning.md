# Versioning & Release Strategy

> **Audience: maintainers.** This document describes how releases are produced and what to do when things go wrong. For user-facing update instructions see the [README](../README.md#versioning).

---

## Architecture & Design Principles

* **100% Python cross-platform architecture:** Contains 0% `.sh`, 0% `.bat`, 0% `.bats`. Works natively on Windows, macOS, and Linux.
* **Binary installation and entrypoints:** Registered in `pyproject.toml` `console_scripts` (`install`, `uninstall`, `sdd`, `create-worktree`, `generate-workspace`, `sync-toolkit`, `toolkit-menu`, `update-toolkit`, `run-local`, `kube-env`, etc.).
* **Dual execution mode:** ALL CLI scripts support Interactive TUI mode and CLI flags with full `--help` documentation.
* **Spec-Kit aligned 8-phase SDD engine:** Supports `specify`, `clarify`, `plan`, `checklist`, `tasks`, `analyze`, `exec`, `converge`, and `quick`.
* **Dynamic End-to-End AI Agent adaptation matrix:** Compatible with Antigravity 2.0, Gemini CLI, Claude Code, GitHub Copilot, Cursor, and ChatGPT.

---

## Model overview

- `main` is the only long-lived branch.
- Stable releases are tags: `v1.0.0`, `v1.1.0`, `v2.0.0`.
- Beta releases are tags: `v1.3.0-beta.1`, `v1.3.0-beta.2`.
- **No permanent release branches.** See [Hotfixes](#hotfixes) for when a temporary one is needed.
- **No permanent `beta` branch.** Beta is rolling — only the latest `-beta.N` tag is supported.

When a user runs `update-toolkit`, git checks out a tag directly. This puts the repo in **detached HEAD** — `HEAD` points to the tagged commit rather than to a branch. That is expected and correct: the toolkit is consumed, not developed, from that state. The script prints a reminder to that effect.

---

## Cutting a stable release

You don't run a release command. The flow is driven by Conventional Commits on `main`:

1. Merge feature PRs into `main` using Conventional Commit prefixes (`feat:`, `fix:`, `feat!:`, etc.).
2. After each push to `main`, the `release-please` GitHub Actions workflow opens (or updates) a Release PR titled `chore(main): release X.Y.Z`. It contains the proposed version bump and the `CHANGELOG.md` update.
3. When ready to ship, **merge the Release PR**. `release-please` then creates the `vX.Y.Z` tag and publishes the GitHub Release automatically.

That's the entire flow for a normal release. No manual tagging, no manual changelog editing.

### How release-please computes the version

| Commit prefix | Bump |
|---|---|
| `feat:` | MINOR |
| `fix:`, `perf:`, `refactor:` | PATCH |
| `feat!:` or `BREAKING CHANGE:` in body | MAJOR |
| `docs:`, `chore:`, `test:`, `ci:` | none (no bump) |

Scopes are **required**: `feat(test-runner): ...`. The `commit-msg` hook in `.githooks/` enforces this.

### Overriding the computed version

- **Force a specific version** — add an empty commit with `Release-As:` in the message:
  ```bash
  git commit --allow-empty -m "chore: release 2.0.0" -m "Release-As: 2.0.0"
  ```
- **Force a major bump for a non-breaking commit** — use `feat!:` or add `BREAKING CHANGE:` in the commit body.

---

## Cutting a beta release

Betas are tagged **manually** — release-please ignores prerelease tags and will not interfere.

```bash
git checkout main && git pull
git tag -a v1.3.0-beta.1 -m "Beta release v1.3.0-beta.1"
git push origin v1.3.0-beta.1
```

Optionally add a `## [1.3.0-beta.1]` section to `CHANGELOG.md` and commit it on `main` before tagging.

**Beta is rolling.** If a bug is found on `v1.3.0-beta.1`: fix it on `main`, then cut `v1.3.0-beta.2`. Do not patch `beta.1` — no one should be pinned to it.

---

## Hotfixes

### main has not diverged from the latest stable

Commit the fix on `main` with a `fix:` prefix. The open Release PR will pick it up and the next merge will produce a patch release.

### main has diverged incompatibly

This means `main` already has unreleased features that should not ship in the patch. Create a temporary release branch from the tag, fix it there, tag manually, then cherry-pick back:

```bash
git checkout -b release/v1.2.x v1.2.0
# apply the fix with a Conventional Commit message
git commit -m "fix: ..."
git tag -a v1.2.1 -m "Hotfix v1.2.1"
git push origin release/v1.2.x v1.2.1
git checkout main
git cherry-pick -x <fix-sha>
git push origin main
```

`release-please` does not run on `release/*` branches, so the manual tag is the source of truth for the patch release. The branch can be deleted after the cherry-pick is confirmed on `main`.

> **Keep release branches temporary.** There is no value in maintaining permanent release branches for this toolkit — teams update to the latest stable. A branch exists only long enough to produce the patch tag and confirm the fix is back on `main`.

---

## Why no permanent release branches

Some projects keep a `release/v1.x` branch alive indefinitely so users pinned to that major can receive fixes. This toolkit does not do that because:

- All consumers update to latest stable via `update-toolkit` — no one is intentionally pinned to an old minor.
- The overhead of maintaining parallel lines (cherry-picks, double release-please configs) is not justified.
- The risk scenario (new feature on `main` blocks a patch) is handled by the lazy branch approach above, created on demand only when the situation actually arises.

If the toolkit ever gains consumers who deliberately stay on older majors, revisit this decision.

---

## What detached HEAD means and why it is correct here

When `update-toolkit` runs, it executes `git checkout refs/tags/vX.Y.Z`. Because a tag is a fixed label on a commit — it never moves — git has no branch to attach `HEAD` to. The result is **detached HEAD**: `HEAD` points directly to the commit rather than to a branch pointer.

```
# Normal (on a branch):
HEAD → main → commit abc

# Detached (on a tag):
HEAD → commit abc   (no branch in the middle)
```

Nothing is broken. Files are correct, history is intact. The only consequence is that any new commit made from this state has no branch to advance, so it becomes orphaned the moment you check out something else. That is exactly why the script prints `"do not commit on this checkout"` — the toolkit is meant to be used from a frozen release state, not developed from it. Detached HEAD is the correct representation of that intent.
