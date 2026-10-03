"""Synthetic-only tests for persisted aggregate catalog boundaries."""
import os
from uuid import uuid4
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app import create_app
from backend.catalog import ProductInput, import_products, retrieve_candidates
from backend.config import ROOT, Settings
from backend.errors import BackendError
from backend.models import (CatalogNamespace, CatalogPoolMember, CatalogProduct,
                            CatalogSourceProduct, Vendor)
from backend.pools import configure_pool, pool_vendor_ids, validate_pool_candidate
from backend.synthetic import generate_fixture
from gate_a.database import create_db_engine
from gate_a.models import Tenant

TOKEN = "synthetic-all-products-token"


@pytest.fixture(scope="module")
def engine():
    value = os.environ.get("PO_BACKEND_POOL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set PO_BACKEND_POOL_TEST_DATABASE_URL to the isolated all-products PostgreSQL database")
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.database not in {"gate_a_test_backend_all_products", "gate_a_test_backend_all_products_v2"} or url.query:
        pytest.fail("All-products checks require their isolated loopback test database")
    engine = create_db_engine(url, connect_timeout_seconds=10)
    config = Config(str(ROOT / "backend.alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def make_namespace(session, tenant_id, name, catalog_id, products, *, synthetic=False):
    vendor = Vendor(tenant_id=tenant_id, name=name)
    session.add(vendor)
    session.flush()
    namespace = CatalogNamespace(tenant_id=tenant_id, vendor_id=vendor.id,
        source_catalog_id=catalog_id, source_filename="fictional-source.xlsx",
        workbook_sha256="a" * 64, database_sha256="b" * 64,
        source_sheet="Products", adapter_version="synthetic-test-v1",
        assigned_by="Synthetic QA", synthetic=synthetic)
    session.add(namespace)
    session.flush()
    if products:
        result = import_products(session, tenant_id, vendor.id,
            [ProductInput(sku=sku, description=description) for sku, description in products])
        for row_number, record in enumerate(result, 1):
            session.add(CatalogSourceProduct(tenant_id=tenant_id, vendor_id=vendor.id,
                product_id=record["candidate_id"], namespace_id=namespace.id,
                source_row_number=row_number, raw_fields={"source_sku": record["sku"]},
                attributes=[], detail_sections=[]))
    session.flush()
    return vendor, namespace


def two_catalogs(session):
    tenant = Tenant(name="Synthetic pool tenant " + uuid4().hex)
    session.add(tenant)
    session.flush()
    first, n1 = make_namespace(session, tenant.id, "Fictional source one", "fictional-1", [
        ("SAME-100", "Fictional collision one"), ("ABCD-1234", "Fictional exact item"),
        ("4516", "Fictional numeric description code"), ("SYN-ONLY-1", "Not in aggregate provenance")])
    second, n2 = make_namespace(session, tenant.id, "Fictional source two", "fictional-2", [
        ("SAME-100", "Fictional collision two"), ("NORM-200", "Fictional normalized item"),
        ("B712O-2CL", "Fictional typo hint product")])
    excluded, n3 = make_namespace(session, tenant.id, "Fictional excluded source", "fictional-3", [
        ("OUTSIDE-1", "Excluded fictional product")])
    synth_vendor, n4 = make_namespace(session, tenant.id, "Fictional fixture", "synthetic", [], synthetic=True)
    return tenant, (first, n1), (second, n2), (excluded, n3), (synth_vendor, n4)


def create_pool(session, tenant_id, a, b, *, default=True):
    return configure_pool(session, tenant_id, "All products", [a.id, b.id], make_default=default)


def test_pool_membership_is_explicit_idempotent_and_excludes_synthetic(session):
    tenant, first, second, excluded, synthetic = two_catalogs(session)
    pool = create_pool(session, tenant.id, first[1], second[1])
    again = configure_pool(session, tenant.id, "All products", [second[1].id, first[1].id], make_default=True)
    assert again.id == pool.id and again.is_default
    members = session.scalars(select(CatalogPoolMember).where(CatalogPoolMember.pool_id == pool.id)).all()
    assert {member.namespace_id for member in members} == {first[1].id, second[1].id}
    assert len(pool_vendor_ids(session, tenant.id, pool.id)) == 2
    with pytest.raises(ValueError, match="different membership"):
        configure_pool(session, tenant.id, "All products", [first[1].id, excluded[1].id], make_default=True)
    with pytest.raises(ValueError, match="non-synthetic"):
        configure_pool(session, tenant.id, "Bad pool", [synthetic[1].id], make_default=False)


def test_lookup_unions_members_preserves_provenance_and_keeps_collisions_ambiguous(session):
    tenant, first, second, excluded, _ = two_catalogs(session)
    pool = create_pool(session, tenant.id, first[1], second[1])
    vendors = pool_vendor_ids(session, tenant.id, pool.id)
    same = retrieve_candidates(session, tenant.id, first[0].id,
        [{"raw_value": "SAME-100", "source_role": "vendor_sku"}], None,
        vendor_ids=vendors, pool_id=pool.id, limit=5)
    assert same["outcome"] == "ambiguous" and len(same["candidates"]) == 2
    assert {item["origin_vendor_id"] for item in same["candidates"]} == {str(first[0].id), str(second[0].id)}
    assert {item["namespace_id"] for item in same["candidates"]} == {str(first[1].id), str(second[1].id)}
    bounded = retrieve_candidates(session, tenant.id, None,
        [{"raw_value": "SAME-100", "source_role": "vendor_sku"}], None,
        vendor_ids=vendors, pool_id=pool.id, limit=1)
    assert bounded["outcome"] == "ambiguous" and len(bounded["candidates"]) == 1
    exact = retrieve_candidates(session, tenant.id, None,
        [{"raw_value": "ABCD-1234", "source_role": "vendor_sku"}], None,
        vendor_ids=vendors, pool_id=pool.id)
    normalized = retrieve_candidates(session, tenant.id, None,
        [{"raw_value": "norm 200", "source_role": "vendor_sku"}], None,
        vendor_ids=vendors, pool_id=pool.id)
    numeric = retrieve_candidates(session, tenant.id, None, [], "Model 4516", vendor_ids=vendors, pool_id=pool.id)
    fuzzy = retrieve_candidates(session, tenant.id, None, [{"raw_value": "B7120-2CL", "source_role": "vendor_sku"}], None,
        vendor_ids=vendors, pool_id=pool.id)
    assert exact["outcome"] == "suggested" and exact["candidates"][0]["sku"] == "ABCD-1234"
    assert normalized["method"] == "normalized" and normalized["candidates"][0]["namespace_id"] == str(second[1].id)
    assert numeric["method"] == "description_numeric_code_hint"
    assert fuzzy["outcome"] == "suggested"
    outside = session.scalar(select(CatalogProduct).where(CatalogProduct.vendor_id == excluded[0].id))
    assert not validate_pool_candidate(session, tenant.id, pool.id, excluded[0].id, outside.id)
    assert not validate_pool_candidate(session, uuid4(), pool.id, first[0].id,
        session.scalar(select(CatalogProduct.id).where(CatalogProduct.vendor_id == first[0].id)))


def test_pool_ids_cannot_cross_tenant_and_approval_validation_requires_membership(session):
    tenant, first, second, excluded, _ = two_catalogs(session)
    pool = create_pool(session, tenant.id, first[1], second[1])
    outside_product = session.scalar(select(CatalogProduct).where(CatalogProduct.vendor_id == excluded[0].id))
    assert not validate_pool_candidate(session, tenant.id, pool.id, outside_product.vendor_id, outside_product.id)
    with pytest.raises(BackendError, match="catalog_pool_not_found"):
        pool_vendor_ids(session, uuid4(), pool.id)


@pytest.fixture
def web_client(engine):
    settings = Settings(_env_file=None, database_url=SecretStr(engine.url.render_as_string(hide_password=False)),
        local_api_token=SecretStr(TOKEN), live_processing_enabled=False, openai_api_key=None,
        storage_directory=ROOT / "data" / "all-products-test" / uuid4().hex)
    with TestClient(create_app(settings, engine=engine), base_url="http://127.0.0.1:8019") as client:
        client.headers["X-Local-Token"] = TOKEN
        yield client


def test_default_upload_search_details_and_legacy_vendor_path(web_client, engine):
    tenant = web_client.post("/tenants", json={"name": "Synthetic API tenant " + uuid4().hex}).json()
    web_client.headers["X-Tenant-ID"] = tenant["id"]
    with Session(engine) as session:
        _, first = make_namespace(session, UUID(tenant["id"]), "Fictional region one", "fictional-api-1",
            [("SAME-200", "Fictional API item one"), ("SHARED-1", "Fictional collision A"),
             ("SYN-001", "Fictional fixture code item A")])
        _, second = make_namespace(session, UUID(tenant["id"]), "Fictional region two", "fictional-api-2",
            [("SHARED-1", "Fictional collision B"), ("SYN-001", "Fictional fixture code item B")])
        outside_vendor, outside_namespace = make_namespace(session, UUID(tenant["id"]),
            "Fictional excluded source", "fictional-api-excluded", [("OUTSIDE-9", "Excluded candidate")])
        pool = create_pool(session, UUID(tenant["id"]), first, second)
        pool_id = str(pool.id)
        namespace_ids = {str(first.id), str(second.id)}
        first_vendor_id = str(first.vendor_id)
        session.commit()
    workspace = web_client.get("/website/workspaces").json()["workspaces"][0]
    all_products = next(item for item in workspace["catalog_pools"] if item["id"] == pool_id)
    assert all_products["product_count"] == 5 and all_products["member_count"] == 2 and all_products["is_default"]
    assert web_client.get("/website/catalog?q=SHARED-1").json()["total"] == 2
    listed = web_client.get("/website/catalog?pool_id=" + pool_id + "&q=SHARED-1").json()
    assert {p["origin_catalog"] for p in listed["products"]} == {"fictional-api-1", "fictional-api-2"}
    item = listed["products"][0]
    detail = web_client.get("/website/catalog/" + item["id"] + "?pool_id=" + pool_id).json()
    assert detail["source"]["namespace_id"] in namespace_ids
    uploaded = web_client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        files={"file": ("synthetic.pdf", generate_fixture(), "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()
    assert source["catalog_pool_id"] == pool_id
    created = web_client.post("/documents/" + source["id"] + "/runs", headers={"Idempotency-Key": uuid4().hex},
        json={"provider": "synthetic", "fixture_name": "purchase_order"}).json()
    assert created["catalog_pool_id"] == pool_id
    processed = web_client.post("/runs/" + created["id"] + "/process")
    assert processed.status_code == 200 and processed.json()["state"] in {"completed", "partial"}
    suggestions = web_client.get("/runs/" + created["id"] + "/suggestions").json()["suggestions"]
    suggestion = next(item for item in suggestions if item["row_id"] == "line-1")
    assert suggestion["outcome"] == "ambiguous" and len(suggestion["candidates"]) == 2
    assert {candidate["origin_vendor_id"] for candidate in suggestion["candidates"]} == {
        str(first.vendor_id), str(second.vendor_id)}
    assert web_client.get("/runs/" + created["id"] + "/reviews").json()["events"] == []
    outside_id = web_client.get("/website/catalog?vendor_id=" + str(outside_vendor.id) + "&q=OUTSIDE-9").json()["products"][0]["id"]
    row = web_client.get("/runs/" + created["id"] + "/result").json()["extraction"]["rows"][0]
    review = {"action": "propose_candidate", "row_id": row["row_id"], "reviewer": "Synthetic QA",
        "reason": "Pool boundary check", "evidence_reference": row["evidence"], "candidate_ids": [outside_id]}
    assert web_client.post("/runs/" + created["id"] + "/reviews", json=review).status_code == 422
    in_pool = suggestion["candidates"][0]
    approve = {**review, "action": "approve", "candidate_ids": None,
        "selected_candidate_id": in_pool["candidate_id"]}
    assert web_client.post("/runs/" + created["id"] + "/reviews", json=approve).status_code == 201
    old_upload = web_client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        data={"vendor_id": first_vendor_id}, files={"file": ("legacy.pdf", generate_fixture(), "application/pdf")})
    assert old_upload.status_code == 201 and old_upload.json()["catalog_pool_id"] is None
    old_run = web_client.post("/documents/" + old_upload.json()["id"] + "/runs",
        headers={"Idempotency-Key": uuid4().hex}, json={"provider": "synthetic", "fixture_name": "purchase_order"})
    assert old_run.status_code == 201 and old_run.json()["catalog_pool_id"] is None


def test_no_default_pool_has_clear_setup_error(web_client):
    tenant = web_client.post("/tenants", json={"name": "Synthetic no-pool " + uuid4().hex}).json()
    web_client.headers["X-Tenant-ID"] = tenant["id"]
    response = web_client.get("/website/catalog")
    assert response.status_code == 409 and response.json()["error"] == "default_catalog_pool_setup_required"
    payload = web_client.get("/website/corpus").json()
    assert payload["catalog_selection_required"] is True and payload["default_catalog_pool"] is None
    upload = web_client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        files={"file": ("synthetic.pdf", generate_fixture(), "application/pdf")})
    assert upload.status_code == 409 and upload.json()["error"] == "default_catalog_pool_setup_required"
