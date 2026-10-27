# Python 3.11+ Standards

## Invariants
- **Type Annotations**: Provide explicit type hints on all function signatures; validate with `mypy --strict`.
- **No `Any`**: Type real shapes with unions (`str | dict[str, str] | None`), `TypedDict`, `Protocol` or a model. `dict[str, Any]` only for raw JSON at the edge, parsed into a model right away.
- **Pydantic v2**: Use immutable Pydantic models (`model_config = ConfigDict(frozen=True)`) for DTOs and config settings.
- **Pydantic Types, Not Regex**: Type fields and tool/endpoint params with Pydantic types (`EmailStr`, `HttpUrl`, `UUID4`, `PositiveInt`, `Literal[...]`) and let Pydantic reject bad input; no hand-made validation in services.
- **Errors**: Catch specific exceptions, never bare `except:`; `logging` with lazy `%s` args, never `print`.
- **Async Safety**: Never perform blocking I/O calls directly inside the asyncio event loop; offload via `asyncio.to_thread`.
- **Testing**: Write hermetic tests with `pytest` and typed fixtures.
