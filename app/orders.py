"""Mock order store. Status changes (cancellations) are held in memory only."""
import copy, json, re
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "data" / "orders.json"
_BASE = {o["id"]: o for o in json.loads(_PATH.read_text(encoding="utf-8"))}
_state = copy.deepcopy(_BASE)


def normalize_order_id(value):
    if not value:
        return None

    text = str(value).upper().strip()

    # Accept: ORD-101, ORD 101, ORD101, ORDER 101,
    # ORDER NUMBER 101, and ORDER #101.
    match = re.search(
        r"\b(?:ORDER\s*(?:NUMBER|NO\.?)?\s*|ORD\s*)#?\s*[- ]?(\d{3})\b",
        text,
    )

    if not match:
        return None

    return f"ORD-{match.group(1)}"


def list_orders():
    return list(_state.values())


def find_order(raw_id):
    oid = normalize_order_id(raw_id)
    return copy.deepcopy(_state[oid]) if oid in _state else None


def mark_cancelled(order_id):
    _state[order_id]["status"] = "Cancelled"


def reset_orders():
    _state.clear()
    _state.update(copy.deepcopy(_BASE))
