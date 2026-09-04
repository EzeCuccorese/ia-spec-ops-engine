# Python 3.11+ & Async Standards

## Invariants
- **Type Annotations**: Provide explicit type hints on all function signatures; validate with `mypy --strict`.
- **Pydantic v2**: Use immutable Pydantic models (`model_config = ConfigDict(frozen=True)`) for DTOs and config settings.
- **Async Safety**: Never perform blocking I/O calls directly inside the asyncio event loop; offload via `asyncio.to_thread`.
- **Testing**: Write hermetic tests with `pytest` and typed fixtures.
