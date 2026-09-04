# Concurrency & Distributed Locking

## Invariants
- **Race Condition Prevention**: Ensure thread-safety for all shared resources. Prefer immutable data structures and message passing over shared mutable memory.
- **Optimistic vs Pessimistic Locking**:
  - *Optimistic Locking*: Use version fields (`@Version`, eTags) for high-read/low-contention domain entities.
  - *Pessimistic Locking*: Use `SELECT FOR UPDATE` only for high-contention, critical transactional invariants.
- **Distributed Locking**: Use distributed lock mechanisms (e.g. Redis Redlock) with lease times and automatic renewal for cluster-wide exclusive operations. Always release locks in a `finally` block.
- **Deterministic Caching**: Apply Cache-Aside pattern with mandatory TTL. Never cache unvalidated or sensitive PII.
