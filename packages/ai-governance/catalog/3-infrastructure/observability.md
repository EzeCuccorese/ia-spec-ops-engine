# Observability & OpenTelemetry

## Invariants
- **Structured JSON Logging**: Emit logs as parseable JSON objects with `timestamp`, `level`, `message`, `trace_id`, `span_id`, and `service`.
- **Context & MDC**: Inject correlation IDs into MDC logger context at request entry.
- **RED Metrics**: Expose Rate, Error, and Duration metrics for all entrypoints.
- **OpenTelemetry Tracing**: Propagate trace contexts across distributed HTTP/message boundaries.
