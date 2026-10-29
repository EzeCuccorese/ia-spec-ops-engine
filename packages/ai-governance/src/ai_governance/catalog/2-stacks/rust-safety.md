# Rust & Safety Standards

## Invariants
- **Algebraic Data Types**: Model domain states exhaustively with `enum` to make invalid states unrepresentable.
- **Error Handling**: Use the `?` operator with `Result<T, E>` and `Option<T>`. Prohibit `unwrap()` and `expect()` in production code.
- **Trait Boundaries**: Define architectural boundaries and repository ports via Traits.
- **Ownership & Borrowing**: Minimize heap allocations; borrow with `&str` / `&[T]` instead of cloning owned types unless required.
- **Parse, Don't Validate**: Turn input into typed values at the boundary (`url::Url`, `uuid::Uuid`, newtypes with `TryFrom`, `#[validate(email, url)]` from `validator`); no hand-rolled regex.
- **No Escape Hatches**: No `serde_json::Value` or `Box<dyn Any>` for known shapes; derive `Deserialize` on typed structs.
