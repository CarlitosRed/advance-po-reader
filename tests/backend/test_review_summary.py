"""A saved correction invalidates prior approval without changing source literals."""
from types import SimpleNamespace
from uuid import uuid4

from backend.review_summary import reviewed_summary, resolution_blockers
from backend.synthetic import fixture_payload


def run(payload, **extra):
    return SimpleNamespace(id=uuid4(), state="completed", review_state="in_progress",
                           result=payload.model_dump(mode="json"), **extra)


def decisions(payload):
    return [{"row_id": row.row_id, "action": "approve" if row.row_kind == "product" else "acknowledge",
        "reviewer": "Fictional QA", "reason": "Fictional source checked", "evidence_reference": [],
        "new_value": {"candidate": {"candidate_id": str(uuid4()), "sku": "FICTIONAL", "description": "Fixture", "method": "exact"}}}
        for row in payload.rows]


def test_raw_strings_remain_distinct_from_corrected_approved_quantity():
    payload = fixture_payload()
    events = decisions(payload)
    events.append({"row_id": "line-1", "action": "correct", "new_value": {"field_name": "quantity", "value": "002.50"}})
    summary = reviewed_summary(run(payload), events)
    assert "line-1" in summary["pending_row_ids"] and not summary["can_finish_review"]
    events.append(decisions(payload)[0])
    summary = reviewed_summary(run(payload), events)
    first = summary["approved_products"][0]
    assert first["quantity"] == "002.50" and first["original_quantity"] == "2"
    assert payload.rows[0].quantity.raw_value == "2"
    assert summary["can_finish_review"] and len(summary["excluded_rows"]) == 2


def test_partial_and_document_warnings_require_their_own_acknowledgements():
    payload = fixture_payload("partial")
    events = decisions(payload)
    assert "partial_pages_require_explicit_acknowledgement" in resolution_blockers(payload, events)
    events.append({"row_id": None, "action": "acknowledge_page", "evidence_reference": [{"page_number": 1}]})
    if payload.warnings:
        assert "document_warnings_require_explicit_acknowledgement" in resolution_blockers(payload, events)
        events.append({"row_id": None, "action": "acknowledge_document"})
    assert resolution_blockers(payload, events) == []


def test_unsupported_or_unprocessed_run_has_no_approved_products():
    payload = fixture_payload("unsupported")
    summary = reviewed_summary(run(payload), [])
    assert not summary["approved_products"] and not summary["can_finish_review"]
    unprocessed = run(fixture_payload())
    unprocessed.state = "created"
    unprocessed.result = None
    assert reviewed_summary(unprocessed, [])["blockers"] == ["run_has_no_reviewable_purchase_order"]
