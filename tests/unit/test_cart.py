"""Cart/order rules used by Agent mode: order total, and which orders can be cancelled."""

from decimal import Decimal

from services.order_service.app.cart import can_cancel, cart_total


def test_cart_total():
    assert cart_total([(Decimal("123.95"), 2), (Decimal("4.05"), 1)]) == Decimal("251.95")
    assert cart_total([]) == Decimal("0")


def test_only_placed_orders_can_be_cancelled():
    assert can_cancel("placed")
    for status in ("shipped", "out_for_delivery", "delivered", "cancelled", "returned"):
        assert not can_cancel(status)
