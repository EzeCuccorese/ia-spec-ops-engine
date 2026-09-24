# Java 21+ & Spring Boot Standards

## Invariants
- **Constructor Injection**: Inject dependencies exclusively via constructor injection with `final` fields. Prohibit `@Autowired` on private fields.
- **Records**: Use Java `record` for DTOs, value objects, and domain events. Record header components are implicitly final; NEVER write `final` inside the header (e.g. `public record Foo(UUID id, String name)`, never `record Foo(final UUID id)`).
- **Structured Logging**: Use SLF4J (`LoggerFactory.getLogger`) with parameterized placeholders `{}`. Never use `System.out` or `printStackTrace()`.
- **Exception Handling**: Handle exceptions centrally with `@RestControllerAdvice` and RFC 7807 Problem Details.
- **Testing**: JUnit 5 + AssertJ + Testcontainers for integration/DB tests.
