# TypeScript & Node.js Standards

## Invariants
- **Strict Mode**: Enable strict mode (`strict: true`) in `tsconfig.json`. Prohibit `any`; use `unknown` with type guards.
- **Border Validation with Zod**: Parse and validate all incoming HTTP requests, query params, and environment variables with Zod schemas.
- **Branded Types**: Use branded nominal types for domain identifiers (e.g. `type UserId = string & { readonly __brand: unique symbol }`).
- **Async & Errors**: Use async/await deterministically with `Promise.allSettled` for concurrent batches. Prefer Result type unions over throwing unhandled errors.
