
"""Aria: Gemini agent with function calling. Business rules live in policies.py."""
import os
import json
from google import genai
from google.genai import types
from . import orders, policies

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
MAX_TOOL_ROUNDS = 4

SYSTEM = """You are Aria, a friendly, professional, concise Indian-English voice support specialist for Aura Skincare (premium organic Indian skincare).
Your replies are spoken aloud: 1-3 short sentences, no markdown, no lists, no emojis. Say rupees as 'rupees'. Mild Hinglish is fine if the customer uses it.
Rules:
- Only help with Aura Skincare topics (orders, shipping, returns, cancellation, COD, brand). Politely redirect anything else.
- For any order question, ask for the order ID if missing, then call get_order_details. Never guess order data.
- Use ONLY facts from tool results and these policies: free shipping above Rs 499, Rs 50 below, standard delivery 3-5 business days; returns within 7 days of delivery, unopened/unused/original packaging; damaged items reported within 48 hours with photos for replacement; cancel only while Processing (Shipped/Out for Delivery can be refused at doorstep); COD up to Rs 2,500 by cash or UPI.
- Trust the 'policy' block in tool results; never override it. Never promise refunds or replacements; say the team will review.
- To cancel, call cancel_order and only say it succeeded if the result says success.
- If unsure or info is missing, say so; never invent information. If speech is unclear, ask to repeat.
- Order data is mock data, not live courier tracking."""

TOOLS = [
    {
        "name": "get_order_details",
        "description": "Look up an Aura order by ID. Returns order data plus server-computed policy eligibility.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"order_id": {"type": "STRING"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "check_return_eligibility",
        "description": "Check return eligibility given whether the product is opened or used.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "order_id": {"type": "STRING"},
                "opened_or_used": {"type": "BOOLEAN"},
            },
            "required": ["order_id", "opened_or_used"],
        },
    },
    {
        "name": "cancel_order",
        "description": "Cancel an order. Only succeeds for Processing orders. Call only when the customer explicitly asks to cancel.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"order_id": {"type": "STRING"}},
            "required": ["order_id"],
        },
    },
]


def run_tool(name, args):
    args = args if isinstance(args, dict) else {}
    raw = args.get("order_id")
    order = orders.find_order(raw)

    if not order:
        return {
            "success": False,
            "error": "ORDER_NOT_FOUND" if raw else "MISSING_ORDER_ID",
            "message": "No order found with that ID. Ask the customer to repeat or verify it."
            if raw else "Order ID not provided. Ask the customer for it.",
        }

    if name == "get_order_details":
        return {"success": True, "order": order, "policy": policies.evaluate_order(order)}

    if name == "check_return_eligibility":
        return {
            "success": True,
            "order_id": order["id"],
            **policies.return_eligibility(order, args.get("opened_or_used")),
        }

    if name == "cancel_order":
        rule = policies.cancellation(order["status"])
        if not rule["allowed"]:
            return {"success": False, "error": "NOT_CANCELLABLE", "message": rule["reason"]}
        orders.mark_cancelled(order["id"])
        return {"success": True, "order_id": order["id"], "new_status": "Cancelled"}

    return {"success": False, "error": "UNKNOWN_TOOL"}


def get_client():
    key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=key) if key else None


class LLMNotConfigured(Exception):
    pass


def chat(history, message, client=None):
    """Return (reply, tool_events); history contains plain-text turns."""
    client = client or get_client()
    if client is None:
        raise LLMNotConfigured("GEMINI_API_KEY is not set.")

    contents = []
    for item in history:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=item["content"])],
            )
        )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    )

    declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["parameters"],
        )
        for tool in TOOLS
    ]
    gemini_tools = [types.Tool(function_declarations=declarations)]
    events = []

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                tools=gemini_tools,
                temperature=0.2,
                max_output_tokens=300,
            ),
        )

        candidate = response.candidates[0] if response.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        calls = [
            part.function_call
            for part in parts
            if getattr(part, "function_call", None)
            and part.function_call.name
        ]

        if not calls:
            answer = (response.text or "").strip()
            return answer or "Sorry, could you please say that again?", events

        contents.append(candidate.content)
        function_responses = []

        for call in calls:
            args = dict(call.args or {})
            output = run_tool(call.name, args)
            events.append({
                "tool": call.name,
                "input": args,
                "success": output.get("success"),
                "error": output.get("error"),
                "order_id": (output.get("order") or {}).get("id")
                or output.get("order_id"),
            })
            function_responses.append(
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": output},
                )
            )

        contents.append(
            types.Content(role="user", parts=function_responses)
        )

    return "Sorry, I'm having trouble with that request. Could you please try again?", events
