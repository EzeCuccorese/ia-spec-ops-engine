"""In-memory persistence for orders and products."""

from __future__ import annotations

from shop.models import Customer, Order, Product


class NotFoundError(Exception):
    """Raised when a lookup by id fails."""


class ProductRepository:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def add(self, product: Product) -> None:
        self._products[product.sku] = product

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError as exc:
            raise NotFoundError(f"unknown product sku: {sku}") from exc

    def all(self) -> list[Product]:
        return list(self._products.values())


class CustomerRepository:
    def __init__(self) -> None:
        self._customers: dict[str, Customer] = {}

    def add(self, customer: Customer) -> None:
        self._customers[customer.customer_id] = customer

    def get(self, customer_id: str) -> Customer:
        try:
            return self._customers[customer_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown customer id: {customer_id}") from exc


class OrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def add(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown order id: {order_id}") from exc

    def all(self) -> list[Order]:
        return list(self._orders.values())
