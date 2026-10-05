"""Independent source text, confined to declared regions; never catalog policy."""
from backend.review_summary import effective_row_role

METHOD = "pymupdf-region-text-casefold-whitespace-token-v1"
SOURCE_REVIEW_ACTION = "confirm_source_text"
UNAVAILABLE_ACTION = "confirm_unavailable_page_text"


def normalize(value):
    return " ".join(value.casefold().split())


def phrase_supported(observed, decoded):
    phrase, text = normalize(observed), normalize(decoded)
    if not phrase:
        return False
    start = text.find(phrase)
    while start >= 0:
        end = start + len(phrase)
        if (start == 0 or not text[start - 1].isalnum()) and (end == len(text) or not text[end].isalnum()):
            return True
        start = text.find(phrase, start + 1)
    return False


def source_grounding(payload, data, source):
    """Called once with hash-checked bytes; saved alongside deterministic parses."""
    import pymupdf as fitz
    document = fitz.open(stream=data, filetype="pdf") if source.media_type == "application/pdf" else None
    checks = []
    try:
        for row in payload.rows:
            if effective_row_role(row, payload.schema_version) != "product_item":
                continue
            observations = []
            fields = [("description", row.description),
                      *((f"identifier.{index}.raw_value", value) for index, value in enumerate(row.identifiers))]
            for field_name, field in fields:
                if field.raw_value is None:
                    continue
                for ref in field.evidence:
                    page = document[ref.page_number - 1] if document else None
                    page_text = page.get_text("text") if page else ""
                    declared = next(p for p in payload.pages if p.page_number == ref.page_number)
                    region = next(r for r in declared.regions if r.region_reference == ref.region_reference)
                    box = region.bbox
                    rect = page.rect if page else None
                    decoded = page.get_text("text", clip=fitz.Rect(
                        rect.x0 + box.x0 * rect.width, rect.y0 + box.y0 * rect.height,
                        rect.x0 + box.x1 * rect.width, rect.y0 + box.y1 * rect.height)) if page else ""
                    status = ("unavailable" if not normalize(page_text) else
                              "supported" if phrase_supported(field.raw_value, decoded) else "unsupported")
                    observations.append({"field_name": field_name, "page_number": ref.page_number,
                        "region_reference": ref.region_reference, "literal_observed_text": field.raw_value,
                        "literal_source_text": decoded, "normalized_observed_text": normalize(field.raw_value),
                        "normalized_source_text": normalize(decoded), "status": status})
            # No observed product text is unsupported on a text-bearing page.
            if not observations:
                for ref in row.evidence:
                    page = document[ref.page_number - 1] if document else None
                    declared = next(p for p in payload.pages if p.page_number == ref.page_number)
                    box = next(r.bbox for r in declared.regions if r.region_reference == ref.region_reference)
                    decoded = page.get_text("text", clip=fitz.Rect(
                        page.rect.x0 + box.x0 * page.rect.width, page.rect.y0 + box.y0 * page.rect.height,
                        page.rect.x0 + box.x1 * page.rect.width, page.rect.y0 + box.y1 * page.rect.height)) if page else ""
                    observations.append({"field_name": "product_text", "page_number": ref.page_number,
                        "region_reference": ref.region_reference, "literal_observed_text": None,
                        "literal_source_text": decoded, "normalized_observed_text": "",
                        "normalized_source_text": normalize(decoded),
                        "status": "unsupported" if page and normalize(page.get_text("text")) else "unavailable"})
            status = ("unsupported" if any(o["status"] == "unsupported" for o in observations) else
                      "unavailable" if any(o["status"] == "unavailable" for o in observations) else "supported")
            checks.append({"row_id": row.row_id, "source_sha256": source.sha256,
                           "method": METHOD, "status": status, "observations": observations})
    finally:
        if document:
            document.close()
    return checks


def grounding_projection(run, events, source):
    checks = (getattr(run, "parses", None) or {}).get("source_grounding", [])
    result = []
    for check in checks:
        unavailable_pages = {o["page_number"] for o in check["observations"] if o["status"] == "unavailable"}
        confirmations = [e for e in events if e["action"] == UNAVAILABLE_ACTION and
                         e["new_value"].get("source_sha256") == source.sha256]
        missing = sorted(unavailable_pages - {e["new_value"]["page_number"] for e in confirmations})
        reviewed = any(e["action"] == SOURCE_REVIEW_ACTION and e["row_id"] == check["row_id"] and
                       e["new_value"].get("source_sha256") == source.sha256 for e in events)
        result.append({**check, "unsupported_reviewed": reviewed, "unconfirmed_page_numbers": missing})
    return result


def grounding_blockers(checks):
    blockers = []
    if any(c["status"] == "unsupported" and not c["unsupported_reviewed"] for c in checks):
        blockers.append("unsupported_product_text_requires_source_review")
    if any(c["unconfirmed_page_numbers"] for c in checks):
        blockers.append("unavailable_page_text_requires_confirmation")
    return blockers
