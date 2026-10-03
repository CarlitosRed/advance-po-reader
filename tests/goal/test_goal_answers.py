from copy import deepcopy
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from backend.models import CatalogProduct, CatalogNamespace, CatalogPool, CatalogPoolMember
from conftest import ROOT, PRODUCTS, ok, process, product_row, review_body

pytestmark = pytest.mark.goal


def unknown(desk, **kwargs):
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2"),
            product_row(2, description="Synthetic new accessory", quantity="1", kind="unknown")]
    return rows, process(desk, rows, **kwargs)


def new_body(row, **kwargs):
    return review_body(row, "new_product", product={"sku": "GOAL-REVIEW-003", "description": "Synthetic new accessory"},
                       decision_key=uuid4().hex, **kwargs)


def test_goal_6_new_migration_upgrade_downgrade_upgrade(goal_engine):
    name = "gate_a_test_backend_goal_migration_" + uuid4().hex
    admin = create_engine(goal_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    fresh = None
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        fresh = create_engine(goal_engine.url.set(database=name))
        config = Config(str(ROOT / "backend.alembic.ini"))
        with fresh.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert "origin" in {c["name"] for c in inspect(connection).get_columns("catalog_products")}
            command.downgrade(config, "0008_catalog_pools")
            assert "origin" not in {c["name"] for c in inspect(connection).get_columns("catalog_products")}
            command.upgrade(config, "head")
            assert "review_pool_id" in {c["name"] for c in inspect(connection).get_columns("catalog_products")}
            guard = connection.execute(text("SELECT pg_get_functiondef('backend_review_candidate_guard()'::regprocedure)")).scalar()
            assert "this_is_product" in guard and "new_product" in guard
    finally:
        if fresh is not None:
            fresh.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def test_goal_6_existing_product_answer_binds_then_requires_approval(desk):
    rows, result = unknown(desk)
    candidate = desk.products[0]["candidate_id"]
    approve = review_body(rows[1], "approve", selected_candidate_id=candidate)
    assert desk.client.post(f"/runs/{result.run['id']}/reviews", json=approve).status_code == 422
    event = ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "this_is_product", catalog_id=candidate)))
    assert event["new_value"]["resolution"] == "needs_approval"
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert "line-2" in summary["pending_row_ids"] and summary["approved_products"] == []
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=approve))
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert summary["approved_products"][0]["candidate"]["candidate_id"] == candidate
    assert result.result["extraction"]["rows"][1]["row_kind"] == "unknown"


def test_goal_6_correction_needs_fresh_approval_and_keeps_explicit_binding(desk):
    rows, result = unknown(desk)
    endpoint = f"/runs/{result.run['id']}/reviews"
    candidate = desk.products[0]["candidate_id"]
    ok(desk.client.post(endpoint, json=review_body(rows[1], "this_is_product", catalog_id=candidate)))
    approval = review_body(rows[1], "approve", selected_candidate_id=candidate)
    ok(desk.client.post(endpoint, json=approval))
    ok(desk.client.post(endpoint, json=review_body(rows[1], "correct", field_name="quantity", new_value="003")))
    assert "line-2" in ok(desk.client.get(f"/runs/{result.run['id']}/summary"))["pending_row_ids"]
    ok(desk.client.post(endpoint, json=approval))
    item = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))["approved_products"][0]
    assert item["quantity"] == "003" and item["original_quantity"] == "1"
    ok(desk.client.post(endpoint, json=review_body(rows[1], "not_a_product")))
    assert desk.client.post(endpoint, json=approval).status_code == 422


def test_goal_6_new_product_is_marked_idempotent_and_unapproved(desk):
    assert ok(desk.client.get("/health/ready"))["expected_revision"] == "0009_review_answers"
    rows, result = unknown(desk)
    body = new_body(rows[1])
    endpoint = f"/runs/{result.run['id']}/reviews"
    first = ok(desk.client.post(endpoint, json=body))
    again = ok(desk.client.post(endpoint, json=body))
    assert first["id"] == again["id"]
    candidate = first["new_value"]["candidates"][0]
    assert candidate["origin"] == "review"
    records = ok(desk.client.get("/catalog", params={"vendor_id": desk.vendor["id"]}))["products"]
    added = [record for record in records if record["sku"] == "GOAL-REVIEW-003"]
    assert len(added) == 1 and added[0]["origin"] == "review"
    assert added[0]["review_pool_id"] is None
    visible = ok(desk.client.get("/website/catalog", params={"vendor_id": desk.vendor["id"]}))["products"]
    assert next(p for p in visible if p["sku"] == "GOAL-REVIEW-003")["origin"] == "review"
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert summary["approved_products"] == [] and "line-2" in summary["pending_row_ids"]
    changed = deepcopy(body)
    changed["product"]["description"] = "Changed payload"
    assert desk.client.post(endpoint, json=changed).status_code == 409
    ok(desk.client.post(endpoint, json=review_body(rows[1], "approve", selected_candidate_id=candidate["candidate_id"])))
    reviewed = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert reviewed["approved_products"][0]["candidate"]["origin"] == "review"


def test_goal_6_new_product_and_binding_roll_back_on_alias_conflict(desk):
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"], "products": [
        {**PRODUCTS[0], "aliases": [{"value": "TAKEN-ALIAS", "source_role": "vendor_sku"}]}]}))
    rows, result = unknown(desk)
    body = new_body(rows[1])
    body["product"]["aliases"] = [{"value": "TAKEN-ALIAS", "source_role": "vendor_sku"}]
    response = desk.client.post(f"/runs/{result.run['id']}/reviews", json=body)
    assert response.status_code == 409
    records = ok(desk.client.get("/catalog", params={"vendor_id": desk.vendor["id"]}))["products"]
    assert not any(p["sku"] == "GOAL-REVIEW-003" for p in records)
    assert ok(desk.client.get(f"/runs/{result.run['id']}/reviews"))["events"] == []


def test_goal_10_review_created_product_never_matches_another_tenant(desk):
    rows, result = unknown(desk)
    event = ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=new_body(rows[1])))
    review_id = event["new_value"]["candidates"][0]["candidate_id"]
    b = ok(desk.client.post("/tenants", json={"name": "Fictional review-isolation B " + uuid4().hex}))
    desk.client.headers["X-Tenant-ID"] = b["id"]
    vendor = ok(desk.client.post("/vendors", json={"name": "Fictional B vendor"}))
    desk.vendor = vendor
    b_rows = [product_row(1, code="GOAL-REVIEW-003", description="Unmapped code", quantity="1")]
    b_result = process(desk, b_rows)
    assert b_result.suggestions[0]["candidates"] == []
    response = desk.client.post(f"/runs/{b_result.run['id']}/reviews", json=review_body(
        b_rows[0], "this_is_product", catalog_id=review_id))
    assert response.status_code == 422


def test_goal_6_uncertain_line_cannot_finish_with_acknowledgement_or_no_match(desk):
    row = product_row(1, code="MISSING-999", description="Unmapped synthetic fixture", quantity="1")
    result = process(desk, [row])
    assert result.suggestions[0]["tier"] == "uncertain"
    assert desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(row, "no_match")).status_code == 422
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(row, "not_a_product")))
    summary = ok(desk.client.get(f"/runs/{result.run['id']}/summary"))
    assert summary["excluded_rows"][0]["decision"] == "not_a_product"
    assert summary["can_finish_review"]


def test_goal_6_review_product_preserves_pool_scope_and_visible_origin(desk, goal_engine):
    tenant, vendor = UUID(desk.tenant["id"]), UUID(desk.vendor["id"])
    with Session(goal_engine) as session:
        namespace = CatalogNamespace(tenant_id=tenant, vendor_id=vendor, source_catalog_id="fictional",
            source_filename="fictional.csv", workbook_sha256="a"*64, database_sha256="b"*64,
            source_sheet="Fictional", adapter_version="fixture", assigned_by="Fictional reviewer", synthetic=False)
        pool = CatalogPool(tenant_id=tenant, name="Fictional review pool", is_default=True)
        session.add_all([namespace, pool])
        session.flush()
        session.add(CatalogPoolMember(tenant_id=tenant, pool_id=pool.id, vendor_id=vendor, namespace_id=namespace.id))
        pool_id = str(pool.id)
        session.commit()
    rows, result = unknown(desk, use_default_pool=True)
    assert result.run["catalog_pool_id"] == pool_id
    event = ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=new_body(rows[1], vendor_id=str(vendor))))
    candidate = event["new_value"]["candidates"][0]
    assert candidate["origin"] == "review"
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[1], "approve", selected_candidate_id=candidate["candidate_id"])))
    listing = ok(desk.client.get("/website/catalog", params={"pool_id": pool_id}))["products"]
    assert any(p["id"] == candidate["candidate_id"] and p["origin"] == "review" for p in listing)
    workspace = next(w for w in ok(desk.client.get("/website/workspaces"))["workspaces"] if w["id"] == str(tenant))
    pool_summary = next(p for p in workspace["catalog_pools"] if p["id"] == pool_id)
    assert pool_summary["product_count"] == 1 and pool_summary["vendor_ids"] == [str(vendor)]
    next_run = process(desk, [product_row(1, code="GOAL-REVIEW-003", description="Synthetic new accessory", quantity="1")], use_default_pool=True)
    assert next_run.suggestions[0]["candidates"][0]["candidate_id"] == candidate["candidate_id"]
