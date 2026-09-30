# Self-Documenting Code

- Names reveal intent: no abbreviations, type prefixes or filler words (`data`, `manager`, `helper`, `utils`).
- Verbs for functions, nouns for types and values, `is/has/can` for booleans; one word per concept, in the domain's language.
- A function does one thing at one level of abstraction and reads top-down; return early instead of nesting.
- A function either changes state or returns data, never both; no argument mutation or output parameters.
- Split boolean flag parameters into two functions; group related parameters into an object.
- Named constants or enums instead of magic numbers and strings.
- Comments explain why (rationale, trade-offs, tickets), never what: rename or extract instead.
- Docstrings only on public entry points: the contract and edge cases.
- No commented-out code, changelog comments or `TODO` without a ticket; delete dead code.
- `ws design` enforces complexity, length, argument and nesting limits: fix the design, never suppress it.
