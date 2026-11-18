# Clean Code & Design Principles

## Invariants
- **Single Responsibility (SRP)**: Give each module, class, and function one clear reason to change; split God objects as soon as responsibilities diverge.
- **Composition over Inheritance (OCP)**: Extend behavior through composition or strategy objects rather than adding `if/else` or `switch` chains on type; keep inheritance depth at 2 or less.
- **Substitutability & Small Interfaces (LSP & ISP)**: Ensure subtypes honor the base contract without surprises, and split broad interfaces into small, client-specific ones.
- **Dependency Inversion (DIP)**: Depend on abstractions (interfaces or ports) in high-level domain logic, never directly on concrete infrastructure classes.
- **DRY (Rule of Three)**: Maintain a single source of truth for each business fact. Extract shared abstractions on the third repetition, and never merge look-alike code that changes for different reasons.
- **KISS & YAGNI**: Build the simplest design that meets today's requirement; avoid speculative parameters, extra layers, or premature extension points.
- **Law of Demeter**: Talk only to direct collaborators; replace navigation chains like `order.customer().address().city()` with a single intention-revealing method.
- **Least Astonishment**: Make each function do strictly what its name promises, with no hidden side effects or surprising default arguments.
- **Immutability & Pure Logic**: Keep variables, DTOs, and collections immutable by default, and isolate pure business calculations from I/O.
- **Value Objects**: Encapsulate domain concepts in self-validating Value Objects (`Money`, `Email`, `UserId`) instead of passing raw strings or numbers.
- **Explicit Absence & Errors**: Represent missing values with `Option`/`Result` types or empty collections rather than `null`, and never swallow exceptions in empty catch blocks.
