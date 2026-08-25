# Executable Tasks Breakdown (`tasks.md`)

**Feature**: {feature_name}  
**Date**: {date}  
**Total Tasks**: {total_count}

---

## 📋 Task List Ordered by SDD Pillars

### Pillar 1: Contracts & Interfaces First
- [ ] `[T1]` Define formal DTOs/Zod schemas for `{feature}` in `{path}`.
- [ ] `[T2]` Define service interface and repository contracts.

### Pillar 2: Test Harness (Test-First)
- [ ] `[T3]` Implement unit tests for `{component}` validating input edge cases (Red).
- [ ] `[T4]` Implement integration test for API endpoint `{route}`.

### Pillar 3: Minimal Implementation
- [ ] `[T5]` Implement domain service logic for `{feature}` in `{path}`.
- [ ] `[T6]` Implement HTTP controller and wire dependency injection.

### Pillar 4: Early Detection & Quality Gate
- [ ] `[T7]` Run static analysis linter and fix any warnings.
- [ ] `[T8]` Execute full regression test suite and verify Gherkin acceptance criteria.
