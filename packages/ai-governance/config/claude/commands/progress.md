---
description: Save current task state to the global cross-session progress tracker
---

Save the active task progress using the `progress` CLI tool:

1. If the task ID is unknown, run `progress here` to resolve from current git branch/repo.
2. If it does not exist yet, create it with `progress new <id> --title "..."`.
3. Update what changed since last time: summary, completed steps, affected repositories and links.
4. Record major decisions or bug investigation notes to the markdown log.
5. Finish with `progress show <id>` to display the updated state.
6. If session context is high, suggest the user run `/clear` — the next session can easily resume with `/resume <id>`.

Arguments: $ARGUMENTS
