# Git, Commits, and Workflow

## Core Working Rules

- **`git commit` and `git push` are freely permitted on feature branches** (any branch other than `main`, `master`, `develop`, `staging`). On protected branches (`main`, `master`), explicit written authorization from the user is required.
- **FORBIDDEN to mention Artificial Intelligence usage**: Do not include phrases like "Generated with Claude Code", robot emojis such as 🤖, or any reference to AI generation in PR titles, descriptions, commits, or comments.

---

## Pre-Push Requirements

- Run test suites across all modified projects prior to pushing:
  - Java (Gradle): `./gradlew test`
  - Java (Maven): `./mvnw test`
  - Node.js: `npm test`
- If any test fails: **do not push**. Report the test failure transparently and resolve the root cause first.
- **Never use `--no-verify`.** If a pre-commit or pre-push hook fails (e.g., `lint-staged`, `eslint`), fix all linting and format errors; never bypass repository verification hooks.

---

## Commit Message Format — Conventional Commits

`type(scope): description`

| Type | Usage |
|---|---|
| `feat` | New user-facing feature or API capability |
| `fix` | Bug fix |
| `refactor` | Code refactoring without behavioral changes |
| `test` | Adding or updating unit/integration tests |
| `docs` | Documentation changes or migration scripts only |
| `chore` | Build tasks, dependency updates, CI configs — no production code change |
| `perf` | Performance optimization |
| `ci` | Modifications to CI/CD pipelines and workflows |

```text
type(scope): description in lowercase imperative mood

Optional commit body explaining the technical context and rationale (why, not what).
```

- Description written in English, imperative mood, lowercase, no trailing period.
- Breaking changes: add `BREAKING CHANGE:` header in the commit footer.

---

## Pre-Branch and Pre-PR Checks

- Read repository workflows first: `ls .github/workflows/`. Each project defines customized CI/CD rules; branch prefixes (`hotfix/`, `feature/`, `release/`) often trigger specific pipeline logic. **Do not assume** default conventions — inspect `.github/workflows/` files directly.

---

## Standard Pre-Approved Commands

- `git status`, `git diff`, `git log`, `git branch`, `git remote`
- `git add`, `git commit`, `git push` on non-protected feature branches
- `git fetch`, `git pull`
- `gh pr create`, `gh pr view`, `gh pr list`, `gh run view`, `gh api`
- `ls`, `find`, `grep`, `rg`
- `./gradlew` and `gradle` commands with any standard task targets
