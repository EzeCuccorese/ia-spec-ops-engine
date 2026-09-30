import pytest
from shop.models import Customer, Product
from shop.repository import (
    CustomerRepository,
    NotFoundError,
    OrderRepository,
    ProductRepository,
)
from shop.service import OrderService


@pytest.fixture
def service() -> OrderService:
    products = ProductRepository()
    products.add(Product(sku="widget", name="Widget", unit_price_cents=500))
    customers = CustomerRepository()
    customers.add(Customer(customer_id="c1", name="Ada", tier="gold"))
    return OrderService(products, customers, OrderRepository())


def test_place_order_computes_subtotal(service: OrderService) -> None:
    order = service.place_order("o1", "c1", [("widget", 3)])
    assert order.subtotal_cents == 1500


def test_total_cents_matches_order(service: OrderService) -> None:
    service.place_order("o1", "c1", [("widget", 2)])
    assert service.total_cents("o1") == 1000


def test_unknown_customer_raises(service: OrderService) -> None:
    with pytest.raises(NotFoundError):
        service.place_order("o2", "missing", [])


def test_unknown_product_raises(service: OrderService) -> None:
    with pytest.raises(NotFoundError):
        service.place_order("o3", "c1", [("missing", 1)])
