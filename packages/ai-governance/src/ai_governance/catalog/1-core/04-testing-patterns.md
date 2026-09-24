# Testing Patterns & Test-Driven Development (TDD)

- Every test follows strict Arrange-Act-Assert structure with visual separation.
- Write the failing test before the production code that makes it pass.
- Unit tests: fast, isolated, no framework boot or network calls.
- Integration tests: real dependencies via Testcontainers (Postgres, Mongo, Kafka) or WireMock.
- End-to-end tests: minimal smoke tests for critical user journeys only.
- Mock only across architectural boundaries (I/O, external APIs); never mock domain logic or internals.
- Target >=85% branch coverage on domain/application logic. Zero flaky tests: no `Thread.sleep`, poll instead.
