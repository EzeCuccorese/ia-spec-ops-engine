# Task: payment client with retries, backoff, timeouts, error mapping

Add a payment client to the `shop` package (`src/shop/`). Create a new module
(e.g. `src/shop/payment.py`) with a `PaymentClient` class that charges an
order total through a pluggable transport (do not use real network calls —
accept a `transport` callable/object injected in `__init__`, so tests can use
a fake). Use only the stdlib (e.g. `time`, `dataclasses`); no new
dependencies.

Requirements:

- `charge(order_id: str, amount_cents: int, idempotency_key: str) ->
  PaymentResult` calls `transport.send(order_id, amount_cents,
  idempotency_key)`, which raises one of: `TransportTimeout`,
  `TransportConnectionError`, `TransportHTTPError(status_code, body)`, or
  returns a success payload `{"status": "ok", "charge_id": ...}`.
- **Timeouts**: the client enforces an overall timeout budget (parameter,
  default 10s) across all attempts, tracked via an injectable clock function
  (default `time.monotonic`) so tests don't sleep in real time.
- **Retries with backoff**: retry on `TransportTimeout` and
  `TransportConnectionError`, and on `TransportHTTPError` with status codes
  in `{429, 500, 502, 503, 504}`. Up to 3 attempts total. Backoff is
  exponential (base 0.1s, factor 2) with a sleep function injected (default
  `time.sleep`) so tests don't sleep in real time. Do not retry on other
  HTTP status codes (e.g. 400, 401, 402, 422) — map those to a permanent
  failure immediately.
- **Error mapping**: map transport errors to a `PaymentResult` (success=False)
  with a stable `error_code` field: `"timeout"`, `"network_error"`,
  `"declined"` (402), `"invalid_request"` (400/422), `"unauthorized"` (401),
  `"server_error"` (after retries exhausted on 5xx/429), or `"unknown_error"`
  for any other status code.
- On success, return `PaymentResult(success=True, charge_id=..., attempts=N)`.

Add unit tests in `tests/` with a fake transport covering: immediate success,
success after two retries, permanent decline (no retry), and exhausted
retries on repeated 503s.

## Public API (required — hidden acceptance tests import these exact names)

In `src/shop/payment.py`:

```python
import time
from dataclasses import dataclass


class TransportTimeout(Exception):
    pass


class TransportConnectionError(Exception):
    pass


class TransportHTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


@dataclass
class PaymentResult:
    success: bool
    charge_id: str | None = None
    attempts: int = 0
    error_code: str | None = None
    # error_code in {"timeout", "network_error", "declined", "invalid_request",
    # "unauthorized", "server_error", "unknown_error"} when success is False


class PaymentClient:
    def __init__(
        self,
        transport,
        max_attempts: int = 3,
        timeout_budget_s: float = 10.0,
        base_backoff_s: float = 0.1,
        backoff_factor: float = 2.0,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None: ...

    def charge(
        self, order_id: str, amount_cents: int, idempotency_key: str
    ) -> PaymentResult:
        """Calls `self.transport.send(order_id, amount_cents,
        idempotency_key)`, retrying per the rules above, using
        `self.sleep(seconds)` for backoff and `self.clock()` to track the
        timeout budget. `attempts` on the returned PaymentResult is the
        number of times `transport.send` was called."""
```

`transport.send(order_id, amount_cents, idempotency_key)` either returns a
success payload (`{"status": "ok", "charge_id": ...}`) or raises one of
`TransportTimeout`, `TransportConnectionError`, `TransportHTTPError`.
