# Code Review Guidelines

When reviewing Pull Requests, enforce these standards:

## Repository Architecture & Scope
- This repository contains two independent Python packages:
  - `packages/ai-governance`: rules, task flow (taskflow) & multi-provider design debates, context-frugality tools, and Atlassian utilities.
  - `packages/workspace`: deterministic quality gates (`ws check`, `ws hooks`), design limits (`ws design`), stack detection (`ws detect`), and command condensation (`ws run`, `ws condense`, `ws log`).
- Keep dependencies isolated between packages; do not create circular or unnecessary cross-dependencies.
- Ensure CLI outputs, error messages, and documentation in this repository are written in English.

## Code Quality & Python Standards
- Python 3.11+ patterns: prefer explicit type hints everywhere (`list[str]`, `dict[str, Any]`, explicit return types).
- Avoid unnecessary external dependencies when standard library or existing helpers suffice.

## Types & API Contracts
- Mark parameters or fields optional only when supported callers legitimately omit them.
- Validate upstream shapes before indexing; reject `NaN`, `Infinity`, and overflowing numbers before range checks.
- Prefer explicit operations over sentinel values that silently alter API semantics; use plural nouns for REST paths.

## Errors, Resilience & Security
- Map timeouts and connection failures to domain status errors; avoid bare `except Exception:` swallowing errors.
- Degrade optional reads gracefully without breaking the main flow, while failing permission/security guards closed.
- Exclude credentials, secrets, and request bodies (including nested fields) from logs and trace spans.
- Avoid regexes with overlapping alternatives or nested repetition on untrusted input; close file handles, pools, and subprocesses deterministically.
- On partial multi-step writes, report succeeded vs. failed steps and preserve the original error if cleanup fails.

## Testing Quality & Confidentiality
- Assert contractual error codes or stable diagnostics rather than bare exception types.
- Name every parametrized test case descriptively and avoid mocking the unit under test.
- Flag any external PR templates, commit messages, ticket text, or user-facing messages that leak forbidden internal engine tooling names.

## Review Focus
- **High priority (P1)**: Logic bugs, security flaws (credentials in logs, unsafe shell calls, path traversal, ReDoS), race conditions, resource leaks, broken API contracts.
- **Medium priority (P2)**: Unhandled timeouts/errors, missing `NaN`/`Infinity`/boundary validation, weak tests asserting bare exceptions, breaking changes to public APIs or CLI interfaces.
- **Low priority (P3) / Avoid**: Concrete local simplifications only; skip purely subjective stylistic nits that a linter or formatter resolves.
- Be concise and provide actionable code snippets or GitHub suggestion blocks where a fix is recommended.
