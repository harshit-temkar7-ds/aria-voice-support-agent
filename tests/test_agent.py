
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient
from google.genai import types

from app import agent, orders, summarizer
from app.main import app


def function_response(name, args):
    return NS(
        candidates=[
            NS(
                content=NS(
                    parts=[
                        NS(
                            function_call=NS(name=name, args=args)
                        )
                    ]
                )
            )
        ],
        text=None,
    )


def text_response(text):
    return NS(
        candidates=[
            NS(
                content=NS(
                    parts=[NS(text=text, function_call=None)]
                )
            )
        ],
        text=text,
    )


class FakeModels:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class Fake:
    def __init__(self, *responses):
        self.models = FakeModels(*responses)


def test_tool_loop():
    orders.reset_orders()
    client = Fake(
        function_response("get_order_details", {"order_id": "ord 101"}),
        text_response("It is out for delivery."),
    )

    reply, events = agent.chat([], "where is ord 101", client=client)

    assert reply == "It is out for delivery."
    assert events[0]["order_id"] == "ORD-101"
    assert events[0]["success"] is True

    second_call_contents = client.models.calls[1]["contents"]

    function_response_parts = [
        part
        for content in second_call_contents
        if hasattr(content, "parts")
        for part in content.parts
        if getattr(part, "function_response", None)
    ]

    assert function_response_parts
    result = function_response_parts[0].function_response.response["result"]
    assert result["order"]["courier"] == "BlueDart"

    orders.reset_orders()


def test_invalid_and_missing():
    assert (
        agent.run_tool("get_order_details", {"order_id": "ORD-999"})["error"]
        == "ORDER_NOT_FOUND"
    )
    assert agent.run_tool("get_order_details", {})["error"] == "MISSING_ORDER_ID"


def test_cancel_enforced_server_side():
    orders.reset_orders()

    assert (
        agent.run_tool("cancel_order", {"order_id": "ORD-101"})["error"]
        == "NOT_CANCELLABLE"
    )
    assert agent.run_tool("cancel_order", {"order_id": "ORD-103"})["success"]
    assert orders.find_order("ORD-103")["status"] == "Cancelled"

    orders.reset_orders()


def test_api(monkeypatch):
    # Remove the Gemini key even if it was loaded from .env at startup.
    monkeypatch.setattr(agent, "get_client", lambda: None)

    client = TestClient(app)

    assert client.get("/api/health").json()["status"] == "ok"
    assert len(client.get("/api/orders").json()) == 3
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 503
    assert client.post("/api/chat", json={"message": ""}).status_code == 422

    summary = client.post(
        "/api/summary",
        json={
            "transcript": [
                {"role": "user", "content": "where is ORD-101"}
            ],
            "tool_events": [
                {"order_id": "ORD-101", "success": True}
            ],
        },
    ).json()

    assert summary["order_id"] == "ORD-101"
    assert summary["customer_intent"] == "ORDER_TRACKING"



def test_summary_fallback_on_bad_llm():
    # Fallback should work when the Gemini summary response is invalid.
    class FakeGeminiSummary:
        def __init__(self):
            self.models = self

        def generate_content(self, **kwargs):
            return NS(text="not json")

    client = FakeGeminiSummary()

    summary = summarizer.summarize(
        [{"role": "user", "content": "cancel ORD-103"}],
        [
            {
                "tool": "get_order_details",
                "order_id": "ORD-103",
                "success": True,
            }
        ],
        client=client,
    )

    assert summary["customer_intent"] == "CANCELLATION"
    assert summary["order_id"] == "ORD-103"
    assert summary["resolution_status"] == "UNRESOLVED"
