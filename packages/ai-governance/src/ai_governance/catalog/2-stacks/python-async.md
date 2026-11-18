# Python 3.11+ Standards

## Invariants
- **Strict Type Hints**: Annotate all function and method signatures (`mypy --strict`), parameterize collections (`dict[K, V]`, `list[T]`), and never shadow Python builtins.
- **Avoid `Any`**: Model data with unions, `TypedDict`, `Protocol`, or dataclasses/models. Use `dict[str, Any]` only for raw JSON at the boundary and parse it immediately.
- **Pydantic v2 Validation**: Use frozen models (`ConfigDict(frozen=True)`) for DTOs and settings, and rely on built-in Pydantic types (`EmailStr`, `HttpUrl`, `UUID4`, `PositiveInt`, `Literal`) instead of hand-rolled validation.
- **Strict Integer Checks**: In Python, `bool` is a subclass of `int` (`isinstance(True, int)` is `True`), so check `type(x) is int` (or explicitly reject `bool`) whenever strict integers are required.
- **Explicit Error Handling**: Catch specific exception classes; never use bare `except:` or silent `except Exception: pass`.
- **Structured Logging**: Use the `logging` module with lazy `%s` formatting instead of `print` or eager f-strings.
- **Async Safety**: Never block the `asyncio` event loop with synchronous I/O or CPU work; offload blocking calls via `asyncio.to_thread`.
- **ASGI Middleware Order**: In Starlette and FastAPI, `add_middleware` wraps in reverse registration order—the last middleware added runs outermost on incoming requests.
- **Package & Class Structure**: Keep `__init__.py` limited to package exports and imports, and declare instance attributes in `__init__` rather than mutating `__dict__`.
- **Testing**: Write hermetic `pytest` tests using typed fixtures.
