"""Shared read-only projection of original observations and human review."""
from backend.contracts import ExtractionPayload
from gate_a.contracts import RowKind

SUMMARY_POLICY_VERSION = "review-summary-v2"


def effective_row_role(row, schema_version):
    if schema_version == "1.2":
        return row.row_role
    if row.row_kind == RowKind.PRODUCT:
        return "product_item"
    if row.row_kind in {RowKind.CHARGE, RowKind.TAX, RowKind.SUBTOTAL, RowKind.TOTAL, RowKind.NOTE}:
        return "document_detail"
    return "unknown"


def resolution_blockers(payload, events, tiers=None):
    latest = {event["row_id"]: event["action"] for event in events if event.get("row_id")}
    decided = {row_id for row_id, action in latest.items()
               if action in {"approve", "no_match", "not_a_product", "not_product"}}
    for row in payload.rows:
        if legacy_no_match_requires_answer(row, latest.get(row.row_id), tiers):
            decided.discard(row.row_id)
    blockers = []
    required = [row for row in payload.rows if effective_row_role(row, payload.schema_version)
                in {"product_item", "unknown"}]
    if not required or any(row.row_id not in decided for row in required):
        blockers.append("unresolved_rows_remain")
    if any(page.state == "failed" for page in payload.pages):
        blockers.append("failed_pages_require_new_processing_run")
    acknowledged = {ref["page_number"] for event in events
                    if event["action"] == "acknowledge_page"
                    for ref in event["evidence_reference"]}
    if any(page.state == "partial" and page.page_number not in acknowledged for page in payload.pages):
        blockers.append("partial_pages_require_explicit_acknowledgement")
    if payload.warnings and not any(event["action"] == "acknowledge_document" for event in events):
        blockers.append("document_warnings_require_explicit_acknowledgement")
    return blockers


def legacy_no_match_requires_answer(row, action, tiers):
    return action == "no_match" and (row.row_kind == "unknown" or
                                    (tiers or {}).get(row.row_id) == "uncertain")


def reviewed_summary(run, events, tiers=None):
    result = {"run_id": str(run.id), "state": run.state, "review_state": run.review_state,
              "summary_policy_version": SUMMARY_POLICY_VERSION,
              "approved_products": [], "pending_row_ids": [], "excluded_rows": [], "document_details": [],
              "review_event_count": len(events), "blockers": [],
              "can_finish_review": False, "source_observations_unchanged": True}
    if run.state not in {"completed", "partial"} or not run.result:
        result["blockers"] = ["run_has_no_reviewable_purchase_order"]
        return result
    payload = ExtractionPayload.model_validate(run.result)
    if payload.document_type != "purchase_order":
        result["blockers"] = ["run_has_no_reviewable_purchase_order"]
        return result
    latest = {e["row_id"]: e for e in events if e.get("row_id")}
    for row in payload.rows:
        role = effective_row_role(row, payload.schema_version)
        if role == "continuation":
            result["document_details"].append({"row_id": row.row_id, "row_kind": row.row_kind,
                "role": role, "item_group_id": row.item_group_id, "continuation_of": row.continuation_of,
                "raw_description": row.description.raw_value,
                "evidence": [ref.model_dump(mode="json") for ref in row.evidence]})
            continue
        if role == "document_detail":
            result["document_details"].append({"row_id": row.row_id, "row_kind": row.row_kind,
                "role": role, "description": row.description.raw_value,
                "line_total": row.line_total.raw_value,
                "evidence": [ref.model_dump(mode="json") for ref in row.evidence]})
            continue
        event = latest.get(row.row_id)
        if (not event or event["action"] not in {"approve", "no_match", "not_a_product", "not_product"}
                or legacy_no_match_requires_answer(row, event["action"], tiers)):
            result["pending_row_ids"].append(row.row_id)
        elif event["action"] == "approve":
            candidate = event["new_value"]["candidate"]
            values = {}
            for field in ("quantity", "unit"):
                correction = next((e for e in reversed(events) if e["row_id"] == row.row_id
                    and e["action"] == "correct" and e["new_value"].get("field_name") == field), None)
                values[field] = correction["new_value"]["value"] if correction else getattr(row, field).raw_value
            continuation_rows = [candidate_row for candidate_row in payload.rows
                if effective_row_role(candidate_row, payload.schema_version) == "continuation" and
                (candidate_row.continuation_of == row.row_id if payload.schema_version == "1.2"
                 else candidate_row.item_group_id == (row.item_group_id or row.row_id))]
            result["approved_products"].append({
                "row_id": row.row_id, "candidate": candidate,
                "item_group_id": row.item_group_id or row.row_id,
                "description": row.description.raw_value,
                "continuation_descriptions": [{"row_id": item.row_id,
                    "raw_description": item.description.raw_value,
                    "evidence": [ref.model_dump(mode="json") for ref in item.evidence]}
                    for item in continuation_rows],
                "quantity": values["quantity"], "unit": values["unit"],
                "original_quantity": row.quantity.raw_value, "original_unit": row.unit.raw_value,
                "reviewer": event["reviewer"], "reason": event["reason"],
                "evidence": [ref.model_dump(mode="json") for ref in row.evidence]})
        else:
            result["excluded_rows"].append({"row_id": row.row_id, "row_kind": row.row_kind,
                                           "decision": event["action"]})
    result["blockers"] = resolution_blockers(payload, events, tiers)
    result["can_finish_review"] = not result["blockers"] and run.review_state != "resolved"
    return result
