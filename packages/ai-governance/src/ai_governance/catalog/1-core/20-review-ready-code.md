# Review-Ready Code

## Invariants

### Types and literals
- **Required values**: Make a field or parameter optional only when a supported caller can omit it.
- **Response shape**: Validate upstream response shapes before indexing or mapping them.
- **Finite ranges**: Reject non-finite numbers before applying numeric range checks.
- **Explicit operations**: Use explicit operations instead of sentinel values that change an API's meaning.
- **REST routes**: Use plural nouns for resource paths.

### Errors and timeouts
- **Failure policy**: Handle timeouts and connection failures alongside status errors; degrade optional reads without breaking the main operation and fail guards closed.
- **Unread data**: Distinguish unavailable data from a successful empty result in the caller-visible outcome.
- **Domain errors**: Translate library failures into the module's domain error contract while preserving the cause and relevant status.
- **Partial writes**: Report which steps were saved and which failed when a multi-step write stops partway through.

### Logging and secrets
- **Telemetry payloads**: Exclude request bodies and sensitive values from trace spans as well as logs, including nested fields; apply `06-security-privacy`.
- **Bounded matching**: Avoid overlapping alternatives and nested repetition in regular expressions over untrusted input.

### Tests
- **Failure identity**: Assert the contractual error code or stable diagnostic that distinguishes the intended failure path, not only its exception type; apply `04-testing-patterns`.
- **Case names**: Give each parametrized test case an explicit, stable, descriptive identifier.

### Reuse and duplication
- **Existing contracts**: Apply `12-boundaries-and-reuse` for types, validation and helpers, `11-self-documenting-code` for shared literals and rationale, and `09-concurrency-locking` for coordinated writes and credential refreshes.
- **Necessary reads**: Fetch only data the selected code path consumes.

### PR hygiene
- **Temporary code**: Remove temporary overrides, development-only endpoints and debug panels before requesting review.
- **Documentation parity**: Update affected documentation, docstrings and examples with the code in the same PR.
- **Environment coverage**: Supply configuration for each targeted environment and state explicitly when production remains disabled.
- **Environment values**: Keep values that vary by environment in environment configuration, not in code.
- **New file types**: Explain in the PR description why the change introduces a file type the repository does not yet use.
- **Existing review rules**: Apply `17-quality-gate`, `18-surgical-changes` and `19-pull-requests` for checks, scope, ownership and review readiness.
