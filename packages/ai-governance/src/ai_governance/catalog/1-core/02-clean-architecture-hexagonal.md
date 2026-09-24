# Clean & Hexagonal Architecture (Ports and Adapters)

- Dependencies point strictly inward to the Domain; outer layers may know inner layers, never the reverse.
- Domain layer (entities, value objects, domain events/services) has zero framework/library dependencies.
- Application layer holds use cases and CQRS handlers behind Input/Output Ports (interfaces).
- Infrastructure implements Ports as Adapters: inbound (controllers, CLI, subscribers) and outbound (repositories, HTTP clients, publishers).
- Never expose internal domain entities across a boundary; transform to dedicated DTOs/ViewModels at the edge.
- Domain/Application define interfaces; Infrastructure implements them, never the inverse.
