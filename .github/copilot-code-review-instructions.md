# Code Review Guidelines for GitHub Copilot

When reviewing Pull Requests in this repository, follow these standards:

## Repository Architecture & Scope
- This repository contains independent Python packages:
  - `packages/ai-governance`: rules, telemetry, progress tracking, context-frugality tools.
  - `packages/workspace`: Git worktree management, quality gates, environment tools.
  - `packages/spec`: specification workflows and agent adapters.
- Keep dependencies isolated between packages; do not create circular or unnecessary cross-dependencies.

## Code Quality & Python Standards
- Python 3.11+ patterns: prefer type hints everywhere (`typing` or built-in generics like `list[str]`, `dict[str, Any]`).
- Check for proper error handling and explicit exceptions rather than bare `except Exception:`.
- Avoid unnecessary external dependencies when standard library or existing helpers suffice.
- Ensure CLI outputs, error messages, and documentation are written in English.

## Review Focus
- **High priority**: Logic bugs, security flaws (hardcoded credentials, unsafe shell calls, path traversal), performance regressions, race conditions.
- **Medium priority**: Missing test cases for new logic or edge cases, breaking changes to public APIs or CLI interfaces.
- **Low priority / Avoid**: Purely subjective stylistic nits that a linter/formatter would resolve.
- Be concise and provide actionable code snippets where a fix is recommended.
