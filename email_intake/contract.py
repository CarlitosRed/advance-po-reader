"""Closed classifier contract; all ordinary output uses fixed reason codes."""
import json

PAIRS = {
    "order": ("order", "new_order"),
    "change": ("needs_a_look", "change_requested"),
    "cancellation": ("needs_a_look", "cancel_requested"),
    "quote_request": ("needs_a_look", "quote_requested"),
    "invoice": ("not_an_order", "invoice_only"),
    "status_question": ("not_an_order", "status_only"),
    "other_business": ("not_an_order", "other_business_only"),
    "spam": ("not_an_order", "spam_only"),
    "unsure": ("needs_a_look", "unclear"),
}
LOCAL_REASONS = frozenset({"REFUSED", "INCOMPLETE", "INVALID", "TRANSPORT_PENDING",
                           "PARSE_FAILED", "LIMIT", "CAP", "CONFLICT", "MISSING_KEY",
                           "LIVE_DISABLED", "LEDGER", "DUPLICATE", "PDF_LIMIT"})
REASONS = LOCAL_REASONS | {pair[1] for pair in PAIRS.values()}
SCHEMA = {"type": "object", "properties": {
    "category": {"type": "string", "enum": list(PAIRS)},
    "lane": {"type": "string", "enum": ["order", "needs_a_look", "not_an_order"]},
    "reason_code": {"type": "string", "enum": [p[1] for p in PAIRS.values()]}},
    "required": ["category", "lane", "reason_code"], "additionalProperties": False}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("INVALID")
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=unique_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("INVALID")))


def decision(category):
    lane, reason = PAIRS[category]
    return {"category": category, "lane": lane, "reason_code": reason}


def pending(reason):
    if reason not in LOCAL_REASONS:
        reason = "INVALID"
    return {"category": "unsure", "lane": "needs_a_look", "reason_code": reason}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(SCHEMA["required"]):
        return pending("INVALID")
    if any(type(v) is not str for v in value.values()) or value["category"] not in PAIRS:
        return pending("INVALID")
    if (value["lane"], value["reason_code"]) != PAIRS[value["category"]]:
        return pending("CONFLICT")
    return value.copy()
