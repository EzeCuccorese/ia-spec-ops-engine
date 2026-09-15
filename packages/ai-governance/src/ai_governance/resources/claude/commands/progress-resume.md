---
description: Resume an explicit or context-matched task
---

With an id, run `progress view <id> --full`. Without one, first try
`progress here --json`; if it is ambiguous, show `progress list --json` and ask the
user to choose. Summarize status, pending steps, repositories, and verified facts.
Use `progress resume <id>` only for a paused task; reopening a closed task requires
the separate explicit `progress reopen <id>` transition.

Arguments: $ARGUMENTS
