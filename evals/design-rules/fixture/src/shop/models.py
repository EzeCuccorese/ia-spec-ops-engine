"""Domain models for the shop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    unit_price_cents: int


@dataclass(frozen=True)
class LineItem:
    product: Product
    quantity: int

    @property
    def subtotal_cents(self) -> int:
        return self.product.unit_price_cents * self.quantity


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    tier: str = "standard"


@dataclass
class Order:
    order_id: str
    customer: Customer
    items: list[LineItem] = field(default_factory=list)

    @property
    def subtotal_cents(self) -> int:
        return sum(item.subtotal_cents for item in self.items)

    def add_item(self, item: LineItem) -> None:
        self.items.append(item)
