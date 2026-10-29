# TypeScript & Node.js Standards

## Invariants
- **Strict Mode**: Enable strict mode (`strict: true`) in `tsconfig.json`. Prohibit `any`, `as` casts on external data and `@ts-ignore`; use `unknown` with type guards or a schema parse.
- **Border Validation with Zod**: Parse and validate all incoming HTTP requests, query params, and environment variables with Zod schemas, using its built-in formats (`z.email()`, `z.url()`, `z.uuid()`; `z.string().email()` in Zod 3) instead of hand-written regex. Derive types with `z.infer`.
- **Branded Types**: Use branded nominal types for domain identifiers (e.g. `type UserId = string & { readonly __brand: unique symbol }`).
- **Async & Errors**: Use async/await deterministically with `Promise.allSettled` for concurrent batches. Prefer Result type unions over throwing unhandled errors.
