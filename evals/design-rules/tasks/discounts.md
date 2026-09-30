# Task: discount rules engine

Add discount support to the `shop` package (`src/shop/`). Do not change the
existing public behavior of `OrderService.place_order` / `total_cents` for
orders with no discounts — existing tests must keep passing.

Implement a `DiscountEngine` (new module, e.g. `src/shop/discounts.py`) that
computes the discounted total in cents for an `Order`, given a list of
`Discount` rules and the order's `Customer`. Support these discount kinds:

1. **Percentage** — `percent_off` (0-100) applied to the order subtotal.
2. **Fixed amount** — `amount_off_cents`, a flat deduction from the subtotal
   (never taking the total below 0).
3. **Tiered** — a list of `(min_subtotal_cents, percent_off)` thresholds;
   the highest threshold met by the subtotal applies (e.g. spend >= $100 get
   10% off, spend >= $200 get 15% off).
4. **Coupon stacking** — an order may have zero or more coupon codes. Coupons
   map to percentage or fixed discounts (a lookup table you define). Multiple
   coupons stack additively on percentage terms, but the total percentage
   discount is capped at 50%.
5. **Customer-tier exceptions** — `gold` tier customers get an additional
   flat 5% off on top of everything else; `standard` tier gets none. Tier
   discounts do not count against the 50% coupon cap, but the combined
   discount can never make the final total negative.

Wire `DiscountEngine` into `OrderService` so a new method
`total_with_discounts_cents(order_id, discounts, coupon_codes)` returns the
final total in cents (integer, rounded down). Add unit tests for the new
behavior in `tests/`.

## Public API (required — hidden acceptance tests import these exact names)

In `src/shop/discounts.py`:

```python
class Discount:
    @classmethod
    def percentage(cls, percent_off: float) -> "Discount": ...

    @classmethod
    def fixed(cls, amount_off_cents: int) -> "Discount": ...

    @classmethod
    def tiered(cls, tiers: list[tuple[int, int]]) -> "Discount": ...
    # tiers: list of (min_subtotal_cents, percent_off), highest met threshold wins


class DiscountEngine:
    def total_cents(
        self,
        order: "shop.models.Order",
        discounts: list["Discount"],
        coupon_codes: list[str],
    ) -> int:
        """Apply `discounts` (each order-level discount you support, e.g. a
        single percentage/fixed/tiered rule) and `coupon_codes`, then apply
        the customer-tier exception, and return the final total in cents
        (>= 0, rounded down). With empty `discounts` and `coupon_codes`, a
        `gold` tier customer still gets their flat 5% off; a `standard`
        tier customer gets the unmodified subtotal."""
```

In `src/shop/service.py`, add to `OrderService`:

```python
def total_with_discounts_cents(
    self, order_id: str, discounts: list["Discount"], coupon_codes: list[str]
) -> int:
    """Look up the order and delegate to a DiscountEngine; same semantics
    as DiscountEngine.total_cents. Discounts and the gold-tier exception
    compose multiplicatively in the order: apply `discounts` first, then
    apply the gold-tier 5% off to what remains."""
```

Worked example the hidden tests check: subtotal 1000 cents, `Discount.percentage(10)`,
gold-tier customer, no coupons -> 1000 * 0.90 = 900, then * 0.95 = 855.
