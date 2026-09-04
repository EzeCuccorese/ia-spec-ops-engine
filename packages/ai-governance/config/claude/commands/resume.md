---
description: Resume a task from the global cross-session progress tracker
---

Resume work on an existing task from the global progress tracker:

- If `$ARGUMENTS` provides an ID, run `progress show $ARGUMENTS --full` to load the task state and complete log.
- If no argument is provided, run `progress here` to resolve from the current branch or directory.
- Summarize where the task stands (status, next steps, affected repositories) and propose the next action.

Arguments: $ARGUMENTS
