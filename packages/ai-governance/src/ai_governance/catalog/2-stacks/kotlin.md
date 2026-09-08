# Kotlin & Coroutines Standards

## Invariants
- **Immutability & Data Classes**: Use `data class` with `val` for DTOs and Value Objects. Use `sealed interface` for domain state modeling.
- **Structured Concurrency**: Use Kotlin Coroutines and `Flow`. Never launch work on `GlobalScope`; bind jobs to structured scopes and handle `CancellationException`.
- **Null Safety**: Leverage Kotlin's type system to eliminate nullability. Avoid force unwraps (`!!`).
