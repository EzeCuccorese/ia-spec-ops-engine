# Quality Gates & Definition of Done (DoD) Checklist

**Feature**: {feature_name}  
**Target Branch**: {branch_name}  
**Date**: {date}

---

## 🛡️ 1. Technical Quality Gates
- [ ] **Contract Compliance**: All endpoints, DTOs, and event payloads match schemas in `plan.md`.
- [ ] **Test Coverage**: Critical business logic covered with unit/integration tests (JaCoCo $\\ge 90\\%$, pytest/vitest $\\ge 85\\%$).
- [ ] **Deterministic Clean Run**: All automated tests pass in hermetic environments (`pytest`, `npm test`, `./gradlew test`).
- [ ] **Static Analysis**: Linter passed with 0 errors and 0 warnings (`ruff check`, `npm run lint`, `cargo clippy`).

---

## 🔒 2. Security & Compliance
- [ ] **Zero Hardcoded Secrets**: No API keys, credentials, or private tokens in source code or diffs.
- [ ] **Zero PII in Logs**: No personal data (names, emails, IDs, credit cards) in application logs.
- [ ] **Input Validation**: All external inputs validated at system boundaries with Zod/Pydantic/DTOs.
- [ ] **Database Safety**: MongoDB backups executed before data mutations (with explicit "OK WRITE" confirmation).

---

## 📝 3. Git & Pull Request Readiness
- [ ] **Conventional Commits**: All commit messages follow `type(scope): description` in imperative English.
- [ ] **ZERO AI MENTIONS**: Absolutely no AI mentions or robot emojis in commit messages, code comments, or PR descriptions.
- [ ] **Documentation**: API contracts and architecture notes updated where applicable.
