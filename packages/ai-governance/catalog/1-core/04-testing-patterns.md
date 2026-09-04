# Testing Patterns & Test-Driven Development (TDD)

## Execution Invariants
- **AAA Pattern**: Every test must follow strict Arrange-Act-Assert structure with visual separation.
- **Test-First Methodology**: Write failing tests before writing production code.
- **Test Pyramid**:
  1. *Unit Tests*: Fast, isolated, in-memory tests for domain logic without heavy framework boots or network calls.
  2. *Integration Tests*: Verify infrastructure adapters against real dependencies using Testcontainers (Postgres, Mongo, Kafka) or WireMock.
  3. *End-to-End Tests*: Minimal smoke tests verifying critical user journeys.
- **Mocking Boundaries**: Mock only across architectural boundaries (I/O, external APIs). Do not mock domain logic or internal implementation details.
- **Coverage & Determinism**: Target $\ge 85\%$ branch coverage on domain/application logic. Zero flaky tests (no `Thread.sleep`, use polling with awaitility).
