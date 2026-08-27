# Domain-Driven Design (DDD)

## Tactical Design Invariants
- **Ubiquitous Language**: Class, method, and variable names must exactly match the business domain glossary, not technical database jargon.
- **Entities vs Value Objects**:
  - *Entities*: Defined by unique identity, lifecycle, and business state transitions.
  - *Value Objects*: Immutable, defined entirely by their attributes, self-validating, without identity.
- **Aggregates & Consistency Boundaries**:
  - The Aggregate Root is the sole entry point for state mutation.
  - Reference other aggregates only by identity (ID), not by direct object references.
  - Enforce business invariants atomically inside the aggregate root.
- **Rich vs Anemic Domain**: Domain models must encapsulate business behavior and validation. Reject anemic data bags with bare getters/setters.
- **Domain Events**: Emit domain events on significant state changes to decouple side effects.
