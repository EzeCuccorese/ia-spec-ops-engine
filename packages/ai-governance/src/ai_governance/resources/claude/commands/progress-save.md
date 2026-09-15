---
description: Save compact progress for the current task
---

Resolve the task with `progress here --json`, unless the user supplied an explicit id.
Create a task only after the user identifies it. Update its summary, steps, facts,
references, links, repositories, and long-form notes through the corresponding
`progress` commands. Facts are reserved for verified information that should not be
re-investigated. End by running `progress view <id> --json` and confirm the saved state.

Never invent a Jira issue or transition one as a side effect of saving progress.

Arguments: $ARGUMENTS
