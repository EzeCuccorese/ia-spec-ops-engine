import pytest
from shop.discounts import Discount, DiscountEngine
from shop.models import Customer, LineItem, Order, Product
from shop.repository import CustomerRepository, OrderRepository, ProductRepository
from shop.service import OrderService


def _order(subtotal_cents: int, tier: str = "standard") -> Order:
    product = Product(sku="x", name="X", unit_price_cents=subtotal_cents)
    customer = Customer(customer_id="c", name="C", tier=tier)
    order = Order(order_id="o", customer=customer)
    order.add_item(LineItem(product=product, quantity=1))
    return order


def test_percentage_discount():
    engine = DiscountEngine()
    order = _order(1000)
    total = engine.total_cents(order, [Discount.percentage(10)], [])
    assert total == 900


def test_fixed_amount_never_negative():
    engine = DiscountEngine()
    order = _order(100)
    total = engine.total_cents(order, [Discount.fixed(500)], [])
    assert total == 0


def test_tiered_highest_threshold_wins():
    engine = DiscountEngine()
    tiers = [(10000, 10), (20000, 15)]
    order = _order(20000)
    total = engine.total_cents(order, [Discount.tiered(tiers)], [])
    assert total == 17000


def test_gold_tier_extra_five_percent():
    engine = DiscountEngine()
    order = _order(1000, tier="gold")
    total = engine.total_cents(order, [], [])
    assert total == 950


@pytest.fixture
def service() -> OrderService:
    products = ProductRepository()
    products.add(Product(sku="widget", name="Widget", unit_price_cents=1000))
    customers = CustomerRepository()
    customers.add(Customer(customer_id="c1", name="Ada", tier="gold"))
    return OrderService(products, customers, OrderRepository())


def test_service_total_with_discounts(service: OrderService):
    service.place_order("o1", "c1", [("widget", 1)])
    total = service.total_with_discounts_cents("o1", [Discount.percentage(10)], [])
    assert total == 855
