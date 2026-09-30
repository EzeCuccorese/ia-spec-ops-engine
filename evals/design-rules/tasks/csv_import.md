# Task: CSV order import with validation and error report

Add CSV order import to the `shop` package (`src/shop/`). Create a new module
(e.g. `src/shop/csv_import.py`) with a function
`import_orders_csv(path, products, customers, orders) -> ImportReport` that
reads a CSV file of orders and loads valid ones into the given repositories
(`ProductRepository`, `CustomerRepository`, `OrderRepository` from
`shop.repository`).

CSV columns: `order_id,customer_id,sku,quantity`. Each row is one line item;
consecutive rows with the same `order_id` belong to the same order.

Validate each row:

- `order_id` and `customer_id` must be non-empty.
- `customer_id` must exist in `CustomerRepository`; `sku` must exist in
  `ProductRepository`.
- `quantity` must parse as a positive integer.
- An `order_id` that already exists in `OrderRepository` is a duplicate and
  the whole order (all its rows) is rejected.

Behavior:

- Valid orders are built (via `shop.models.Order`/`LineItem`) and added to
  `OrderRepository`.
- Invalid rows are skipped and collected into an error report; if any row of
  an order is invalid, none of that order's line items are imported, but
  other valid orders in the file still are.
- Return an `ImportReport` (a small dataclass) with: `imported_order_ids:
  list[str]`, `errors: list[str]` where each error names the row number and
  reason (e.g. `"row 4: unknown sku 'xyz'"`).

Add unit tests in `tests/` covering: an all-valid file, a file with a bad
sku, a file with a non-numeric quantity, and a duplicate order id.

## Public API (required — hidden acceptance tests import these exact names)

In `src/shop/csv_import.py`:

```python
from dataclasses import dataclass, field


@dataclass
class ImportReport:
    imported_order_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def import_orders_csv(
    path,  # str or pathlib.Path
    products: "shop.repository.ProductRepository",
    customers: "shop.repository.CustomerRepository",
    orders: "shop.repository.OrderRepository",
) -> ImportReport:
    """Read the CSV at `path` (columns: order_id,customer_id,sku,quantity),
    validate, and add valid orders to `orders`. Returns an ImportReport
    whose `imported_order_ids` lists the order_ids that were successfully
    added (in file order) and whose `errors` lists one message per rejected
    row or rejected order."""
```

`import_orders_csv` must accept a plain string path as well as a
`pathlib.Path` (open it directly, e.g. via `open(path)` or
`Path(path).open()`).
