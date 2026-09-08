# Idiomatic Go Standards

## Invariants
- **Consumer-Defined Interfaces**: Define small interfaces (1–3 methods) where they are consumed, not where implemented.
- **Explicit Error Handling**: Return `(result, error)`. Wrap errors with context using `fmt.Errorf("...: %w", err)`. Inspect with `errors.Is` and `errors.As`.
- **Context Propagation**: The first parameter of every I/O-bound function must be `ctx context.Context`.
- **Goroutine Lifecycle**: Always ensure goroutines have a deterministic termination path via `context` or channels. Use `sync.WaitGroup` or `errgroup`.
