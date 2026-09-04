# Architecture Documentation, C4 Model & Diagrams

## Invariants
- **Diagrams as Code (Mermaid & PlantUML)**: All architecture diagrams must be written in declarative, version-controlled text (Mermaid inside Markdown).
- **C4 Model Hierarchy**:
  - *Level 1: System Context*: Actors, external systems, and system boundaries.
  - *Level 2: Container Diagram*: Services, web apps, databases, and message brokers.
  - *Level 3: Component Diagram*: Controllers, use cases, and repositories within a service.
  - *Level 4: Code Diagram*: Class diagrams and ER diagrams for domain entities.
- **Sequence Diagrams**: Mandatory for distributed transactions, OAuth flows, and event-driven messaging.
- **Architecture Decision Records (ADR)**: Document significant architectural choices with Title, Status, Context, Decision, and Consequences.
