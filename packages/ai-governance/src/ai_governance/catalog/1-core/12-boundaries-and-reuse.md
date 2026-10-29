# Typed Boundaries & Reuse

- Validate at the boundary with the stack's validation library and its built-in types (email, URL, UUID, dates, enums); never hand-roll a regex the library already covers.
- No escape-hatch types (`Any`, `any`, `Object`, `mixed`, `dynamic`, `interface{}`) in signatures or DTOs: model the real shape with unions, generics or a dedicated type.
- No pass-through functions: a function that only forwards one call or writes one log line is inlined, unless its name adds a domain concept.
- Reuse the module's existing helpers (HTTP client wrapper, error parsing, formatting) before writing new ones; a deliberate deviation carries a one-line comment with the reason.
