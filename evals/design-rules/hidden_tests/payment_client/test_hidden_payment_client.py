from shop.payment import (
    PaymentClient,
    TransportConnectionError,
    TransportHTTPError,
    TransportTimeout,
)


class FakeTransport:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = 0

    def send(self, order_id, amount_cents, idempotency_key):
        self.calls += 1
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _client(transport):
    sleeps = []
    return PaymentClient(
        transport=transport,
        sleep=sleeps.append,
        clock=_counter(),
    )


def _counter():
    state = {"t": 0.0}

    def clock():
        state["t"] += 0.01
        return state["t"]

    return clock


def test_immediate_success():
    transport = FakeTransport([{"status": "ok", "charge_id": "ch_1"}])
    client = _client(transport)
    result = client.charge("o1", 1000, "idem-1")
    assert result.success is True
    assert result.attempts == 1


def test_success_after_two_retries():
    transport = FakeTransport(
        [
            TransportTimeout(),
            TransportConnectionError(),
            {"status": "ok", "charge_id": "ch_2"},
        ]
    )
    client = _client(transport)
    result = client.charge("o1", 1000, "idem-2")
    assert result.success is True
    assert result.attempts == 3


def test_permanent_decline_no_retry():
    transport = FakeTransport([TransportHTTPError(402, "declined")])
    client = _client(transport)
    result = client.charge("o1", 1000, "idem-3")
    assert result.success is False
    assert result.error_code == "declined"
    assert transport.calls == 1


def test_exhausted_retries_on_503():
    transport = FakeTransport(
        [
            TransportHTTPError(503, "busy"),
            TransportHTTPError(503, "busy"),
            TransportHTTPError(503, "busy"),
        ]
    )
    client = _client(transport)
    result = client.charge("o1", 1000, "idem-4")
    assert result.success is False
    assert result.error_code == "server_error"
    assert transport.calls == 3
