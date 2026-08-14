# Quality Gate Checklist: {Feature Title}

**Feature ID**: `{feature-name}`  
**Spec Reference**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)  

---

## 📋 Definition of Done (DoD) Criteria

### 1. Code Quality & Standards
- [ ] Contracts defined first (Zod/DTOs) before implementing business logic.
- [ ] Clean linter run (`npm run lint` / `oxlint` / `./gradlew check`) with 0 errors/warnings.
- [ ] No hardcoded secrets, API keys, or credentials.
- [ ] No PII (Personally Identifiable Information) written to logs.

### 2. Testing & Coverage
- [ ] Test Harness written first (Red test failing for expected contract reasons).
- [ ] Minimal implementation passes test suite 100% (Green).
- [ ] Unit/Integration test coverage meets threshold (JaCoCo $\ge$ 90% for critical logic).

### 3. Post-Mutation Verification (Golden Rule)
- [ ] Post-mutation confirmation read (GET HTTP request or DB lookup) verified after writes.

### 4. Git & Commits
- [ ] Conventional Commit format (`type(scope): description`) in lowercase, imperative mode.
- [ ] ZERO references to AI or robot emojis in commits, PRs, or code comments.
