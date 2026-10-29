# API Design & REST Contracts

## Invariants
- **Resource Naming**: Plural nouns for collections (`/stores`, `/stores/{id}`), kebab-case, no verbs in paths; match the naming of sibling routes in the same router.
- **HTTP Semantics**: GET (idempotent, no body), POST (resource creation), PUT (complete replacement), PATCH (partial update), DELETE (idempotent removal).
- **Standard Error Payload (RFC 7807)**: Return Problem Details JSON with `type`, `title`, `status`, `detail`, and `instance`.
- **Idempotency Keys**: Require `Idempotency-Key` header for financial transactions and sensitive state mutations.
- **Correlation IDs**: Propagate `X-Request-Id` and `X-Trace-Id` across all responses.
