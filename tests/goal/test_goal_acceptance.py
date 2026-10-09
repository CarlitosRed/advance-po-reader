"""T-007: measure product behavior without fixing the application.

Passing extraction checks mean fixed observations survived the real workflow;
they are deliberately not a measurement of a vision model's accuracy.
"""
from copy import deepcopy
from io import BytesIO

from PIL import Image
import pytest

from conftest import PRODUCTS, ok, process, product_row, review_body

pytestmark = pytest.mark.goal


def gap(reason):
    return pytest.mark.xfail(reason=reason, strict=True, raises=AssertionError)


def two_products():
    return [product_row(i, code=p["sku"], description=p["description"], quantity=q)
            for i, (p, q) in enumerate(zip(PRODUCTS, ("002.00", "3")), 1)]


def exact(desk):
    rows = two_products()
    return rows, process(desk, rows)


def unknown(desk):
    rows = [two_products()[0], product_row(2, description="Unclassified synthetic accessory", kind="unknown")]
    return rows, process(desk, rows)


def tier(suggestion):
    # Inspect the public response; never derive a tier from test-side matching rules.
    return str(suggestion.get("tier", suggestion["outcome"])).casefold()


def test_goal_1_separate_code_column_preserves_every_product_and_raw_quantity(desk):
    rows, result = exact(desk)
    extracted = result.result["extraction"]["rows"]
    assert len(extracted) == 2
    assert [(r["identifiers"][0]["raw_value"], r["description"]["raw_value"], r["quantity"]["raw_value"])
            for r in extracted] == [("GOAL-001", "Synthetic cobalt ladder", "002.00"),
                                    ("GOAL-002", "Synthetic vermilion bracket", "3")]
    assert {s["row_id"] for s in result.suggestions} == {r["row_id"] for r in rows}
    assert all(s["method"] == "exact" for s in result.suggestions)
    assert result.summary["approved_products"] == []


def test_goal_2_code_inside_description_is_found_without_code_column(desk):
    rows = [product_row(1, description="Synthetic cobalt ladder, code GOAL-001", quantity="2")]
    result = process(desk, rows, code_column=False)
    assert result.result["extraction"]["rows"][0]["identifiers"] == []
    suggestion, = result.suggestions
    assert suggestion["method"] == "description_code_hint"
    assert [c["sku"] for c in suggestion["candidates"]] == ["GOAL-001"]
    assert "GOAL-001" in str(suggestion["evidence"])


def test_goal_3_nonproducts_never_match_and_are_listed_as_document_details(desk):
    rows = [two_products()[0]]
    # Even exact catalog code text in nonproduct details must never enter matching.
    details = [("note", "Address: synthetic receiving desk GOAL-001"),
               ("total", "Order total GOAL-001"), ("note", "Comment: check GOAL-001"),
               ("note", "Header: Code Description Quantity GOAL-001"),
               ("note", "Footer: synthetic page GOAL-001"), ("charge", "Freight charge"),
               ("tax", "Tax"), ("subtotal", "Subtotal")]
    rows += [product_row(i, code="GOAL-001", description=text, kind=kind)
             for i, (kind, text) in enumerate(details, 2)]
    result = process(desk, rows)
    assert [s["row_id"] for s in result.suggestions] == ["line-1"]
    assert result.summary["pending_row_ids"] == ["line-1"]
    assert {r["row_id"] for r in result.summary["document_details"]} == {r["row_id"] for r in rows[1:]}
    assert result.summary["approved_products"] == []
    for row in rows[1:]:
        response = desk.client.post(f"/runs/{result.run['id']}/reviews",
                                    json=review_body(row, "approve", selected_candidate_id=desk.products[0]["candidate_id"]))
        assert response.status_code == 422


def test_goal_4_exact_code_preselected_but_needs_explicit_human_approval(desk):
    rows, result = exact(desk)
    suggestion = result.suggestions[0]
    assert suggestion["outcome"] == "suggested"
    assert suggestion["suggested_candidate_id"] == desk.products[0]["candidate_id"]
    assert "line-1" in result.summary["pending_row_ids"]
    assert result.summary["approved_products"] == []
    events = ok(desk.client.get(f"/runs/{result.run['id']}/reviews"))["events"]
    assert events == []
    blocked = desk.client.post(f"/runs/{result.run['id']}/reviews", json={
        "action": "resolve", "reviewer": "Fictional reviewer", "reason": "Attempt before approval"})
    assert blocked.status_code == 409
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[0], "approve", selected_candidate_id=suggestion["suggested_candidate_id"])))
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert [r["row_id"] for r in summary["approved_products"]] == ["line-1"]
    assert summary["review_event_count"] == 1


def test_goal_4_exact_code_is_in_certain_tier(desk):
    _, result = exact(desk)
    assert tier(result.suggestions[0]) == "certain", result.suggestions[0]


def test_goal_5_description_only_match_finds_scoped_product_and_stays_pending(desk):
    rows = [product_row(1, description="Synthetic cobalt ladder", quantity="2")]
    result = process(desk, rows, code_column=False)
    suggestion, = result.suggestions
    assert suggestion["method"] == "trigram"
    assert [c["sku"] for c in suggestion["candidates"]] == ["GOAL-001"]
    assert result.summary["approved_products"] == []
    assert result.summary["pending_row_ids"] == ["line-1"]


def test_goal_5_description_only_match_is_in_probable_tier(desk):
    rows = [product_row(1, description="Synthetic cobalt ladder", quantity="2")]
    result = process(desk, rows, code_column=False)
    assert tier(result.suggestions[0]) == "probable", result.suggestions[0]


def test_goal_6_unknown_line_keeps_source_snippet_and_pending_review(desk):
    rows, result = unknown(desk)
    assert result.run["state"] == "partial"
    assert "line-2" in result.summary["pending_row_ids"]
    assert result.result["extraction"]["rows"][1] == rows[1] | {
        "item_group_id": None, "row_role": None, "continuation_of": None}
    crop = desk.client.get(f"/runs/{result.run['id']}/rows/line-2/preview")
    assert crop.status_code == 200
    assert crop.content.startswith(b"\x89PNG")
    assert crop.headers["cache-control"] == "no-store"
    with Image.open(BytesIO(crop.content)) as image:
        assert image.width > 0 and image.height > 0
        assert image.convert("L").getextrema()[0] < 255, "snippet must retain printed ink"


def test_goal_6_unknown_line_is_in_uncertain_tier(desk):
    _, result = unknown(desk)
    rows = {s["row_id"]: s for s in result.suggestions}
    assert "line-2" in rows, "unknown line has no public tier-bearing suggestion"
    assert tier(rows["line-2"]) == "uncertain"


def test_goal_6_unknown_line_accepts_answer_product_x(desk):
    rows, result = unknown(desk)
    candidate = desk.products[0]["candidate_id"]
    proposal = desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "propose_candidate", candidate_ids=[candidate]))
    assert proposal.status_code == 201, proposal.text
    approved = desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "approve", selected_candidate_id=candidate))
    assert approved.status_code == 201, approved.text
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert any(r["row_id"] == "line-2" and r["candidate"]["candidate_id"] == candidate
               for r in summary["approved_products"])


def test_goal_6_unknown_line_accepts_new_product_added_to_catalog(desk):
    rows, result = unknown(desk)
    new = ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"], "products": [
        {"sku": "GOAL-NEW-003", "description": rows[1]["description"]["raw_value"]}]}))["products"][0]
    catalog = ok(desk.client.get("/catalog", params={"vendor_id": desk.vendor["id"]}))["products"]
    assert any(p["sku"] == "GOAL-NEW-003" for p in catalog)
    proposal = desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "propose_candidate", candidate_ids=[new["candidate_id"]]))
    assert proposal.status_code == 201, proposal.text
    approved = desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "approve", selected_candidate_id=new["candidate_id"]))
    assert approved.status_code == 201, approved.text
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert any(r["row_id"] == "line-2" and r["candidate"]["sku"] == "GOAL-NEW-003"
               for r in summary["approved_products"])


def test_goal_6_acknowledgement_needs_explicit_exclusion_answer(desk):
    rows, result = unknown(desk)
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(rows[1], "acknowledge")))
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert "line-2" in summary["pending_row_ids"]
    assert not summary["can_finish_review"]
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(rows[1], "not_a_product")))
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert "line-2" not in summary["pending_row_ids"]
    assert summary["approved_products"] == []
    assert any(r["row_id"] == "line-2" for r in summary["excluded_rows"])
    original = ok(desk.client.get(f"/runs/{result.run['id']}/result"))["extraction"]["rows"][1]
    assert original["row_kind"] == "unknown", "original extraction must remain immutable"


def test_goal_6_unknown_line_accepts_explicit_not_a_product_answer(desk):
    rows, result = unknown(desk)
    response = desk.client.post(f"/runs/{result.run['id']}/reviews",
                                json=review_body(rows[1], "not_product"))
    assert response.status_code == 201, response.text
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert any(r["row_id"] == "line-2" and r["decision"] == "not_product"
               for r in summary["excluded_rows"])


@gap("backend/contracts.py only validates page/region references; service.process_run never grounds observed products against source pixels/text")
def test_goal_7_invented_line_in_declared_region_is_rejected_or_flagged(desk):
    rows = two_products()
    baseline = process(desk, rows)
    if baseline.run["state"] != "completed":
        pytest.fail("positive grounding baseline must complete before testing invented output")
    invented = product_row(3, code="GOAL-GHOST-999", description="Invented synthetic ghost product", quantity="99")
    # Cite a real printed row's region: graph validity must not count as source grounding.
    invented["row_id"] = "invented-line"
    for references in [invented["evidence"], *(invented[name]["evidence"]
                       for name in ("description", "quantity", "unit")), invented["identifiers"][0]["evidence"]]:
        references[0]["region_reference"] = "line-1"
    result = process(desk, rows, observed=[*deepcopy(rows), invented])
    if result.result["attempts"][0]["state"] != "succeeded":
        pytest.fail("fake provider must succeed to measure source grounding")
    extracted = result.result["extraction"]
    flagged = extracted and (extracted["warnings"] or any(
        row["row_id"] == "invented-line" and row["uncertainty"] for row in extracted["rows"]))
    assert result.run["state"] in {"failed", "partial"} or flagged, result.run


@gap("backend/service.py considers a provider-declared complete page complete if any product remains; no independent source product-line count check")
def test_goal_8_missing_product_line_triggers_completeness_check(desk):
    rows = two_products()
    # The generated page still contains both products; JSON silently omits line-2.
    result = process(desk, rows, observed=[deepcopy(rows[0])])
    assert result.run["state"] in {"failed", "partial"}, result.run
    assert result.run["outcome_code"] != "ready_for_human_review"


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg"], ids=["PNG", "JPG"])
def test_goal_9_photo_uses_same_upload_process_match_review_and_snippet_path_as_pdf(desk, media_type):
    rows = two_products()
    pdf = process(desk, rows)
    photo = process(desk, rows, media_type=media_type)
    assert photo.source["media_type"] == media_type
    assert photo.result["extraction"] == pdf.result["extraction"]
    assert photo.run["state"] == pdf.run["state"]
    assert [(s["row_id"], s["method"], [c["sku"] for c in s["candidates"]]) for s in photo.suggestions] == [
        (s["row_id"], s["method"], [c["sku"] for c in s["candidates"]]) for s in pdf.suggestions]
    assert photo.summary["pending_row_ids"] == pdf.summary["pending_row_ids"]
    assert photo.summary["approved_products"] == []
    crop = desk.client.get(f"/runs/{photo.run['id']}/rows/line-1/preview")
    assert crop.status_code == 200 and crop.content.startswith(b"\x89PNG")
    selected = photo.suggestions[0]["suggested_candidate_id"]
    ok(desk.client.post(f"/runs/{photo.run['id']}/reviews", json=review_body(
        rows[0], "approve", selected_candidate_id=selected)))
    reviewed = ok(desk.client.get(f"/runs/{photo.run['id']}/summary"))
    assert [r["row_id"] for r in reviewed["approved_products"]] == ["line-1"]
    events = ok(desk.client.get(f"/runs/{photo.run['id']}/reviews"))["events"]
    assert len(events) == 1 and events[0]["action"] == "approve"


def test_goal_10_tenant_catalogs_candidates_reviews_and_sources_stay_isolated(desk):
    rows = two_products()
    tenant_a = desk.tenant["id"]
    vendor_a = desk.vendor["id"]
    run_a = process(desk, rows)
    b = ok(desk.client.post("/tenants", json={"name": "Synthetic independent tenant B"}))
    desk.client.headers["X-Tenant-ID"] = b["id"]
    vendor_b = ok(desk.client.post("/vendors", json={"name": "Synthetic independent vendor B"}))
    b_product = ok(desk.client.post("/catalog/import", json={"vendor_id": vendor_b["id"], "products": [
        {"sku": "GOAL-001", "description": "Tenant B entirely different product"},
        {"sku": "B-ONLY-999", "description": "Synthetic cobalt ladder"}]}))["products"][0]
    desk.vendor = vendor_b
    run_b = process(desk, rows)
    assert run_b.suggestions[0]["suggested_candidate_id"] == b_product["candidate_id"]
    assert not {c["candidate_id"] for s in run_b.suggestions for c in s["candidates"]} & {
        p["candidate_id"] for p in desk.products}
    assert desk.client.get(f"/runs/{run_a.run['id']}/suggestions").status_code == 404
    assert desk.client.get(f"/documents/{run_a.source['id']}/content").status_code == 404
    foreign = desk.client.post(f"/runs/{run_b.run['id']}/reviews", json=review_body(
        rows[0], "propose_candidate", candidate_ids=[desk.products[0]["candidate_id"]]))
    assert foreign.status_code == 422
    desk.client.headers["X-Tenant-ID"] = tenant_a
    desk.vendor = {"id": vendor_a}
    b_only = process(desk, [product_row(1, code="B-ONLY-999", description="Unique unmapped component", quantity="1")])
    assert b_only.suggestions[0]["candidates"] == []
    assert desk.client.get("/catalog", params={"vendor_id": vendor_b["id"]}).status_code == 404
