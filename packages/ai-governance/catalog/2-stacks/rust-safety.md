# Rust & Safety Standards

## Invariants
- **Algebraic Data Types**: Model domain states exhaustively with `enum` to make invalid states unrepresentable.
- **Error Handling**: Use the `?` operator with `Result<T, E>` and `Option<T>`. Prohibit `unwrap()` and `expect()` in production code.
- **Trait Boundaries**: Define architectural boundaries and repository ports via Traits.
- **Ownership & Borrowing**: Minimize heap allocations; borrow with `&str` / `&[T]` instead of cloning owned types unless required.
