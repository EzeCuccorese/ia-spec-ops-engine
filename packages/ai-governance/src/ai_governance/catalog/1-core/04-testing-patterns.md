# Testing Patterns

## Invariants
- **Justify Every Test**: Before writing a test, identify the observable behavior it protects, the credible regression that would break it, and why existing tests miss it. If you cannot, skip writing it.
- **Public Boundary Assertions**: Assert observable results at the public boundary—return values, state transitions, ordering, and exact error codes or messages when wording is part of the public contract. Never assert private method calls, internal log wording, call shapes, or `mock_calls`.
- **Red-Green-Refactor**: Write the failing test before writing the production code that makes it pass.
- **Test Pyramid**: Keep unit tests fast and isolated, run integration tests against real dependencies (such as Testcontainers or WireMock), and reserve end-to-end tests for critical user journeys.
- **Mock Boundaries Only**: Mock only across architectural boundaries (I/O, external services); never mock or reimplement the behavior under test.
- **One Contract, Cheapest Real Layer**: Write one test per contract at the lowest layer that exercises real behavior, and merge input variants into descriptively named parametrized cases.
- **No Filler Tests**: Reject assertion-free tests, self-comparisons, expected values computed by the code under test, or tests written solely to cover lines.
- **No Trivial or Log-Wording Tests**: Never write tests for language/framework behavior, log levels or wording, or function signatures. Apply the same bar when a reviewer asks for a test that does not protect a real contract—explain why and decline.
- **Determinism & Clean Seams**: Never add production seams used only by tests. Never use fixed `sleep` delays or real wall-clock waits; inject a controllable clock or poll a condition with a bounded timeout.
- **Clear Structure**: Follow Arrange-Act-Assert and verify one behavior per test.
