# Task: order confirmation notifier with logging and error handling

Add an order notifier to the `shop` package (`src/shop/`). Create a new module
`src/shop/notifier.py` that sends a confirmation message for a placed order
through a pluggable sender (no real network calls — accept a `sender` object
injected in `__init__`, so tests can use a fake). Use only the stdlib
(`logging`, `dataclasses`); no new dependencies.

Requirements:

- `notify(order_id: str) -> Notification` loads the order from the
  `OrderRepository`, builds a `Notification` and calls
  `sender.send(notification)`.
- The message body is `"Order <order_id>: <n> item(s), total <amount>"`, where
  `<n>` is the sum of the line quantities and `<amount>` is the subtotal in
  units with two decimals (`1500` cents -> `15.00`).
- An unknown order id lets the repository's `NotFoundError` reach the caller;
  the sender is not called.
- An order without items raises `EmptyOrderError`; the sender is not called.
- If `sender.send` raises `SenderError`, the notifier logs the failure, and
  raises `NotificationFailed` (with the original error as its cause). Any other
  exception from the sender is not caught.
- Log one line when a notification is sent and one when it fails, with the
  `logging` module (logger name `shop.notifier`).

Add unit tests in `tests/`.

## Public API (required — hidden acceptance tests import these exact names)

In `src/shop/notifier.py`:

```python
from dataclasses import dataclass

from shop.repository import OrderRepository


class SenderError(Exception):
    pass


class EmptyOrderError(Exception):
    pass


class NotificationFailed(Exception):
    pass


@dataclass(frozen=True)
class Notification:
    order_id: str
    customer_id: str
    body: str


class OrderNotifier:
    def __init__(self, orders: OrderRepository, sender) -> None: ...

    def notify(self, order_id: str) -> Notification:
        """Builds the notification, calls `self.sender.send(notification)` once
        and returns it."""
```
