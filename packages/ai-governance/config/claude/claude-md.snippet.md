<!-- managed by specops-ai-governance: start -->

## Progress Tracking

Tool: `progress` (CLI installed in `~/.local/bin/progress`). Store in `~/.claude/progress/`. Each task is identified by its **Jira key** (`ONB-1164`) or a freeform slug. It is never named after a single repo: real-world tasks span multiple repositories. Repositories are an attribute of the task, never its name.

- **No automatic load on session start.** When resuming work on a task, run `progress show <id>` (or `--full` to inspect the complete log) instead of assuming clean slate or dragging old context.
- `progress here` automatically resolves the active task by current git branch or directory.
- Before ending a session, persist state: `progress new <id> --title "..."` or update steps, then advise the user to run `/clear`.

## Context Frugality

- Test output is automatically condensed by `frugal --post-bash`: green passed tests are trimmed away, preserving only failing test traces and summary lines.
- To bypass trimming for a specific command, append `#nofrugal` or set `FRUGAL=0`.
- Massive directory listings or JSON payloads are summarized with `head` and `tail` projections.

<!-- managed by specops-ai-governance: end -->
