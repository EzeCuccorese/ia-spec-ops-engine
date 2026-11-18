# Concurrency & Distributed Locking

## Invariants
- **Race Condition Prevention**: Ensure thread-safety for all shared resources. Prefer immutable data structures and message passing over shared mutable memory.
- **Optimistic vs Pessimistic Locking**:
  - *Optimistic Locking*: Use version fields (`@Version`, eTags) for high-read/low-contention domain entities.
  - *Pessimistic Locking*: Use `SELECT FOR UPDATE` only for high-contention, critical transactional invariants.
- **Distributed Locking**: Use distributed lock mechanisms (e.g. Redis Redlock) with lease times and automatic renewal for cluster-wide exclusive operations, and always release locks in a `finally` block. Note that a time-leased lock does not guarantee full mutual exclusion without fencing tokens or idempotent writes.
- **Quotas**: Reserve quota with an atomic script, refund only within the original rate-limit window so rotated windows are never over-credited, and bound wait times.
- **Deterministic Caching**: Apply Cache-Aside pattern with mandatory TTL. Never cache unvalidated or sensitive PII.
