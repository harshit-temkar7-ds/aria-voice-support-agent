"""Deterministic Aura Skincare policy rules. The LLM never decides these."""
FREE_SHIPPING_ABOVE = 499
SHIPPING_FEE = 50
COD_MAX = 2500
RETURN_DAYS = 7
DAMAGE_REPORT_HOURS = 48


def shipping_info(value):
    if value > FREE_SHIPPING_ABOVE:
        return {"fee": 0, "note": "Free shipping (order above Rs 499)."}
    if value < FREE_SHIPPING_ABOVE:
        return {"fee": SHIPPING_FEE, "note": "Rs 50 shipping fee (order below Rs 499)."}
    return {"fee": None, "note": "Policy does not state a shipping rule for exactly Rs 499; do not guess, offer to check with the team."}


def cod_eligible(value):
    return value <= COD_MAX


def cancellation(status):
    if status == "Processing":
        return {"allowed": True, "reason": "Order is Processing, so it can be cancelled."}
    if status in ("Shipped", "Out for Delivery"):
        return {"allowed": False, "reason": f"Order is {status} and cannot be cancelled. The customer may refuse delivery at the doorstep."}
    return {"allowed": False, "reason": f"Order status is {status}; cancellation is only possible while Processing."}


def return_eligibility(order, opened_or_used=None):
    """eligible: True / False / None (need more info from customer)."""
    if order["status"] != "Delivered":
        return {"eligible": False, "reason": "Returns apply only after delivery; this order is not delivered yet."}
    days = order.get("delivered_days_ago")
    if days is None:
        return {"eligible": None, "reason": "Delivery date unknown; cannot confirm the 7-day window."}
    if days > RETURN_DAYS:
        return {"eligible": False, "reason": f"Delivered {days} days ago, outside the {RETURN_DAYS}-day return window."}
    if opened_or_used is True:
        return {"eligible": False, "reason": "Product is opened/used; only unopened, unused items in original packaging can be returned."}
    if opened_or_used is None:
        return {"eligible": None, "reason": "Within 7 days. Ask whether the product is unopened, unused and in original packaging."}
    return {"eligible": True, "reason": "Within 7 days and unopened/unused. Eligible to request a return; do not promise a refund amount or timeline."}


def damage_report_eligibility(order):
    if order["status"] != "Delivered":
        return {"eligible": False, "reason": "Order not delivered yet."}
    days = order.get("delivered_days_ago")
    if days is None:
        return {"eligible": None, "reason": "Delivery date unknown."}
    if days * 24 > DAMAGE_REPORT_HOURS:
        return {"eligible": False, "reason": "Damage/defect must be reported within 48 hours of delivery; that window has passed."}
    return {"eligible": True, "reason": "Within 48 hours. Photos are required; replacement is subject to review, not guaranteed."}


def evaluate_order(order):
    return {
        "shipping": shipping_info(order["value"]),
        "cod_eligible": cod_eligible(order["value"]),
        "cancellation": cancellation(order["status"]),
        "return": return_eligibility(order),
        "damage_report": damage_report_eligibility(order),
    }
