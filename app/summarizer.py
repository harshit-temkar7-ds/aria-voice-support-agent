
"""Post-call structured summary using Gemini, with a deterministic fallback."""
import json
import re

from . import agent, orders

INTENTS = [
    "ORDER_TRACKING",
    "CANCELLATION",
    "RETURN_REFUND",
    "SHIPPING_INFO",
    "COD_INFO",
    "DAMAGED_PRODUCT",
    "OUT_OF_SCOPE",
    "OTHER",
]
STATUSES = ["RESOLVED", "UNRESOLVED", "ESCALATION_NEEDED"]


def fallback_summary(transcript, events):
    user_text = " ".join(
        t["content"] for t in transcript if t["role"] == "user"
    ).lower()
    assistant_text = " ".join(
        t["content"] for t in transcript if t["role"] == "assistant"
    ).lower()

    oid = next(
        (e["order_id"] for e in reversed(events) if e.get("order_id")),
        None,
    )

    # Recognize ORD-103, ord103, "order 103", and "order-103".
    if not oid:
        match = re.search(r"\bord(?:er)?[\s-]*(\d{3})\b", user_text)
        if match:
            oid = orders.normalize_order_id(f"ORD-{match.group(1)}")

    intent = "OTHER"
    for keyword, name in [
        ("cancel", "CANCELLATION"),
        ("damag", "DAMAGED_PRODUCT"),
        ("return", "RETURN_REFUND"),
        ("refund", "RETURN_REFUND"),
        ("cod", "COD_INFO"),
        ("cash on", "COD_INFO"),
        ("shipping", "SHIPPING_INFO"),
        ("where", "ORDER_TRACKING"),
        ("track", "ORDER_TRACKING"),
        ("status", "ORDER_TRACKING"),
    ]:
        if keyword in user_text:
            intent = name
            break

    successful_tools = {
        e.get("tool")
        for e in events
        if e.get("success") is True
    }

    technical_failure = any(
        phrase in assistant_text
        for phrase in [
            "technical issue",
            "facing a technical issue",
            "ai service had a problem",
        ]
    )

    if technical_failure:
        status = "UNRESOLVED"
    elif intent == "CANCELLATION":
        new_cancellation = "cancel_order" in successful_tools
        already_cancelled = (
            "get_order_details" in successful_tools
            and (
                "already cancelled" in assistant_text
                or "already canceled" in assistant_text
            )
        )
        status = (
            "RESOLVED"
            if new_cancellation or already_cancelled
            else "UNRESOLVED"
        )
    elif intent == "ORDER_TRACKING":
        status = (
            "RESOLVED"
            if "get_order_details" in successful_tools
            and oid
            else "UNRESOLVED"
        )
    elif intent == "RETURN_REFUND":
        status = (
            "RESOLVED"
            if successful_tools.intersection(
                {"get_order_details", "check_return_eligibility"}
            ) and oid
            else "UNRESOLVED"
        )
    else:
        status = "RESOLVED" if successful_tools else "UNRESOLVED"

    customer_turns = sum(t["role"] == "user" for t in transcript)

    if status == "RESOLVED" and intent == "CANCELLATION":
        summary_text = (
            f"Cancellation request for {oid or 'an unspecified order'} "
            "was completed or the order was already cancelled."
        )
    elif status == "RESOLVED" and intent == "ORDER_TRACKING":
        summary_text = (
            f"Order information for {oid} was retrieved. "
            "See the transcript for delivery details."
        )
    elif status == "RESOLVED" and intent == "RETURN_REFUND":
        summary_text = (
            f"Return-related information for {oid} was checked. "
            "See the transcript for the eligibility decision."
        )
    else:
        summary_text = (
            "The request could not be confirmed as resolved. "
            "See the transcript for details."
        )

    return {
        "customer_intent": intent,
        "order_id": oid,
        "resolution_status": status,
        "call_summary": (
            f"Automatic summary: {customer_turns} customer turn(s). "
            f"{summary_text}"
        ),
    }


def summarize(transcript, events, client=None):
    if not transcript:
        return {
            "customer_intent": "OTHER",
            "order_id": None,
            "resolution_status": "UNRESOLVED",
            "call_summary": "No conversation took place.",
        }

    try:
        client = client or agent.get_client()
        if client is None:
            raise RuntimeError("Gemini client is not configured.")

        conversation = "\n".join(
            f"{turn['role']}: {turn['content']}"
            for turn in transcript
        )

        prompt = (
            f"Summarize this customer support call. Return ONLY valid JSON "
            f"with keys customer_intent (one of {INTENTS}), "
            f"order_id (string or null), resolution_status "
            f"(one of {STATUSES}), and call_summary (1-2 factual sentences). "
            f"Use the transcript and tool events. Do not claim an action "
            f"succeeded unless the evidence supports it.\n\n"
            f"Transcript:\n{conversation}\n\nTool events:\n"
            f"{json.dumps(events)}"
        )

        response = client.models.generate_content(
            model=agent.MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

        data = json.loads(response.text)

        if (
            data.get("customer_intent") not in INTENTS
            or data.get("resolution_status") not in STATUSES
            or not isinstance(data.get("call_summary"), str)
            or not (
                data.get("order_id") is None
                or isinstance(data.get("order_id"), str)
            )
        ):
            raise ValueError("Invalid summary response.")

        return {
            key: data.get(key)
            for key in (
                "customer_intent",
                "order_id",
                "resolution_status",
                "call_summary",
            )
        }

    except Exception:
        return fallback_summary(transcript, events)
