# Java 21+ & Spring Boot Standards

## Invariants
- **Constructor Injection**: Inject dependencies exclusively via constructor injection with `final` fields. Prohibit `@Autowired` on private fields.
- **Records**: Use Java `record` for DTOs, value objects, and domain events. Record header components are implicitly final; NEVER write `final` inside the header (`record Foo(UUID id)`, never `record Foo(final UUID id)`).
- **Structured Logging**: SLF4J with `{}` placeholders; never `System.out` or `printStackTrace()`.
- **Exception Handling**: Handle exceptions centrally with `@RestControllerAdvice` and RFC 7807 Problem Details.
- **Testing**: JUnit 5 + AssertJ + Testcontainers.
- **Bean Validation**: Jakarta Validation on DTOs (`@Email`, `@NotBlank`, Hibernate `@URL`) triggered with `@Valid`; `@Pattern` only when no annotation fits. `URI`/`UUID`, not `String`.
- **No Escape Hatches**: No raw generic types, `Object` parameters or `Map<String, Object>` DTOs; model payloads as records.
