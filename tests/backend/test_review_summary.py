"""A saved correction invalidates prior approval without changing source literals."""
from types import SimpleNamespace
from uuid import uuid4
import pytest

from backend.review_summary import reviewed_summary, resolution_blockers
from backend.synthetic import fixture_payload


@pytest.mark.parametrize("unknown", [False, True])
def test_legacy_no_match_on_unknown_or_uncertain_row_is_pending(unknown):
    raw = fixture_payload().model_dump(mode="json")
    row = raw["rows"][0]
    if unknown:
        row.update(row_kind="unknown", uncertainty="Legacy ambiguous row")
    payload = type(fixture_payload()).model_validate(raw)
    events = decisions(payload)
    events[0].update(action="no_match", new_value={})
    tiers = {} if unknown else {row["row_id"]: "uncertain"}
    summary = reviewed_summary(run(payload), events, tiers)
    assert summary["pending_row_ids"] == [row["row_id"]]
    assert summary["excluded_rows"] == []
    assert "unresolved_rows_remain" in summary["blockers"]
    assert not summary["can_finish_review"]


def run(payload, **extra):
    return SimpleNamespace(id=uuid4(), state="completed", review_state="in_progress",
                           result=payload.model_dump(mode="json"), **extra)


def decisions(payload):
    return [{"row_id": row.row_id, "action": "approve" if row.row_kind == "product" else "not_a_product",
        "reviewer": "Fictional QA", "reason": "Fictional source checked", "evidence_reference": [],
        "new_value": {"candidate": {"candidate_id": str(uuid4()), "sku": "FICTIONAL", "description": "Fixture", "method": "exact"}}}
        for row in payload.rows]


@pytest.mark.parametrize("safety_net_finish_blocking", [False, True])
@pytest.mark.parametrize("schema_version", ["1.1", "1.2"])
@pytest.mark.parametrize("details_only", [False, True])
def test_zero_product_order_keeps_finish_blocker(safety_net_finish_blocking, schema_version, details_only):
    raw = fixture_payload("continuation" if schema_version == "1.2" else "purchase_order").model_dump(mode="json")
    raw["rows"] = [row for row in raw["rows"] if row["row_kind"] in {"charge", "total", "note"}] if details_only else []
    payload = type(fixture_payload()).model_validate(raw)
    assert resolution_blockers(payload, [], safety_net_finish_blocking=safety_net_finish_blocking) == ["unresolved_rows_remain"]
    summary = reviewed_summary(run(payload), [], safety_net_finish_blocking=safety_net_finish_blocking)
    assert summary["blockers"] == ["unresolved_rows_remain"]
    assert not summary["can_finish_review"]
    assert summary["pending_row_ids"] == summary["approved_products"] == []


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
    assert summary["can_finish_review"] and len(summary["excluded_rows"]) == 0
    assert len(summary["document_details"]) == 2


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


def test_summary_v2_groups_continuation_and_keeps_typed_details_out_of_review():
    payload = fixture_payload("continuation")
    events = [{"row_id": row.row_id, "action": "approve", "reviewer": "Fictional QA",
        "reason": "Fixture evidence checked", "new_value": {"candidate": {"candidate_id": str(uuid4()),
            "sku": "SYN-101", "description": "Synthetic support arm", "method": "bounded_exact"}}}
        for row in (payload.rows[0], payload.rows[2])]
    summary = reviewed_summary(run(payload), events)
    assert summary["summary_policy_version"] == "review-summary-v2"
    assert not summary["can_finish_review"] and summary["pending_row_ids"] == ["ambiguous-item"]
    assert [item["row_id"] for item in summary["approved_products"]] == ["item-101", "item-202"]
    assert summary["approved_products"][0]["continuation_descriptions"][0]["raw_description"] == "20 inch width; 16′ length; zinc-coated steel"
    assert [item["row_kind"] for item in summary["document_details"]] == ["unknown", "charge", "total", "note"]
    assert len(summary["document_details"]) == 4


def test_unknown_row_without_valid_relationship_cannot_be_hidden():
    payload = fixture_payload("continuation").model_dump(mode="json")
    payload["rows"][1].update(row_role="unknown", item_group_id=None, continuation_of=None,
        uncertainty="Synthetic source cannot establish continuation")
    parsed = type(fixture_payload("continuation")).model_validate(payload)
    events = [{"row_id": row.row_id, "action": "approve", "reviewer": "Fictional QA",
        "reason": "Candidate reviewed", "new_value": {"candidate": {"candidate_id": str(uuid4()),
        "sku": "SYN", "description": "Fixture", "method": "synthetic"}}}
        for row in (parsed.rows[0], parsed.rows[2])]
    summary = reviewed_summary(run(parsed), events)
    assert summary["pending_row_ids"] == ["description-cont-101", "ambiguous-item"]
    assert "unresolved_rows_remain" in summary["blockers"] and not summary["can_finish_review"]


def test_legacy_rows_are_preserved_but_document_details_no_longer_need_decisions():
    payload = fixture_payload()
    events = [{"row_id": payload.rows[0].row_id, "action": "approve", "reviewer": "Fictional QA",
        "reason": "Source checked", "new_value": {"candidate": {"candidate_id": str(uuid4()),
        "sku": "SYN-001", "description": "Synthetic widget", "method": "exact"}}},
        {"row_id": payload.rows[1].row_id, "action": "approve", "reviewer": "Fictional QA",
         "reason": "Source checked", "new_value": {"candidate": {"candidate_id": str(uuid4()),
         "sku": "SYN-002", "description": "Synthetic widget", "method": "exact"}}}]
    summary = reviewed_summary(run(payload), events)
    assert summary["can_finish_review"] and summary["pending_row_ids"] == []
    assert summary["excluded_rows"] == []
    assert len(summary["document_details"]) == 2
    assert summary["review_event_count"] == 2


def test_candidate_approval_stays_explicit_and_correction_invalidates_it():
    payload = fixture_payload("continuation")
    events = [{"row_id": row.row_id, "action": "approve", "reviewer": "Fictional QA",
        "reason": "Reviewed candidate", "new_value": {"candidate": {"candidate_id": str(uuid4()),
        "sku": "SYN", "description": "Fixture", "method": "synthetic"}}}
        for row in (payload.rows[0], payload.rows[2])]
    assert reviewed_summary(run(payload), events)["approved_products"]
    events.append({"row_id": "item-101", "action": "correct", "new_value": {"field_name": "quantity", "value": "004"}})
    summary = reviewed_summary(run(payload), events)
    assert summary["pending_row_ids"] == ["item-101", "ambiguous-item"]
    assert summary["approved_products"][0]["row_id"] == "item-202"
