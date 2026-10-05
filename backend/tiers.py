"""Review tiers are independent of retrieval outcome and human approval."""
import re
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from backend.catalog import CANONICAL_SKU_ROLES, _description_code_hints, _numeric_description_code_hints
from backend.catalog import normalize_identifier
from backend.contracts import ExtractionPayload
from backend.models import Suggestion
from backend.review_summary import effective_row_role

# Broader labeled readings veto Certain even when the conservative retrieval
# hint path cannot yet discover that SKU (F7 remains a separate PR B repair).
LABELED_CODE = re.compile(r"\b(?:code|sku|product\s+(?:code|id)|item\s+(?:code|id))\b\s*[:#=]?\s*"
                          r"([A-Z0-9][A-Z0-9._/-]{0,39})(?![A-Z0-9._/-])", re.IGNORECASE)


def confidence_tier(row, suggestion):
    candidates = suggestion["candidates"]
    fields = [*row.identifiers, row.description, row.quantity, row.unit]
    if (row.row_kind != "product" or row.uncertainty or
            any(field.state in {"uncertain", "unreadable"} or field.alternative_readings for field in fields) or
            suggestion["outcome"] != "suggested" or len(candidates) != 1):
        return "uncertain", "Unresolved source evidence, classification or candidate ambiguity"
    candidate = candidates[0]
    codes = [identifier for identifier in row.identifiers
             if identifier.source_role in CANONICAL_SKU_ROLES and identifier.raw_value]
    hints = _description_code_hints(row.description.raw_value) + _numeric_description_code_hints(row.description.raw_value)
    hints += LABELED_CODE.findall(row.description.raw_value or "")
    readings = [identifier.raw_value for identifier in codes] + hints
    if any(normalize_identifier(value) != normalize_identifier(candidate["sku"]) for value in readings):
        return "uncertain", "Code-column and description readings conflict with the candidate"
    if (suggestion["method"] == "exact" and codes and
            all(identifier.state == "observed" and identifier.raw_value == candidate["sku"]
                for identifier in codes)):
        return "certain", "Unique literal code-column match; explicit human approval still required"
    return "probable", "Description, embedded-code, alias or normalized match requires confirmation"


def review_suggestions(session, tenant, run):
    records = session.scalars(select(Suggestion).where(Suggestion.tenant_id == tenant,
        Suggestion.run_id == run.id).order_by(Suggestion.row_id)).all()
    by_row = {record.row_id: record for record in records}
    if not run.result:
        return []
    payload = ExtractionPayload.model_validate(run.result)
    values = []
    for row in payload.rows:
        if effective_row_role(row, payload.schema_version) not in {"product_item", "unknown"}:
            continue
        record = by_row.get(row.row_id)
        value = ({column.name: getattr(record, column.name) for column in record.__table__.columns}
                 if record else {"id": uuid5(NAMESPACE_URL, f"{run.id}:{row.row_id}"),
                     "tenant_id": tenant, "run_id": run.id, "row_id": row.row_id,
                     "candidates": [], "method": "none", "outcome": "no_match",
                     "retrieval_version": "review-tiers-v1", "evidence": [],
                     "reason": "Unknown source row requires an explicit three-way decision",
                     "created_at": run.created_at})
        value["tier"], value["tier_reason"] = confidence_tier(row, value)
        value["approval_status"] = "needs_approval"
        value["suggested_candidate_id"] = value["candidates"][0]["candidate_id"] if value["tier"] == "certain" else None
        values.append(value)
    return values
