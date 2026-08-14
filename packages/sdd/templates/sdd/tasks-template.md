# Executable Task Breakdown: {Feature Title}

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Checklist**: [checklist.md](./checklist.md)  
**Overall Status**: ⏳ PENDING  

---

## 📋 SDD Execution Phases (4 SDD Pillars)

### Phase 1: Contracts & Interfaces (Spec First)
- [ ] **TASK-01: Define data schemas and types**
  - **Objective**: Create types, DTOs, Zod schemas / domain interfaces.
  - **Success Criteria**: Linter and type checker pass with zero warnings.
  - **Files**: `src/types/...`, `src/schemas/...`

### Phase 2: Test Harness & Red Suite
- [ ] **TASK-02: Write automated unit/integration test suite**
  - **Objective**: Create tests based on Gherkin scenarios in `spec.md`.
  - **Success Criteria**: Test suite executes and fails strictly for missing logic (Red).
  - **Files**: `tests/...`

### Phase 3: Minimal Implementation (Green)
- [ ] **TASK-03: Implement business service & endpoints**
  - **Objective**: Code minimal business logic required to pass TASK-02 tests.
  - **Success Criteria**: Test suite passes 100% (Green).
  - **Files**: `src/services/...`, `src/controllers/...`

### Phase 4: QA, Security & Converge Validation
- [ ] **TASK-04: Post-mutation read verification & Quality Gate Audit**
  - **Objective**: Execute post-mutation confirmation read, log audit for PII, and verify checklist.
  - **Success Criteria**: All `checklist.md` items pass, clean build without side effects.
