# C# & .NET 8/9 Standards

## Invariants
- **Modern C# Idioms**: Use Primary Constructors, `record` and `readonly record struct` for DTOs and value objects. Enable nullable reference types (`<Nullable>enable</Nullable>`).
- **Dependency Injection**: Register dependencies explicitly (`AddScoped`, `AddSingleton`, `AddTransient`). Prohibit Service Locator anti-pattern.
- **Minimal APIs & EF Core**:
  - Validate endpoints using `FluentValidation`.
  - Use `AsNoTracking()` for read-only Entity Framework queries to optimize memory.
  - Eager load with `Include()` to prevent N+1 queries.
- **Async/Await**: Always pass `CancellationToken` to async methods. Do not use `.Result` or `.Wait()` to avoid deadlocks.
- **Boundary Validation**: FluentValidation (`.EmailAddress()`) or DataAnnotations (`[EmailAddress]`, `[Url]`), `Uri`/`Guid` types; no hand-written regex.
- **No Escape Hatches**: No `object` or `dynamic` in signatures or DTOs; deserialize into typed records.
