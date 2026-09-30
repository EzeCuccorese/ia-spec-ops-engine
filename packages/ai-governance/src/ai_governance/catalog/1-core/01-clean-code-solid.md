# Clean Code & Design Principles

- One reason to change per class/function; split God objects.
- Extend via composition/strategy, not `if/else`/`switch` on type; inheritance depth ≤ 2.
- Subtypes honor the base contract; interfaces are small and client-specific.
- High-level code depends on abstractions, not concrete infrastructure.
- DRY: one source of truth per fact; extract on the third repetition; never merge look-alike code that changes for different reasons.
- KISS/YAGNI: simplest design that meets today's requirement; no speculative parameters, layers or extension points.
- Law of Demeter: talk to direct collaborators; replace `a.b().c()` chains with an intention-revealing method.
- A function does what its name promises: no hidden side effects or surprising defaults.
- Immutable by default; keep pure calculations apart from I/O.
- Value Objects (`Money`, `Email`) over primitives.
- Signal absence with Option/Result or empty collections, not `null`; never swallow exceptions.
