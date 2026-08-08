# Observability — Logging, Tracing, and Metrics

## Structured Logging

### Log Levels

| Level | When to Use |
|---|---|
| `ERROR` | Unrecoverable exceptions, data loss risks, critical business failure |
| `WARN` | Unexpected but recoverable conditions; service degradation events |
| `INFO` | Endpoint requests/responses, start/completion of key business workflows, state transitions |
| `DEBUG` | Intermediate values, external request/response payloads (development environment only) |
| `TRACE` | Highly granular debugging; never enabled in production environments |

### MDC Fields (Mapped Diagnostic Context)

Propagate contextual log metadata whenever available:

- `requestId` — End-to-end HTTP request correlation ID
- `traceId` — Distributed cross-service trace identifier (OpenTelemetry)
- `spanId` — Active span execution identifier

Add domain entity identifiers when applicable (excluding personal data — IDs only): `orderId`, `transactionId`, `partnerId`, `userId`.

### Prohibited Log Contents (Never Log)

- Personally Identifiable Information (PII): Full names, national identification numbers, email addresses, phone numbers
- Financial Data: Bank account numbers, credit/debit card numbers, CVV codes, PIN numbers
- Security Credentials: Plaintext passwords, authentication tokens, API keys, full JWT tokens

---

## Correlation Headers

Propagate cross-service correlation headers in outbound HTTP requests: `X-Request-Id` and `X-Trace-Id` (OpenTelemetry).
