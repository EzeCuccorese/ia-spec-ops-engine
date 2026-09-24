# Git Workflow & Conventional Commits

## Invariants
- **Conventional Commits**: Commit messages must follow `type(scope): description` format in lowercase, imperative mood, English, with no trailing period.
  - Allowed types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `perf`, `build`, `ci`.
  - Example: `feat(auth): implement jwt token generation`
- **Atomic Commits**: Each commit must represent a single, coherent, verifiable change with passing tests.
