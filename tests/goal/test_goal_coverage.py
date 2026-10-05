"""Independent counts use real routes, generated sources and append-only audit."""
from copy import deepcopy
from io import BytesIO
import json
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app import create_app
from backend.config import Settings
from backend.contracts import ExtractionPayload
from backend.coverage import page_coverage
from backend.synthetic import fixture_payload
from tests.goal.conftest import ROOT, PRODUCTS, ok, payload, process, product_row, review_body

pytestmark = pytest.mark.goal


def count_body(result, count, page=1, **extra):
    return {"page_number": page, "source_sha256": result.source["sha256"], "product_count": count,
            "source_discrepancy": False, "reviewer": "Fictional count reviewer",
            "reason": "Independently counted the generated source page", **extra}


def count(desk, result, value, **extra):
    return desk.client.post(f"/runs/{result.run['id']}/page-counts", json=count_body(result, value, **extra))


def summary(desk, result):
    return ok(desk.client.get(f"/runs/{result.run['id']}/summary"))


def approve(desk, result, rows):
    for row, suggestion in zip(rows, result.suggestions):
        ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
            row, "approve", selected_candidate_id=suggestion["suggested_candidate_id"])))


def finish(desk, result):
    return desk.client.post(f"/runs/{result.run['id']}/reviews", json={
        "action": "resolve", "reviewer": "Fictional count reviewer", "reason": "All synthetic checks passed"})


def rows():
    return [product_row(i, code=product["sku"], description=product["description"], quantity="2")
            for i, product in enumerate(PRODUCTS, 1)]


def test_goal_8_provider_complete_and_all_approved_still_need_independent_count(desk):
    products = rows()
    result = process(desk, products)
    assert result.run["state"] == "partial"
    approve(desk, result, products)
    assert finish(desk, result).json()["error"] == "independent_page_product_counts_required"
    check, = summary(desk, result)["page_coverage"]
    assert check["status"] == "unavailable" and check["provider_product_count"] == 2
    assert check["independent_product_count"] is None
    original = deepcopy(result.result)
    event = ok(count(desk, result, 2))
    assert event["row_id"] is None and event["reviewer"] and event["created_at"]
    assert event["evidence_reference"] == [{"scope": "page", "page_number": 1, "source_sha256": result.source["sha256"]}]
    assert summary(desk, result)["page_coverage"][0]["status"] == "matched"
    assert summary(desk, result)["can_finish_review"]
    assert ok(desk.client.get(f"/runs/{result.run['id']}"))["state"] == "completed"
    ok(finish(desk, result))
    assert count(desk, result, 2).status_code == 409
    assert ok(desk.client.get(f"/runs/{result.run['id']}/result")) == original


def test_goal_8_count_never_approves_a_product_or_creates_catalog_entry(desk):
    result = process(desk, rows())
    before = ok(desk.client.get("/catalog", params={"vendor_id": desk.vendor["id"]}))
    ok(count(desk, result, 2))
    after = summary(desk, result)
    assert after["approved_products"] == [] and after["pending_row_ids"] == ["line-1", "line-2"]
    assert finish(desk, result).json()["error"] == "unresolved_rows_remain"
    assert ok(desk.client.get("/catalog", params={"vendor_id": desk.vendor["id"]})) == before


@pytest.mark.parametrize("independent", [0, 1, 3])
def test_goal_8_zero_and_other_mismatches_survive_exclusion_and_document_ack(desk, independent):
    products = rows()
    result = process(desk, products)
    for row in products:
        ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(row, "not_a_product")))
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json={
        "action": "acknowledge_document", "reviewer": "Fictional reviewer", "reason": "Source checked",
        "evidence_reference": [{"page_number": 1, "region_reference": "header"}]}))
    event = ok(count(desk, result, independent))
    assert event["new_value"]["status"] == "mismatch"
    check = summary(desk, result)["page_coverage"][0]
    assert check["provider_product_count"] == 2 and check["independent_product_count"] == independent
    assert check["remedy"] == "new_source_bound_run"
    assert finish(desk, result).json()["error"] == "page_product_count_mismatch_requires_new_run"
    assert ok(desk.client.get(f"/runs/{result.run['id']}"))["state"] == "partial"


def test_goal_8_mistaken_count_correction_is_explicit_append_only_and_ordered(desk, goal_engine):
    result = process(desk, rows())
    wrong = ok(count(desk, result, 3))
    assert count(desk, result, 2).status_code == 409
    corrected = ok(count(desk, result, 2, corrects_event_id=wrong["id"], correction_kind="independent_count_error",
        reason="My prior count included the heading; rechecked the source product items"))
    assert corrected["old_value"] == wrong["new_value"]
    assert corrected["event_sequence"] == wrong["event_sequence"] + 1
    assert summary(desk, result)["page_coverage"][0]["status"] == "matched"
    # A later correction to zero is a mismatch and returns processing to partial.
    ok(count(desk, result, 0, corrects_event_id=corrected["id"], correction_kind="independent_count_error"))
    assert summary(desk, result)["page_coverage"][0]["status"] == "mismatch"
    assert count(desk, result, 2, corrects_event_id=wrong["id"], correction_kind="independent_count_error").status_code == 409
    events = ok(desk.client.get(f"/runs/{result.run['id']}/reviews"))["events"]
    assert len(events) == 3
    for saved, returned in zip(events, (wrong, corrected)):
        assert datetime.fromisoformat(saved["created_at"]) == datetime.fromisoformat(returned["created_at"])
        assert {k: v for k, v in saved.items() if k != "created_at"} == {k: v for k, v in returned.items() if k != "created_at"}
    for statement in ("UPDATE review_events SET reason='changed' WHERE id=:id", "DELETE FROM review_events WHERE id=:id"):
        with pytest.raises(IntegrityError), goal_engine.begin() as connection:
            connection.execute(text(statement), {"id": UUID(wrong["id"])})


def test_goal_8_source_discrepancy_latches_old_run_new_run_needs_fresh_checks(desk):
    products = rows()
    old = process(desk, products, observed=products[:1])
    approve(desk, old, products[:1])
    event = ok(count(desk, old, 2, source_discrepancy=True))
    assert count(desk, old, 1, corrects_event_id=event["id"], correction_kind="independent_count_error").status_code == 409
    desk.provider.set_payload(payload(products))
    new = ok(desk.client.post(f"/documents/{old.source['id']}/runs", json={"provider": "synthetic"},
        headers={"Idempotency-Key": uuid4().hex}))
    ok(desk.client.post(f"/runs/{new['id']}/process"))
    fresh = ok(desk.client.get(f"/runs/{new['id']}/summary"))
    assert fresh["page_coverage"][0]["status"] == "unavailable"
    assert fresh["approved_products"] == [] and len(fresh["pending_row_ids"]) == 2
    assert ok(desk.client.get(f"/runs/{new['id']}/reviews"))["events"] == []
    assert not summary(desk, old)["can_finish_review"]
    assert summary(desk, old)["page_coverage"][0]["source_discrepancy"]


@pytest.mark.parametrize("extra", [{"product_count": -1}, {"product_count": True}, {"product_count": "2"},
    {"product_count": 2.0}, {"page_number": True}, {"page_number": 0}, {"source_discrepancy": "false"},
    {"reviewer": " "}, {"reason": " "}, {"corrects_event_id": str(uuid4())}])
def test_goal_8_count_request_rejects_coercions_unattributed_and_incomplete_corrections(desk, extra):
    result = process(desk, rows())
    response = desk.client.post(f"/runs/{result.run['id']}/page-counts", json=count_body(result, 2, **extra))
    assert response.status_code == 422
    assert summary(desk, result)["page_coverage"][0]["status"] == "unavailable"


def test_goal_10_counts_reject_foreign_tenant_hash_page_and_run(desk):
    result = process(desk, rows())
    assert count(desk, result, 2, source_sha256="f" * 64).status_code == 422
    assert count(desk, result, 2, page=2).status_code == 422
    first = ok(count(desk, result, 2))
    other = process(desk, rows())
    assert other.source["id"] == result.source["id"]
    assert count(desk, other, 2, corrects_event_id=first["id"], correction_kind="independent_count_error").status_code == 422
    tenant = ok(desk.client.post("/tenants", json={"name": "Fictional isolated count tenant " + uuid4().hex}))
    desk.client.headers["X-Tenant-ID"] = tenant["id"]
    assert count(desk, result, 2).status_code == 404
    assert desk.client.get(f"/runs/{result.run['id']}/summary").status_code == 404


def test_goal_8_every_page_including_an_empty_page_needs_its_own_count(desk):
    from types import SimpleNamespace
    products = rows()
    data = BytesIO()
    canvas = Canvas(data, pagesize=(900, 1100), invariant=1)
    canvas.drawString(45, 850, "GOAL-001 Synthetic cobalt ladder; GOAL-002 Synthetic vermilion bracket")
    canvas.showPage()
    canvas.drawString(45, 850, "Fictional empty product page: delivery notes only")
    canvas.showPage()
    canvas.save()
    value = payload(products)
    value["pages"].append({"page_number": 2, "state": "complete", "uncertainty": None, "regions": []})
    desk.provider.set_payload(value)
    source = ok(desk.client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        data={"vendor_id": desk.vendor["id"]}, files={"file": ("fictional", data.getvalue(), "application/pdf")}))
    run = ok(desk.client.post(f"/documents/{source['id']}/runs", json={"provider": "synthetic"},
        headers={"Idempotency-Key": uuid4().hex}))
    ok(desk.client.post(f"/runs/{run['id']}/process"))
    result = SimpleNamespace(run=run, source=source)
    ok(count(desk, result, 2))
    assert [check["status"] for check in summary(desk, result)["page_coverage"]] == ["matched", "unavailable"]
    second = ok(count(desk, result, 0, page=2))
    assert second["new_value"]["status"] == "matched"
    assert [check["independent_product_count"] for check in summary(desk, result)["page_coverage"]] == [2, 0]


def test_goal_8_continuation_and_document_details_do_not_inflate_provider_count():
    from types import SimpleNamespace
    source = SimpleNamespace(page_count=1, sha256="a" * 64)
    value = fixture_payload("continuation")
    check, = page_coverage(value, [], source)
    assert len(value.rows) > 2 and check["provider_product_count"] == 2


def test_goal_10_generated_openapi_snapshot_matches_application():
    settings = Settings(_env_file=None, openai_api_key=None, live_processing_enabled=False)
    app = create_app(settings)
    assert json.loads((ROOT / "contracts/local-backend-openapi.json").read_text(encoding="utf-8")) == app.openapi()
