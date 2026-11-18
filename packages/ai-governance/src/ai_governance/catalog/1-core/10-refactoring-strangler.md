# Refactoring & Legacy Modernization

## Invariants
- **Scoped Boy Scout Rule**: Clean up only the lines and functions already touched by the current task. Leave unrelated functions and modules untouched, and propose wider refactors separately in their own PR.
- **Strangler Fig Pattern**: Incrementally intercept and replace legacy endpoints or services with new modular implementations rather than attempting risky Big Bang rewrites.
- **Anti-Corruption Layer (ACL)**: Isolate new domain models from legacy data structures by translating through an explicit adapter layer so legacy quirks do not leak into the domain.
- **Safety Nets**: Establish behavioral test coverage around the legacy seam before refactoring its implementation.
