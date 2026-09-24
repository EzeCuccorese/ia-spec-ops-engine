# Domain-Driven Design (DDD)

- Class, method, and variable names must match the business domain glossary, not database jargon.
- Entities: unique identity and lifecycle. Value Objects: immutable, self-validating, no identity.
- The Aggregate Root is the sole entry point for state mutation within its boundary.
- Reference other aggregates only by ID, never by direct object reference.
- Enforce business invariants atomically inside the aggregate root that owns them.
- Reject anemic data bags with bare getters/setters; domain models encapsulate behavior and validation.
- Emit domain events on significant state changes to decouple side effects.
