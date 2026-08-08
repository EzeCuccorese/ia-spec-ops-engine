# Global System Rules (SDD & Dev Toolkit)

These guidelines govern development, quality, and security across all projects managed by the `sdd` toolkit.

---

## 1. Commit Conventions (Conventional Commits)
* Use the standard format: `type(scope): description` (lowercase, imperative mood, no trailing period).
* Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
* **Forbidden AI Attribution**: Do not include phrases regarding AI assistance or robot emojis in commits or PRs.

---

## 2. Security and Privacy (OWASP)
* **Secret Protection**: Never commit API keys, tokens, passwords, or connection strings to version control.
* **Privacy (No PII Logging)**: Do not log personally identifiable information (email, national IDs, names) or financial credentials.
* **Input Validation**: Validate all inputs at system edge boundaries before processing.

---

## 3. Coding Practices and Immutability
* **Bounded Code (SDD Minimal Implementation)**: Write code strictly focused on satisfying the contract defined in `.specify/spec.md` and passing unit tests.
* **Mutation Verification**: Following any database or API mutation, perform a read operation to verify correctness before completing the task.
* **Databases**: Before executing data mutations in production or MongoDB environments, export a JSON backup (`<database>_<collection>_<timestamp>.json`).
