---
name: spec-finish
description: "Seals and completes the active specification strictly upon verified PASS status and explicit human sign-off."
---

# Spec Finish Assistant Skill (Final Gate)

## Workflow
1. Verify that the recorded verification status is strictly `PASS` and scenario traceability is complete. If status is `FAIL` or missing, STOP immediately.
2. Request explicit human sign-off: *"Verification 100% successful with immutable evidence. Do you confirm sealing this feature?"*.
3. Upon confirmation, execute `spec finish`.
4. Summarize the completed feature, files modified, and evidence path.

