# Coding Practices — Java, Node.js, Python, React, and Testing

## General Principles

- **Code, Names, and Logs**: Always in **English**. Documentation (`.md`, plans) and communication: according to team standards (default English).
- **Core Principles**: SOLID, DRY, DDD, KISS. Single responsibility per method; if a method exceeds ~20 lines, consider extracting.
- **Scope**: Modify only what is strictly necessary for the task; do not refactor or add unrequested features.
- **Style Guidelines**: Google Java Style / Airbnb JavaScript depending on the technology stack.

---

## Java and Spring Boot

- **Dependency Injection**: Use constructor injection; avoid direct `@Autowired` on fields.
- **Null Safety**: Use `Optional<T>` for return types; never return `null` for collections (return empty collections).
- **Immutability**: Use `final` wherever applicable; use Java Records for DTOs.
- **Local Variables**: Always use explicit types (**do not use `var`**), and mark local variables, parameters, and for-each loops as `final`.
- **Streams**: Prefer functional stream APIs for collection manipulation.
- **Exceptions**: Use domain/context-specific exceptions; avoid generic `RuntimeException` in application layers. Avoid catching raw `Exception`; map to custom domain exceptions.
- **Modern Spring Boot**: Enable Virtual Threads (`spring.threads.virtual.enabled=true`) for high I/O concurrency services.

```java
// BAD
@Autowired
private MyService service;
return list != null ? list : null;
var result = repository.findAll();

// GOOD
private final MyService service;
public MyController(final MyService service) { this.service = service; }
return Optional.ofNullable(list).orElse(List.of());
final List<Order> result = repository.findAll();
```

---

## Logging and Error Handling

- **Logging**: SLF4J with Lombok `@Slf4j`. Never use `System.out`/`System.err`/`printStackTrace()` in production. Use `{}` placeholders in log messages.
- **Configuration**: Set package levels and log patterns in `application.yml`. Log entry/exit points and error conditions appropriately (DEBUG/INFO/WARN/ERROR depending on context).
- **Error Handling**: Implement a central `@ControllerAdvice`/`@RestControllerAdvice` per service; maintain consistent error response structures (code, message, details). Never leave empty `catch` blocks: log and/or rethrow or translate to a domain exception.

---

## Testing

- **TDD**: Preferred approach; write unit/integration tests before writing implementation code whenever possible.
- **Coverage**: Prioritize meaningful coverage over critical execution paths. Minimum 85% JaCoCo coverage overall; **when modifying any non-POJO class, achieve or maintain ≥90% coverage**.
- **Integration**: Write at least one end-to-end integration test per feature validating the full workflow.
- **WireMock**: Mock external HTTP endpoints in integration tests.
- **Testcontainers**: Use real containerized databases and external dependencies during integration testing (never mock database drivers in tests affecting production environments).
- **AAA Pattern**: Arrange–Act–Assert structure; extract helper methods for complex setups if readability improves.
- **@DisplayName**: Clearly describe the scenario and expected outcome.

---

## Node.js and TypeScript

- **Asynchronous Operations**: Use `async/await` exclusively; handle promise rejections explicitly.
- **Layered Architecture**: Controllers (HTTP), Services (business logic), Models/Repositories (data persistence).
- **Modules**: Use standard ESModules (`import`/`export`), avoid CommonJS (`require`).
- **Validation**: Use schema libraries (e.g., Zod) for HTTP request payloads and environment variables.
- **Logging**: Use structured loggers (Pino, Winston); do not use `console.log` in production.
- **Error Handling**: Centralized error management; consistent error formats; do not leak internal details in production.

---

## Python and FastAPI

- **File Size Limits**: Router files, service logic, and processing scripts must not exceed **200 lines**. Extract logic into dedicated submodules or domain classes.
- **Single Responsibility Principle (SRP)**:
  - **Controllers (Routers)**: Focus strictly on receiving HTTP requests, validating request schemas, delegating to services, and returning JSON responses.
  - **Services**: Encapsulate all business logic, report generation, and third-party integrations.
  - **Models**: Validation schemas and database models organized by business domain.
- **Type Annotations**: Always use explicit static typing (Type Hints).
- **Testing**: Use `pytest` for unit and integration testing.

---

## React and TypeScript/JSX

- **Component Size Limits**: React components must not exceed **250 lines**.
- **Separation of Logic and UI**: Presentational components must remain clean UI layers.
- **Mandatory Custom Hooks**: All procedural logic, state handling, and network requests must reside in dedicated Custom Hooks (`/hooks/`).

---

## Software Engineering and Architectural Principles

- **Fail-Fast**: Validate mandatory environment variables and database connections at system startup.
- **Idempotency**: Design critical mutation endpoints using header idempotency keys (`Idempotency-Key`).
- **Fault Tolerance**: Implement resilience patterns (Circuit Breakers, fallbacks) with external APIs.
- **Backward Compatibility**: Maintain backward compatibility across public API contracts and database schemas.
