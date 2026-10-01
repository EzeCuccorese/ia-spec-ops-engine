# Security Policy

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub private vulnerability reporting](https://github.com/EzeCuccorese/ia-spec-ops-engine/security/advisories/new).
You will get an answer within a few days; fixes land on `main` and the report is published
once a fix is available.

## Scope

The latest `main` is supported. The tools run locally and never need credentials in this
repository: tokens and personal data belong in the environment, in the user's own config
directory (for example the Atlassian profiles in `~/.config/ai-governance/atlassian.json`) or
in the OS keychain. Corporate packs under `packages/corporate-rules/` are gitignored and must
never contain credentials.
