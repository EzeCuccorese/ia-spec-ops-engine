"""Order placement service."""

from __future__ import annotations

from shop.models import Customer, LineItem, Order, Product
from shop.repository import CustomerRepository, OrderRepository, ProductRepository


class OrderService:
    def __init__(
        self,
        products: ProductRepository,
        customers: CustomerRepository,
        orders: OrderRepository,
    ) -> None:
        self._products = products
        self._customers = customers
        self._orders = orders

    def place_order(self, order_id: str, customer_id: str, items: list[tuple[str, int]]) -> Order:
        customer: Customer = self._customers.get(customer_id)
        order = Order(order_id=order_id, customer=customer)
        for sku, quantity in items:
            product: Product = self._products.get(sku)
            order.add_item(LineItem(product=product, quantity=quantity))
        self._orders.add(order)
        return order

    def total_cents(self, order_id: str) -> int:
        order = self._orders.get(order_id)
        return order.subtotal_cents
