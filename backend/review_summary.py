"""Shared read-only projection of original observations and human review."""
from backend.contracts import ExtractionPayload


def resolution_blockers(payload, events):
    latest = {event["row_id"]: event["action"] for event in events if event.get("row_id")}
    decided = {row_id for row_id, action in latest.items()
               if action in {"approve", "no_match", "acknowledge"}}
    blockers = []
    if not payload.rows or any(row.row_id not in decided for row in payload.rows):
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


def reviewed_summary(run, events):
    result = {"run_id": str(run.id), "state": run.state, "review_state": run.review_state,
              "approved_products": [], "pending_row_ids": [], "excluded_rows": [],
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
        event = latest.get(row.row_id)
        if not event or event["action"] not in {"approve", "no_match", "acknowledge"}:
            result["pending_row_ids"].append(row.row_id)
        elif row.row_kind == "product" and event["action"] == "approve":
            candidate = event["new_value"]["candidate"]
            values = {}
            for field in ("quantity", "unit"):
                correction = next((e for e in reversed(events) if e["row_id"] == row.row_id
                    and e["action"] == "correct" and e["new_value"].get("field_name") == field), None)
                values[field] = correction["new_value"]["value"] if correction else getattr(row, field).raw_value
            result["approved_products"].append({
                "row_id": row.row_id, "candidate": candidate,
                "quantity": values["quantity"], "unit": values["unit"],
                "original_quantity": row.quantity.raw_value, "original_unit": row.unit.raw_value,
                "reviewer": event["reviewer"], "reason": event["reason"],
                "evidence": [ref.model_dump(mode="json") for ref in row.evidence]})
        else:
            result["excluded_rows"].append({"row_id": row.row_id, "row_kind": row.row_kind,
                                           "decision": event["action"]})
    result["blockers"] = resolution_blockers(payload, events)
    result["can_finish_review"] = not result["blockers"] and run.review_state != "resolved"
    return result
