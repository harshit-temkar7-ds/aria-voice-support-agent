from app import policies as p, orders

def test_shipping():
    assert p.shipping_info(699)["fee"] == 0
    assert p.shipping_info(300)["fee"] == 50
    assert p.shipping_info(499)["fee"] is None

def test_cod():
    assert p.cod_eligible(2500) and not p.cod_eligible(2501)

def test_cancellation():
    assert p.cancellation("Processing")["allowed"]
    assert not p.cancellation("Out for Delivery")["allowed"]
    assert not p.cancellation("Shipped")["allowed"]

def test_returns():
    o102 = orders.find_order("ORD-102")
    assert p.return_eligibility(o102)["eligible"] is False
    assert p.damage_report_eligibility(o102)["eligible"] is False
    d = {"status": "Delivered", "delivered_days_ago": 3}
    assert p.return_eligibility(d, False)["eligible"] is True
    assert p.return_eligibility(d, True)["eligible"] is False
    assert p.return_eligibility(d)["eligible"] is None
    assert p.return_eligibility(orders.find_order("ORD-101"))["eligible"] is False
