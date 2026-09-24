# Clean Code & SOLID Principles

- Split a class/function the moment it takes on a second reason to change; avoid God objects.
- Extend via composition/strategy; never add `if/else`/`switch` cascades on type to alter tested behavior.
- Subtypes must be fully substitutable for their base type without changing contract semantics.
- Keep interfaces to 1-3 cohesive methods; split by client, not one general-purpose interface.
- High-level modules depend on abstractions only, never concrete infrastructure classes.
- Variables, parameters, DTOs, and collections are immutable by default; no hidden side effects.
- Isolate pure business calculations from I/O.
- Wrap primitives in Value Objects (`Money`, `Email`, `UserId`) instead of bare strings/numbers.
- Use Result/Option types or domain exceptions; never leave an empty catch block.
