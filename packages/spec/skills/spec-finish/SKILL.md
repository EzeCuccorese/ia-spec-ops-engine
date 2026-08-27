---
name: spec-finish
description: "Seals and completes the active specification after verified PASS status."
---

# Spec Finish Assistant Skill

## Workflow
When all tasks are complete and `spec verify` recorded `PASS`:
1. Execute `spec finish`.
2. Verify that the feature transition to `complete` succeeded.
3. Summarize the completed feature, files modified, and verified test results for the user.
