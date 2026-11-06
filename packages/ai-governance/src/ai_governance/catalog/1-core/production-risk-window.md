# Production Risk Window

## Invariants
- **Production Changes Blocked Outside Safe Window**: Actions that can break production (deployments, infrastructure, production configuration, branch protection, permissions) must never run outside the safe risk window. Prepare the work, but defer execution to the next business day at the start of business.
- **Configurable Cutoff Hours**: Default cutoff is 16:00 on Monday–Thursday and 13:00 on Friday (`risk_window.cutoff_hour` and `risk_window.friday_cutoff_hour`). Run `ai-governance config show` to inspect the active configuration.
- **Non-Production Environments Are Warning-Only**: For staging, feature branches, and non-production canary environments, cutoff hours are advisory warnings only.
- **Exemptions**: Local machine actions and low-risk reversible changes (such as PRs under review, Jira tickets, or commits on own branches) are exempt.
