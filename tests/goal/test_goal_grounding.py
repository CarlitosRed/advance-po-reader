"""Source text is independent, region-bound and distinct from approval/counts."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from reportlab.pdfgen.canvas import Canvas
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.source_checks import normalize, phrase_supported
from tests.goal.conftest import PRODUCTS, ok, payload, process, product_row, review_body
from tests.goal.test_goal_coverage import count, finish, summary

pytestmark = [pytest.mark.goal, pytest.mark.usefixtures("safety_net_finish_blocking"),
              pytest.mark.parametrize("safety_net_finish_blocking", [True], indirect=True)]


def rows():
    return [product_row(i, code=p["sku"], description=p["description"], quantity="2")
            for i, p in enumerate(PRODUCTS, 1)]


def confirm(desk, result, page=1, **extra):
    return desk.client.post(f"/runs/{result.run['id']}/reviews", json={
        "action": "confirm_unavailable_page_text", "reviewer": "Fictional source reviewer",
        "reason": "Visually inspected this generated source page",
        "evidence_reference": [{"scope": "page", "page_number": page,
                                "source_sha256": result.source["sha256"], **extra}]})


def review_source(desk, result, row):
    return desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(row, "confirm_source_text"))


def from_bytes(desk, products, data, observed_payload=None, media="application/pdf"):
    desk.provider.set_payload(observed_payload or payload(products))
    source = ok(desk.client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        data={"vendor_id": desk.vendor["id"]}, files={"file": ("fictional", data, media)}))
    run = ok(desk.client.post(f"/documents/{source['id']}/runs", headers={"Idempotency-Key": uuid4().hex},
                             json={"provider": "synthetic"}))
    run = ok(desk.client.post(f"/runs/{run['id']}/process"))
    result = SimpleNamespace(run=run, source=source)
    assert ok(desk.client.get(f"/runs/{run['id']}/result"))["attempts"][0]["state"] == "succeeded"
    return result


def pdf_pages(texts, scanned=False):
    output = BytesIO()
    canvas = Canvas(output, pagesize=(900, 1100), invariant=1)
    for value in texts:
        if scanned:
            from reportlab.lib.utils import ImageReader
            canvas.drawImage(ImageReader(Image.new("RGB", (300, 300), "white")), 0, 0, 900, 1100)
        elif value:
            canvas.drawString(45, 858, value)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def test_goal_7_correct_and_invented_text_in_same_real_region(desk, goal_engine):
    printed = rows()[:1]
    result = process(desk, printed)
    good, = result.summary["source_grounding"]
    assert good["status"] == "supported" and good["method"].startswith("pymupdf-region-text")
    observed = deepcopy(printed)
    observed[0]["description"]["raw_value"] = "Fabricated synthetic tower"
    invented = process(desk, printed, observed=observed)
    flag, = invented.summary["source_grounding"]
    assert flag["status"] == "unsupported" and flag["source_sha256"] == invented.source["sha256"]
    comparison = flag["observations"][0]
    assert comparison["literal_observed_text"] == "Fabricated synthetic tower"
    assert PRODUCTS[0]["description"] in comparison["literal_source_text"]
    assert invented.result["extraction"]["rows"][0]["description"] == observed[0]["description"]
    with pytest.raises(IntegrityError), goal_engine.begin() as connection:
        connection.execute(text("UPDATE processing_runs SET parses=NULL WHERE id=:id"), {"id": UUID(invented.run["id"])})


@pytest.mark.parametrize("description,supported", [
    (" synthetic  COBALT\tladder ", True), ("Synthetic cobalt", True),
    ("ynthetic cobalt ladder", False), ("Synthetic cobalt ladd", False),
    ("Synthetic cobalt-ladder", False), ("Synthetic cobalt ladder 99", False)])
def test_goal_7_literal_phrase_normalization_and_boundaries(desk, description, supported):
    printed = rows()[:1]
    observed = deepcopy(printed)
    observed[0]["description"]["raw_value"] = description
    result = process(desk, printed, observed=observed)
    check, = result.summary["source_grounding"]
    assert check["status"] == ("supported" if supported else "unsupported")
    assert result.result["extraction"]["rows"][0]["description"]["raw_value"] == description
    assert check["observations"][0]["normalized_observed_text"] == normalize(description)


def test_goal_7_unicode_casefold_and_whitespace_preserve_punctuation():
    assert phrase_supported("STRASSE\u00a0\t A123", "Straße \n A123")
    assert not phrase_supported("A123", "XA1234")
    assert not phrase_supported("A-123", "A123")


def test_goal_7_wrong_region_and_page_cannot_rescue_text(desk):
    products = rows()
    observed = deepcopy(products)
    observed[0]["description"]["raw_value"] = products[1]["description"]["raw_value"]
    assert process(desk, products, observed=observed).summary["source_grounding"][0]["status"] == "unsupported"
    raw = payload(products[:1])
    raw["pages"].append({"page_number": 2, "state": "complete", "uncertainty": None, "regions": []})
    result = from_bytes(desk, products[:1], pdf_pages(["Other unrelated source text", PRODUCTS[0]["description"]]), raw)
    assert summary(desk, result)["source_grounding"][0]["status"] == "unsupported"
    # A text-bearing page with an empty declared crop is unsupported, not unavailable.
    raw = payload(products[:1])
    raw["pages"][0]["regions"][1]["bbox"].update(y0=.5, y1=.6)
    result = from_bytes(desk, products[:1], pdf_pages([PRODUCTS[0]["description"]]), raw)
    assert summary(desk, result)["source_grounding"][0]["status"] == "unsupported"
    assert confirm(desk, result).json()["error"] == "page_text_is_not_unavailable"


@pytest.mark.parametrize("media", ["application/pdf", "scanned", "image/png", "image/jpeg"])
def test_goal_7_unavailable_preserves_all_tiers_one_confirmation_per_page(desk, media):
    products = [rows()[0], product_row(2, description=PRODUCTS[1]["description"], quantity="1"),
                product_row(3, description="Fictional unmatched item", quantity="1")]
    result = (process(desk, products, media_type=media) if media.startswith("image/") else
              from_bytes(desk, products, pdf_pages([""], scanned=media == "scanned")))
    suggestions = ok(desk.client.get(f"/runs/{result.run['id']}/suggestions"))["suggestions"]
    assert [s["tier"] for s in suggestions] == ["certain", "probable", "uncertain"]
    assert suggestions[0]["suggested_candidate_id"] and suggestions[1]["suggested_candidate_id"] is None
    checks = summary(desk, result)["source_grounding"]
    assert all(c["status"] == "unavailable" and c["unconfirmed_page_numbers"] == [1] for c in checks)
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json={"action":"acknowledge_document",
        "reviewer":"Fictional reviewer", "reason":"Generic acknowledgement",
        "evidence_reference":[{"scope":"document", "source_document_id":result.source["id"], "run_id":result.run["id"], "source_sha256":result.source["sha256"]}]}))
    assert "unavailable_page_text_requires_confirmation" in summary(desk, result)["blockers"]
    event = ok(confirm(desk, result))
    assert event["row_id"] is None and event["reviewer"] and event["created_at"]
    checks = summary(desk, result)["source_grounding"]
    assert all(c["status"] == "unavailable" and c["unconfirmed_page_numbers"] == [] for c in checks)
    assert "unresolved_rows_remain" in summary(desk, result)["blockers"]
    assert "independent_page_product_counts_required" in summary(desk, result)["blockers"]
    ok(count(desk, result, 0))
    assert "page_product_count_mismatch_requires_new_run" in summary(desk, result)["blockers"]
    assert summary(desk, result)["approved_products"] == []
    assert not summary(desk, result)["can_finish_review"]


def test_goal_7_source_review_separate_from_approval_corrections_and_counts(desk):
    printed = rows()[:1]
    observed = deepcopy(printed)
    observed[0]["description"]["raw_value"] = "Fictional invented item"
    result = process(desk, printed, observed=observed)
    ok(count(desk, result, 1))
    candidate = result.suggestions[0]["suggested_candidate_id"]
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(observed[0], "approve", selected_candidate_id=candidate)))
    assert finish(desk, result).json()["error"] == "unsupported_product_text_requires_source_review"
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json={"action":"acknowledge_document",
        "reviewer":"Fictional reviewer", "reason":"Generic acknowledgement",
        "evidence_reference":[{"scope":"document", "source_document_id":result.source["id"], "run_id":result.run["id"], "source_sha256":result.source["sha256"]}]}))
    assert finish(desk, result).json()["error"] == "unsupported_product_text_requires_source_review"
    assert confirm(desk, result).status_code == 422
    ok(review_source(desk, result, observed[0]))
    assert summary(desk, result)["source_grounding"][0]["status"] == "unsupported"
    assert summary(desk, result)["can_finish_review"]
    assert len(summary(desk, result)["approved_products"]) == 1
    # A subsequent correction still invalidates product approval.
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(observed[0], "correct",
        field_name="description", new_value=printed[0]["description"]["raw_value"])))
    assert not summary(desk, result)["can_finish_review"]
    assert summary(desk, result)["approved_products"] == []
    assert ok(desk.client.get(f"/runs/{result.run['id']}/result"))["extraction"]["rows"][0]["description"]["raw_value"] == "Fictional invented item"


def test_goal_7_confirmation_page_hash_tenant_and_new_run_isolation(desk, goal_engine):
    products = rows()[:1]
    raw = payload(products)
    second = deepcopy(raw["rows"][0])
    second["row_id"] = "second-page-item"
    for field in [second, second["description"], second["quantity"], second["unit"], *second["identifiers"]]:
        for ref in field["evidence"]:
            ref["page_number"] = 2
    raw["rows"].append(second)
    page = deepcopy(raw["pages"][0]); page["page_number"] = 2; raw["pages"].append(page)
    result = from_bytes(desk, products, pdf_pages(["", ""]), raw)
    assert confirm(desk, result, source_sha256="0" * 64).status_code == 422
    assert confirm(desk, result, page=3).status_code == 422
    event = ok(confirm(desk, result))
    assert summary(desk, result)["source_grounding"][1]["unconfirmed_page_numbers"] == [2]
    assert review_source(desk, result, products[0]).status_code == 422
    other = ok(desk.client.post("/tenants", json={"name":"Other fictional tenant"}))
    original_tenant = desk.client.headers["X-Tenant-ID"]
    desk.client.headers["X-Tenant-ID"] = other["id"]
    assert confirm(desk, result).status_code == 404
    assert desk.client.get(f"/runs/{result.run['id']}/summary").status_code == 404
    desk.client.headers["X-Tenant-ID"] = original_tenant
    fresh = ok(desk.client.post(f"/documents/{result.source['id']}/runs", headers={"Idempotency-Key":uuid4().hex}, json={"provider":"synthetic"}))
    ok(desk.client.post(f"/runs/{fresh['id']}/process"))
    assert ok(desk.client.get(f"/runs/{fresh['id']}/summary"))["source_grounding"][0]["unconfirmed_page_numbers"] == [1]
    assert ok(desk.client.get(f"/runs/{fresh['id']}/reviews"))["events"] == []
    with pytest.raises(IntegrityError), goal_engine.begin() as connection:
        connection.execute(text("DELETE FROM review_events WHERE id=:id"), {"id":UUID(event["id"])})


def test_goal_7_mixed_unsupported_and_unavailable_needs_both_reviews(desk):
    products = rows()
    raw = payload(products)
    for field in [raw["rows"][1], raw["rows"][1]["description"], raw["rows"][1]["quantity"], raw["rows"][1]["unit"], *raw["rows"][1]["identifiers"]]:
        for ref in field["evidence"]: ref["page_number"] = 2
    page = deepcopy(raw["pages"][0]); page["page_number"] = 2; raw["pages"].append(page)
    result = from_bytes(desk, products, pdf_pages(["Unrelated source text", ""]), raw)
    ok(confirm(desk, result, page=2))
    assert "unsupported_product_text_requires_source_review" in summary(desk, result)["blockers"]
    ok(review_source(desk, result, products[0]))
    assert summary(desk, result)["pending_row_ids"] == [p["row_id"] for p in products]
    assert "independent_page_product_counts_required" in summary(desk, result)["blockers"]


def test_goal_8_zero_product_whole_document_stays_blocked_after_zero_count(desk):
    result = process(desk, rows(), observed=[])
    assert not summary(desk, result)["can_finish_review"]
    ok(count(desk, result, 0))
    value = summary(desk, result)
    assert value["page_coverage"][0]["status"] == "matched"
    assert value["blockers"] == ["unresolved_rows_remain"]
    assert not value["can_finish_review"]
    assert value["approved_products"] == []
    response = finish(desk, result)
    assert response.status_code == 409
    assert response.json()["error"] == "unresolved_rows_remain"
    assert summary(desk, result)["review_state"] != "resolved"



def test_goal_7_unreadable_product_text_is_not_an_unavailable_text_page(desk):
    printed = rows()[:1]
    observed = deepcopy(printed)
    observed[0]["identifiers"] = []
    observed[0]["description"].update(state="unreadable", raw_value=None)
    result = process(desk, printed, observed=observed)
    check, = result.summary["source_grounding"]
    assert check["status"] == "unsupported" and check["observations"][0]["literal_source_text"]
    assert confirm(desk, result).status_code == 422


def test_goal_7_source_confirmation_checks_stored_file_integrity(desk):
    products = rows()[:1]
    result = process(desk, products, media_type="image/png")
    path = desk.settings.storage_directory / result.source["storage_reference"]
    path.write_bytes(b"damaged fictional source")
    assert confirm(desk, result).json()["error"] == "source_integrity_failed"


def test_goal_7_legacy_run_without_grounding_requires_new_processing(desk):
    # Pure projection of preserved pre-B evidence: it cannot silently Finish.
    from backend.review_summary import resolution_blockers
    from backend.contracts import ExtractionPayload
    assert "source_grounding_requires_new_processing_run" in resolution_blockers(
        ExtractionPayload.model_validate(payload(rows())), [], grounding=[], safety_net_finish_blocking=True)
