"""Independent, append-only page counts; provider declarations are not checks."""
from backend.review_summary import effective_row_role

COUNT_ACTION = "confirm_page_product_count"
COUNT_METHOD = "reviewer_source_product_count_v1"


def page_coverage(payload, events, source):
    checks = []
    for number in range(1, source.page_count + 1):
        # Count each original product item on its first source page only.
        # Continuation/detail rows and additional evidence do not add products.
        extracted = sum(effective_row_role(row, payload.schema_version) == "product_item"
                        and min(ref.page_number for ref in row.evidence) == number
                        for row in payload.rows)
        history = [event for event in events if event["action"] == COUNT_ACTION
                   and event["new_value"]["source_sha256"] == source.sha256
                   and event["new_value"]["page_number"] == number]
        latest = history[-1] if history else None
        independent = latest["new_value"]["product_count"] if latest else None
        discrepancy = any(event["new_value"]["source_discrepancy"] for event in history)
        status = "unavailable" if latest is None else (
            "mismatch" if extracted != independent or discrepancy else "matched")
        checks.append({"page_number": number, "source_sha256": source.sha256,
                       "provider_product_count": extracted, "independent_product_count": independent,
                       "status": status, "method": COUNT_METHOD if latest else None,
                       "latest_event_id": latest["id"] if latest else None,
                       "reviewer": latest["reviewer"] if latest else None,
                       "reason": latest["reason"] if latest else None,
                       "recorded_at": latest["created_at"] if latest else None,
                       "source_discrepancy": discrepancy,
                       "remedy": "new_source_bound_run" if status == "mismatch" else None})
    return checks


def coverage_blockers(checks):
    blockers = []
    if any(check["status"] == "unavailable" for check in checks):
        blockers.append("independent_page_product_counts_required")
    if any(check["status"] == "mismatch" for check in checks):
        blockers.append("page_product_count_mismatch_requires_new_run")
    return blockers


def synchronize_coverage_state(run, checks):
    """Only the coverage-held processing outcome may become completed.

    Count corrections may return completed -> partial before review resolution.
    Existing extraction/retrieval partial outcomes retain their original state.
    """
    if run.outcome_code in {"independent_coverage_required", "ready_for_human_review"}:
        blocked = bool(coverage_blockers(checks))
        run.state = "partial" if blocked else "completed"
        run.outcome_code = "independent_coverage_required" if blocked else "ready_for_human_review"
