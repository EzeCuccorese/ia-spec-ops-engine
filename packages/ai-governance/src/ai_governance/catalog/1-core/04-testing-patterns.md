# Testing Patterns

- Before writing a test, name the behavior it protects, the regression that breaks it and why existing tests miss it; else skip it.
- Assert observable results (exact message, state, order) at the public boundary, never private calls, call shape or `mock_calls`.
- Write the failing test before the code that makes it pass.
- Unit: fast, isolated. Integration: real dependencies (Testcontainers, WireMock). End-to-end: critical journeys only.
- Mock only across architectural boundaries; a mock never implements the behavior under test.
- One test per contract at the cheapest real layer; merge variants into parametrized cases.
- No assertion-free tests, self-comparisons, expected values computed by the code under test, or tests that only hit lines.
- No tests of language behavior, log level or wording or signatures; same bar for review asks.
- No production seams used only by tests. No sleeps or real clocks: inject time, poll.
- Arrange-Act-Assert, one behavior per test.
