"""Bounded labeled hints and explicit acknowledgment scopes through real routes."""
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.catalog import ProductInput, import_products, pg_trgm_available, retrieve_candidates
from backend.models import Vendor, CatalogNamespace, CatalogSourceProduct
from backend.pools import configure_pool
from gate_a.models import Tenant
from tests.goal.conftest import PRODUCTS, ok, payload, process, product_row, review_body, source_bytes
from tests.goal.test_goal_coverage import count, finish, summary
from tests.goal.test_goal_grounding import from_bytes, pdf_pages, confirm

pytestmark = [pytest.mark.goal, pytest.mark.usefixtures("safety_net_finish_blocking"),
              pytest.mark.parametrize("safety_net_finish_blocking", [True], indirect=True)]


def document_ref(result, **extra):
    return {"scope": "document", "source_document_id": result.source["id"],
            "run_id": result.run["id"], "source_sha256": result.source["sha256"], **extra}


def page_ref(result, page=1, **extra):
    return {"scope": "page", "page_number": page, "source_sha256": result.source["sha256"], **extra}


def ack(desk, result, action, refs):
    return desk.client.post(f"/runs/{result.run['id']}/reviews", json={"action": action,
        "reviewer": "Fictional scope reviewer", "reason": "Inspected generated source uncertainty",
        "evidence_reference": refs})


@pytest.mark.parametrize("trgm", [True, False])
@pytest.mark.parametrize("code,label", [("A123", "code: "), ("2026", "SKU #"), ("A", "item id="),
    ("AB", "product code "), ("001", "item code: "), ("2026/10/05", "sku "), ("20261005", "code ")])
def test_goal_2_labeled_literal_codes_with_and_without_actual_pg_trgm(goal_engine, trgm, code, label):
    # DROP is transactional and confined to the harness-owned database; rollback
    # restores the extension and indexes before another test can use this engine.
    with goal_engine.connect() as connection, connection.begin() as transaction:
        if not trgm:
            connection.execute(text("DROP EXTENSION IF EXISTS pg_trgm CASCADE"))
        with Session(bind=connection) as session:
            assert pg_trgm_available(session) is trgm
            tenant = Tenant(name="Fictional labeled-code scope")
            session.add(tenant); session.flush()
            vendor = Vendor(tenant_id=tenant.id, name="Fictional labeled-code vendor")
            session.add(vendor); session.flush()
            import_products(session, tenant.id, vendor.id, [ProductInput(sku=code, description="Fictional distinct catalog item")])
            description = "Fictional fixture " + label + code
            result = retrieve_candidates(session, tenant.id, vendor.id, [], description, safety_net_finish_blocking=True)
            assert result["method"] == "description_labeled_code_hint"
            assert [c["sku"] for c in result["candidates"]] == [code]
            assert result["evidence"][0]["raw_token"] == code
            assert result["evidence"][0]["raw_label"] == label
            assert result["outcome"] == "suggested" and "human approval" in result["reason"]
        transaction.rollback()


@pytest.mark.parametrize("description", ["2026", "2026/10/05", "20261005", "Quantity 2026", "Qty 4516", "$4516", "4516 EA", "AB", "A123"])
def test_goal_2_unlabeled_dates_quantities_currency_and_short_words_stay_conservative(desk, description):
    codes = ["2026", "2026/10/05", "20261005", "4516", "AB", "A123"]
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"],
        "products": [{"sku": c, "description": "Fictional unrelated catalog object"} for c in codes]}))
    row = product_row(1, description=description, quantity="2")
    result = process(desk, [row])
    assert result.suggestions[0]["candidates"] == []
    assert result.result["extraction"]["rows"][0]["description"]["raw_value"] == description


@pytest.mark.parametrize("code", ["A123", "2026", "AB", "2026/10/05"])
def test_goal_5_labeled_hint_preserves_observations_and_requires_approval(desk, code):
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"],
        "products": [{"sku": code, "description": "Fictional unrelated catalog object"}]}))
    row = product_row(1, description="Fictional object, code: " + code, quantity="2")
    result = process(desk, [row])
    suggestion, = result.suggestions
    assert suggestion["tier"] == "probable" and suggestion["suggested_candidate_id"] is None
    assert suggestion["approval_status"] == "needs_approval"
    assert result.summary["approved_products"] == [] and finish(desk, result).status_code == 409
    saved = result.result["extraction"]["rows"][0]
    assert saved["identifiers"] == [] and saved["description"] == row["description"]
    ok(count(desk, result, 1))
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(row, "approve",
        selected_candidate_id=suggestion["candidates"][0]["candidate_id"])))
    assert summary(desk, result)["can_finish_review"]
    # A's code-column conflict veto survives a newly discoverable literal code.
    conflicted = deepcopy(row)
    conflicted["identifiers"] = product_row(1, code="GOAL-001")["identifiers"]
    other = process(desk, [conflicted])
    assert other.suggestions[0]["tier"] == "uncertain"
    assert other.suggestions[0]["suggested_candidate_id"] is None


def test_goal_10_labeled_hints_are_tenant_vendor_pool_scoped_and_bounded(goal_engine):
    with goal_engine.connect() as connection, connection.begin() as transaction, Session(bind=connection) as session:
        tenant = Tenant(name="Fictional scoped hints"); foreign = Tenant(name="Fictional foreign hints")
        session.add_all([tenant, foreign]); session.flush()
        vendors = [Vendor(tenant_id=t.id, name="Fictional hints vendor " + str(i)) for i, t in enumerate((tenant, tenant, foreign))]
        session.add_all(vendors); session.flush()
        namespace = CatalogNamespace(tenant_id=tenant.id, vendor_id=vendors[0].id,
            source_catalog_id="fictional-hints", source_filename="fictional.xlsx", workbook_sha256="a" * 64,
            database_sha256="b" * 64, source_sheet="Products", adapter_version="fictional-test-v1",
            assigned_by="Fictional reviewer", synthetic=False)
        session.add(namespace); session.flush()
        pool = configure_pool(session, tenant.id, "Fictional hint pool", [namespace.id], make_default=True)
        for vendor in vendors:
            products = import_products(session, vendor.tenant_id, vendor.id,
                [ProductInput(sku=f"A{i}", description="Fictional bounded item") for i in range(12)])
            if vendor == vendors[0]:
                # A11 is same vendor but absent from the selected namespace.
                for product in products[:11]:
                    session.add(CatalogSourceProduct(tenant_id=tenant.id, vendor_id=vendor.id,
                        namespace_id=namespace.id, product_id=UUID(product["candidate_id"]), source_row_number=int(product["sku"][1:]) + 1, raw_fields={"sku": product["sku"]}, attributes=[], detail_sections=[]))
        session.flush()
        result = retrieve_candidates(session, tenant.id, None, [],
            "; ".join(f"code A{i}" for i in range(12)), limit=3, vendor_ids=[vendors[0].id], pool_id=pool.id, safety_net_finish_blocking=True)
        assert result["outcome"] == "ambiguous" and len(result["candidates"]) == 3
        assert len(result["evidence"]) == 10
        assert all(c["origin_vendor_id"] == str(vendors[0].id) and c["namespace_id"] == str(namespace.id)
                   for c in result["candidates"])
        assert retrieve_candidates(session, tenant.id, None, [], "code A11",
            vendor_ids=[vendors[0].id], pool_id=pool.id, safety_net_finish_blocking=True)["candidates"] == []
        transaction.rollback()


def partial_result(desk, *, source_mode="text", no_regions=False):
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2")]
    raw = payload(rows)
    raw["pages"][0].update(state="partial", uncertainty="Fictional page uncertainty")
    raw["warnings"] = ["Fictional document warning"]
    if no_regions:
        raw["pages"].append({"page_number": 2, "state": "partial", "regions": [], "uncertainty": "Fictional blank partial page"})
        data = pdf_pages(["GOAL-001 Synthetic cobalt ladder", ""])
    else:
        data = source_bytes(rows)
    if source_mode == "unsupported":
        raw["rows"][0]["description"]["raw_value"] = "Fictional invented object"
    elif source_mode == "unavailable":
        data = pdf_pages([""])
    return rows, from_bytes(desk, rows, data, raw)


@pytest.mark.parametrize("no_regions", [False, True])
def test_goal_9_explicit_page_and_document_acknowledgments_preserve_row_and_count_blockers(desk, no_regions):
    rows, result = partial_result(desk, no_regions=no_regions)
    original = ok(desk.client.get(f"/runs/{result.run['id']}/result"))
    event = ok(ack(desk, result, "acknowledge_page", [page_ref(result)]))
    assert event["evidence_reference"] == [page_ref(result)] and event["row_id"] is None
    if no_regions:
        assert "partial_pages_require_explicit_acknowledgement" in summary(desk, result)["blockers"]
        ok(ack(desk, result, "acknowledge_page", [page_ref(result, 2)]))
    event = ok(ack(desk, result, "acknowledge_document", [document_ref(result)]))
    assert event["evidence_reference"] == [document_ref(result)] and event["reviewer"] and event["created_at"]
    assert summary(desk, result)["blockers"] == ["unresolved_rows_remain", "independent_page_product_counts_required"]
    suggestion = ok(desk.client.get(f"/runs/{result.run['id']}/suggestions"))["suggestions"][0]
    body = review_body(rows[0], "approve", selected_candidate_id=suggestion["suggested_candidate_id"])
    body["evidence_reference"][0] = {**body["evidence_reference"][0], "scope": "region"}
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=body))
    ok(count(desk, result, 1))
    if no_regions:
        assert not summary(desk, result)["can_finish_review"]
        ok(count(desk, result, 0, page=2))
    assert summary(desk, result)["can_finish_review"]
    ok(finish(desk, result))
    assert ok(desk.client.get(f"/runs/{result.run['id']}/result")) == original


@pytest.mark.parametrize("source_mode", ["unsupported", "unavailable"])
def test_goal_7_generic_scoped_acknowledgments_do_not_clear_grounding_or_mismatched_counts(desk, source_mode):
    rows, result = partial_result(desk, source_mode=source_mode)
    ok(ack(desk, result, "acknowledge_page", [page_ref(result)]))
    ok(ack(desk, result, "acknowledge_document", [document_ref(result)]))
    ok(count(desk, result, 0))
    blockers = summary(desk, result)["blockers"]
    assert "unresolved_rows_remain" in blockers and "page_product_count_mismatch_requires_new_run" in blockers
    assert ("unsupported_product_text_requires_source_review" if source_mode == "unsupported" else
            "unavailable_page_text_requires_confirmation") in blockers
    if source_mode == "unavailable":
        ok(confirm(desk, result))
        assert "page_product_count_mismatch_requires_new_run" in summary(desk, result)["blockers"]


@pytest.mark.parametrize("bad", ["null_region", "region_for_page", "document_for_page", "wrong_hash", "outside_page",
    "bool_page", "multiple_pages", "wrong_document", "wrong_run", "page_for_document", "page_for_row", "other_row"])
def test_goal_10_acknowledgment_scopes_reject_invalid_or_cross_source_evidence(desk, bad):
    rows, result = partial_result(desk)
    action, refs = "acknowledge_page", [page_ref(result)]
    if bad == "null_region": refs = [{"page_number": 1, "region_reference": None}]
    elif bad == "region_for_page": refs = rows[0]["evidence"]
    elif bad == "document_for_page": refs = [document_ref(result)]
    elif bad == "wrong_hash": refs = [page_ref(result, source_sha256="f" * 64)]
    elif bad == "outside_page": refs = [page_ref(result, 2)]
    elif bad == "bool_page": refs = [page_ref(result, True)]
    elif bad == "multiple_pages": refs *= 2
    elif bad in {"wrong_document", "wrong_run", "page_for_document"}:
        action = "acknowledge_document"
        refs = [document_ref(result, **({"source_document_id": str(uuid4())} if bad == "wrong_document" else
            {"run_id": str(uuid4())} if bad == "wrong_run" else {}))] if bad != "page_for_document" else refs
    elif bad == "other_row": refs = [{"scope": "region", "page_number": 1, "region_reference": "header"}]
    if bad in {"page_for_row", "other_row"}:
        response = desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(rows[0], "not_a_product", evidence_reference=refs))
    else:
        response = ack(desk, result, action, refs)
    assert response.status_code == 422
    assert ok(desk.client.get(f"/runs/{result.run['id']}/reviews"))["events"] == []
    assert not summary(desk, result)["can_finish_review"]


def test_goal_10_acknowledgments_are_tenant_and_run_bound(desk):
    _, old = partial_result(desk)
    _, new = partial_result(desk)
    assert old.source["id"] == new.source["id"]
    ok(ack(desk, old, "acknowledge_page", [page_ref(old)]))
    ok(ack(desk, old, "acknowledge_document", [document_ref(old)]))
    assert ack(desk, new, "acknowledge_document", [document_ref(old)]).status_code == 422
    assert "partial_pages_require_explicit_acknowledgement" in summary(desk, new)["blockers"]
    assert "document_warnings_require_explicit_acknowledgement" in summary(desk, new)["blockers"]
    tenant = ok(desk.client.post("/tenants", json={"name": "Fictional foreign acknowledgment tenant"}))
    desk.client.headers["X-Tenant-ID"] = tenant["id"]
    assert ack(desk, old, "acknowledge_page", [page_ref(old)]).status_code == 404
    assert ack(desk, old, "acknowledge_document", [document_ref(old)]).status_code == 404
