# Self-Documenting Code

## Invariants
- **Intention-Revealing Names**: Choose descriptive names in the domain's language with one consistent term per concept. Avoid cryptic abbreviations, type prefixes, and filler words such as `data`, `info`, `manager`, `helper`, or `utils`.
- **Naming Grammar**: Use verbs for functions (`calculateTotal`), nouns for types and values (`Invoice`), and `is`/`has`/`can` prefixes for booleans (`isEligible`).
- **Cohesive, Flat Functions**: Keep each function focused on one task at a single level of abstraction so it reads top-down like prose; prefer guard clauses and early returns over deep nesting.
- **Command-Query Separation**: A function should either mutate state or return a value, never both. Never mutate input arguments or use output parameters.
- **Clean Parameter Lists**: Split boolean flag parameters (such as `render(isPreview)`) into two separate functions (`renderPreview()`, `renderFinal()`), and group related parameters into a cohesive parameter object.
- **No Magic Values**: Replace unexplained numeric literals and status strings with named constants or enums (e.g., `MAX_RETRY_ATTEMPTS`, `OrderStatus.PAID`).
- **Explain Why, Not What**: Write comments only to document non-obvious rationale, trade-offs, invariants, or ticket links. If code needs a comment to explain what it does, rename symbols or extract a function instead.
- **Focused Docstrings**: Document public entry points with their contract, preconditions, and edge cases; omit redundant docstrings on trivial private helpers.
- **Zero Dead Code**: Delete unused variables, unreachable branches, commented-out code, and inline changelog comments; never leave a `TODO` without a linked ticket.
- **Structural Design Limits**: `ws design` enforces complexity, length, argument, and nesting limits—refactor the design to meet them rather than suppressing checks.
