# Event-Driven Architecture (EDA) & Messaging

## Invariants
- **Transactional Outbox Pattern**: When persisting state changes and publishing events, store events in an outbox table within the same database transaction to prevent message loss or ghost events.
- **Idempotent Consumers**: Design every message handler to be idempotent. Track processed message IDs to handle duplicate deliveries gracefully.
- **Dead Letter Queues (DLQ)**: Route unprocessable/corrupted messages to a dedicated DLQ after configured retries with backoff; never drop messages silently.
- **Schema Evolution**: Maintain backwards compatibility on event schemas (e.g. Avro, JSON Schema, Protobuf). Add optional fields; never remove or rename existing fields.
