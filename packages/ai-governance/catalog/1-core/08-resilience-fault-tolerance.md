# Resilience & Fault Tolerance Patterns

## Invariants
- **Timeouts on All I/O**: Every remote network call (HTTP, gRPC, DB) must specify an explicit, bounded timeout.
- **Circuit Breaker**: Wrap calls to external services with circuit breakers to prevent cascading failures when dependencies degrade.
- **Exponential Backoff with Jitter**: Implement retries only on transient errors (503, connection timeouts), always using exponential backoff randomized with jitter to prevent thundering herd problems.
- **Bulkhead Isolation**: Isolate thread pools and connection pools for critical vs non-critical dependencies to prevent resource exhaustion.
- **Graceful Degradation / Fallbacks**: Provide predictable fallback responses or cached data when downstream services fail.
