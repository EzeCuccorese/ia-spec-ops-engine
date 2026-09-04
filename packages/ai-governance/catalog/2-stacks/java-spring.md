# Java 21+ & Spring Boot Standards

## Invariants
- **Constructor Injection**: Inject dependencies exclusively via constructor injection with `final` fields. Prohibit `@Autowired` on private fields.
- **Immutability & Records**: Use Java `record` for all DTOs, value objects, and domain events. Declare local variables, method parameters, and loop variables as `final` (do not use `var`). CRITICAL: Record header components are implicitly final; NEVER put the `final` keyword inside record declarations (e.g., write `public record Foo(UUID id, String name)`, NEVER `record Foo(final UUID id)`).
- **Structured Logging**: Use SLF4J (`LoggerFactory.getLogger`) with parameterized placeholders `{}`. Never use `System.out` or `printStackTrace()`.
- **Exception Handling**: Handle exceptions centrally with `@RestControllerAdvice` and RFC 7807 Problem Details. No empty catch blocks.
- **Testing**: Use JUnit 5, AssertJ, and Testcontainers. Maintain $\ge 85\%$ JaCoCo coverage on business services.
