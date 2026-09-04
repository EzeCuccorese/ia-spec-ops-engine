# Clean & Hexagonal Architecture (Ports and Adapters)

## Layer Invariants & Dependency Rule
- **The Dependency Rule**: Source code dependencies must strictly point inwards towards the Domain. Outer layers know about inner layers; inner layers know nothing about outer layers.
- **Layer Breakdown**:
  1. **Domain**: Entities, Value Objects, Domain Events, Domain Services. Zero framework/library dependencies.
  2. **Application**: Use Cases, Command/Query Handlers (CQRS), Input/Output Ports (interfaces).
  3. **Infrastructure / Adapters**:
     - *Inbound (Driving)*: HTTP Controllers, CLI, Event Subscribers.
     - *Outbound (Driven)*: Database Repositories, HTTP Clients, Message Publishers.

## Execution Rules
- **Cross-Boundary DTOs**: Never expose internal domain entities across architectural boundaries. Transform entities to dedicated DTOs or ViewModels at the boundary.
- **Inversion of Control**: Domain/Application defines interfaces (Ports); Infrastructure implements them (Adapters).
