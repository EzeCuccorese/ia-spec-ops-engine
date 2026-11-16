import pytest
from shop.models import Customer, LineItem, Order, Product
from shop.notifier import (
    EmptyOrderError,
    NotificationFailed,
    OrderNotifier,
    SenderError,
)
from shop.repository import NotFoundError, OrderRepository


class _Sender:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent = []
        self._error = error

    def send(self, notification) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append(notification)


def _orders() -> OrderRepository:
    orders = OrderRepository()
    customer = Customer(customer_id="c1", name="Ada")
    order = Order(order_id="o1", customer=customer)
    order.add_item(LineItem(Product(sku="widget", name="Widget", unit_price_cents=500), 2))
    order.add_item(LineItem(Product(sku="gadget", name="Gadget", unit_price_cents=505), 1))
    orders.add(order)
    orders.add(Order(order_id="empty", customer=customer))
    return orders


def test_sends_the_confirmation():
    sender = _Sender()
    notification = OrderNotifier(_orders(), sender).notify("o1")
    assert sender.sent == [notification]
    assert notification.order_id == "o1"
    assert notification.customer_id == "c1"
    assert notification.body == "Order o1: 3 item(s), total 15.05"


def test_unknown_order_is_not_sent():
    sender = _Sender()
    with pytest.raises(NotFoundError):
        OrderNotifier(_orders(), sender).notify("missing")
    assert sender.sent == []


def test_empty_order_is_not_sent():
    sender = _Sender()
    with pytest.raises(EmptyOrderError):
        OrderNotifier(_orders(), sender).notify("empty")
    assert sender.sent == []


def test_sender_failure_is_wrapped():
    error = SenderError("down")
    with pytest.raises(NotificationFailed) as raised:
        OrderNotifier(_orders(), _Sender(error)).notify("o1")
    assert raised.value.__cause__ is error


def test_other_sender_errors_are_not_caught():
    with pytest.raises(ZeroDivisionError):
        OrderNotifier(_orders(), _Sender(ZeroDivisionError())).notify("o1")
