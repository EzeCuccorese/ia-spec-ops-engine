# Python 3.11+ Standards

## Invariants
- **Types**: Explicit hints on all signatures (`mypy --strict`); parameterize `dict[K, V]`/`list[T]`; never shadow builtins.
- **No `Any`**: Use unions, `TypedDict`, `Protocol` or models; `dict[str, Any]` only for raw JSON at the edge, parsed immediately.
- **Pydantic v2**: Frozen models (`ConfigDict(frozen=True)`) for DTOs/settings; use Pydantic types (`EmailStr`, `HttpUrl`, `UUID4`, `PositiveInt`, `Literal`) instead of hand-made validation.
- **Errors & Async**: Catch specific exceptions (never bare `except:`); `logging` with lazy `%s` (never `print`); offload blocking I/O in `asyncio` via `asyncio.to_thread`.
- **Structure**: Inline 1-line forwarding wrappers unless adding behavior/domain meaning; keep `__init__.py` to imports; set attributes in `__init__`, never via `__dict__`.
- **Testing**: Hermetic `pytest` tests with typed fixtures.
