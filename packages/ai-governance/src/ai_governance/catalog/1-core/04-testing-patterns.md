# Testing Patterns

- Before writing a test, name the observable behavior it protects, the credible regression that makes it fail, and why existing tests miss it; if you can't, don't write it.
- Assert observable results at the public boundary, never private calls or call shape.
- Write the failing test before the code that makes it pass.
- Unit tests: fast and isolated. Integration: real dependencies (Testcontainers, WireMock). End-to-end: critical journeys only.
- Mock only across architectural boundaries; a mock never implements the behavior under test.
- One test per contract at the cheapest real layer; merge variants into parametrized cases.
- No assertion-free tests, self-comparisons, expected values computed by the code under test, or tests that only hit lines.
- No production seams used only by tests. No sleeps or real clocks: inject time, poll.
- Arrange-Act-Assert, one behavior per test.
