# Clean Code & SOLID Principles

## Core Invariants
- **Single Responsibility (SRP)**: Each module, class, or function must have exactly one reason to change. Avoid God objects.
- **Open/Closed (OCP)**: Extend behavior via polymorphism, strategy patterns, or composition. Never mutate tested classes with cascade `if/else` or `switch` statements.
- **Liskov Substitution (LSP)**: Subtypes and implementations must be fully substitutable for their base abstractions without altering contract semantics.
- **Interface Segregation (ISP)**: Prefer many client-specific interfaces over one general-purpose interface. Keep interfaces to 1–3 cohesive methods.
- **Dependency Inversion (DIP)**: High-level modules must depend on abstractions (interfaces/traits), never on concrete infrastructure details.

## Code Standards
- **Immutability by Default**: Declare variables, parameters, DTOs, and collections as immutable. Avoid hidden side effects and shared mutable state.
- **Pure Functions**: Isolate business calculations from I/O and side effects.
- **Primitive Obsession**: Encapsulate domain concepts in rich Value Objects (e.g., `Money`, `Email`, `UserId`) rather than bare primitives.
- **Error Handling**: Use explicit Result/Option types or domain exceptions. Never swallow exceptions in empty catch blocks.
