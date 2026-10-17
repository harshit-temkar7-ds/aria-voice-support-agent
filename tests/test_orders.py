from app import orders

def test_normalize():
    assert orders.normalize_order_id("ord 101") == "ORD-101"
    assert orders.normalize_order_id("ORD103") == "ORD-103"
    assert orders.normalize_order_id("hello") is None and orders.normalize_order_id(None) is None

def test_lookup_and_missing():
    assert orders.find_order("ORD-101")["courier"] == "BlueDart"
    assert orders.find_order("ORD-999") is None
    assert len(orders.list_orders()) == 3
