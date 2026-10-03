"""Synthetic-only catalog and history tests against a dedicated local database."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.catalog import (
    AliasInput, CatalogConflictError, CatalogScopeError, ProductInput,
    import_products, normalize_identifier, pg_trgm_available, retrieve_candidates,
)
from backend.models import (
    CatalogAlias, CatalogProduct, ProcessingRun, ProviderAttempt, ReviewEvent,
    SourceDocument, Suggestion, UploadReceipt, Vendor,
)
from gate_a.database import create_db_engine
from gate_a.models import Tenant


@pytest.fixture(scope="module")
def engine():
    value = os.environ.get("PO_BACKEND_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set PO_BACKEND_TEST_DATABASE_URL to the isolated catalog test database")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith(("gate_a_test_backend_", "orderlens_product_rows")) or url.query):
        pytest.fail("Catalog tests require an isolated loopback synthetic test database")
    engine = create_db_engine(url, connect_timeout_seconds=10)
    config = Config("backend.alembic.ini")
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


def tenant_vendor(session, name="Synthetic vendor"):
    tenant = Tenant(name=f"Synthetic tenant {uuid4()}")
    session.add(tenant)
    session.flush()
    vendor = Vendor(tenant_id=tenant.id, name=name)
    session.add(vendor)
    session.flush()
    return tenant.id, vendor.id


def product(sku="SYN-001", description="Synthetic blue widget", aliases=()):
    return ProductInput(sku=sku, description=description, aliases=aliases)


def candidates(session, tenant, vendor, raw="SYN-001", role="vendor_sku", **kwargs):
    return retrieve_candidates(session, tenant, vendor,
                               [{"raw_value": raw, "source_role": role}], kwargs.pop("description", None), **kwargs)


def history(session):
    tenant, vendor = tenant_vendor(session)
    source = SourceDocument(tenant_id=tenant, vendor_id=vendor, sha256="a" * 64,
        byte_size=123, media_type="application/pdf", page_count=1, storage_reference=str(uuid4()))
    session.add(source)
    session.flush()
    run = ProcessingRun(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
        provider="synthetic", state="created", review_state="not_started",
        idempotency_key=str(uuid4()), payload_hash="b" * 64)
    session.add(run)
    session.flush()
    return tenant, vendor, source, run


def test_backend_head_and_gate_a_seed(engine):
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == ("0005_review_sequence",)
        assert connection.scalar(text("SELECT count(*) FROM tenants WHERE id='00000000-0000-0000-0000-000000000001'")) == 1


@pytest.mark.parametrize("raw,expected", [("syn-001", "SYN001"), (" 006.00 ", "00600"), ("Á-001", ""), ("!!!", "")])
def test_ascii_search_variant_never_changes_raw(raw, expected):
    original = raw
    assert normalize_identifier(raw) == expected
    assert raw == original


@pytest.mark.parametrize("values", [{"sku": " ", "description": "x"},
                                  {"sku": "x", "description": " "},
                                  {"sku": "x", "description": "x", "unexpected": "x"}])
def test_catalog_input_rejects_blank_or_extra(values):
    with pytest.raises(ValidationError):
        ProductInput(**values)


def test_import_is_idempotent_and_preserves_literal_catalog_sku(session):
    tenant, vendor = tenant_vendor(session)
    alias = AliasInput(value="000-77", source_role="customer_item_number")
    first = import_products(session, tenant, vendor, [product(aliases=(alias,))])
    second = import_products(session, tenant, vendor, [product(aliases=(alias,))])
    assert first == second
    assert session.scalar(select(func.count()).select_from(CatalogProduct).where(CatalogProduct.tenant_id == tenant)) == 1
    assert session.scalar(select(func.count()).select_from(CatalogAlias).where(CatalogAlias.tenant_id == tenant)) == 1
    assert session.scalar(select(CatalogProduct.sku).where(CatalogProduct.tenant_id == tenant)) == "SYN-001"


def test_import_conflict_rolls_back_whole_batch(session):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product()])
    with pytest.raises(CatalogConflictError):
        import_products(session, tenant, vendor, [product("SYN-002"), product(description="Changed")])
    assert session.scalar(select(func.count()).select_from(CatalogProduct).where(CatalogProduct.tenant_id == tenant)) == 1


def test_alias_conflict_does_not_invent_global_rule(session):
    tenant, vendor = tenant_vendor(session)
    alias = AliasInput(value="ITEM-9", source_role="customer_item_number")
    import_products(session, tenant, vendor, [product(aliases=(alias,))])
    with pytest.raises(CatalogConflictError):
        import_products(session, tenant, vendor, [product("SYN-002", aliases=(alias,))])
    assert session.scalar(select(func.count()).select_from(CatalogProduct).where(CatalogProduct.tenant_id == tenant)) == 1


def test_exact_lookup_and_role_sensitive_alias(session):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product(aliases=(AliasInput(value="000-77", source_role="customer_item_number"),))])
    direct = candidates(session, tenant, vendor)
    assert direct["method"] == "exact" and direct["outcome"] == "suggested"
    assert "human approval" in direct["reason"]
    assert candidates(session, tenant, vendor, "000-77", "customer_item_number")["method"] == "exact"
    assert candidates(session, tenant, vendor, "000-77", "mpn")["outcome"] == "no_match"
    assert candidates(session, tenant, vendor, role="customer_item_number")["outcome"] == "no_match"
    assert candidates(session, tenant, vendor, role=None)["outcome"] == "no_match"


def test_normalized_hit_is_only_suggestion_and_preserves_evidence(session):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product()])
    evidence = [{"raw_value": "syn 001", "source_role": "vendor_sku"}]
    result = retrieve_candidates(session, tenant, vendor, evidence, None)
    assert result["method"] == "normalized" and result["outcome"] == "suggested"
    assert evidence[0]["raw_value"] == "syn 001"
    assert result["candidates"][0]["sku"] == "SYN-001"


def test_normalized_collisions_and_exact_conflicts_stay_ambiguous(session):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product("AB-001"), product("AB001")])
    normalized = candidates(session, tenant, vendor, "ab 001")
    assert normalized["outcome"] == "ambiguous" and len(normalized["candidates"]) == 2
    exact = retrieve_candidates(session, tenant, vendor, [
        {"raw_value": "AB-001", "source_role": "vendor_sku"},
        {"raw_value": "AB001", "source_role": "vendor_sku"}], None)
    assert exact["method"] == "exact" and exact["outcome"] == "ambiguous"


def test_tenant_and_vendor_isolation(session):
    tenant, vendor = tenant_vendor(session)
    other_tenant, other_vendor = tenant_vendor(session)
    within = Vendor(tenant_id=tenant, name="Second synthetic vendor")
    session.add(within)
    session.flush()
    one = import_products(session, tenant, vendor, [product()])[0]
    two = import_products(session, other_tenant, other_vendor, [product()])[0]
    three = import_products(session, tenant, within.id, [product()])[0]
    assert len({one["candidate_id"], two["candidate_id"], three["candidate_id"]}) == 3
    for scope, expected in [((tenant, vendor), one), ((other_tenant, other_vendor), two), ((tenant, within.id), three)]:
        result = candidates(session, *scope)
        assert [row["candidate_id"] for row in result["candidates"]] == [expected["candidate_id"]]
    with pytest.raises(CatalogScopeError):
        candidates(session, tenant, other_vendor)


def test_candidate_bound_retains_ambiguity_when_hits_truncated(session):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product(f"AB{'-' * n}001") for n in range(1, 8)])
    result = candidates(session, tenant, vendor, "ab001", limit=2)
    assert len(result["candidates"]) == 2 and result["outcome"] == "ambiguous"
    assert "omitted" in result["reason"]
    with pytest.raises(ValueError):
        candidates(session, tenant, vendor, limit=21)


def test_pg_trgm_typo_and_description_are_bounded_suggestions(session):
    if not pg_trgm_available(session):
        pytest.skip("Local pg_trgm module unavailable; exact/normalized are independently tested")
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product("WIDGET-ABC123"), product("UNRELATED-9", "Orange synthetic adapter")])
    result = candidates(session, tenant, vendor, "WIDGET-ABC124", limit=1)
    assert result["method"] == "trigram" and len(result["candidates"]) == 1
    assert result["candidates"][0]["sku"] == "WIDGET-ABC123"
    assert isinstance(result["candidates"][0]["score"], str)
    result = retrieve_candidates(session, tenant, vendor, [], "Synthetic blue widgte", limit=1)
    assert result["method"] == "trigram" and result["candidates"][0]["sku"] == "WIDGET-ABC123"


def test_extension_absence_has_no_python_full_catalog_scan(session, monkeypatch):
    tenant, vendor = tenant_vendor(session)
    import_products(session, tenant, vendor, [product()])
    monkeypatch.setattr("backend.catalog.pg_trgm_available", lambda session: False)
    result = candidates(session, tenant, vendor, "SYN-003")
    assert result["method"] == "none" and result["outcome"] == "no_match"
    assert "unavailable" in result["reason"]


def test_compound_foreign_keys_reject_cross_tenant_and_cross_vendor(session):
    tenant, vendor, source, run = history(session)
    other_tenant, other_vendor = tenant_vendor(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(CatalogProduct(tenant_id=tenant, vendor_id=other_vendor,
                                  sku="BAD", description="x", normalized_sku="BAD", active=True))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(ProcessingRun(tenant_id=other_tenant, vendor_id=other_vendor,
            source_document_id=source.id, provider="synthetic", state="created", review_state="not_started",
            idempotency_key=str(uuid4()), payload_hash="c" * 64))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(ProviderAttempt(tenant_id=other_tenant, run_id=run.id, state="completed",
            model="synthetic", prompt_version="v1", schema_version="v1", usage={}, latency_ms=0,
            synthetic=True, finished_at=datetime.now(timezone.utc)))
        session.flush()


@pytest.mark.parametrize("table,field,value", [("source_documents", "sha256", "d" * 64),
                                                ("upload_receipts", "idempotency_key", "changed"),
                                                ("suggestions", "reason", "changed"),
                                                ("review_events", "reason", "changed")])
def test_evidence_history_is_append_only(session, table, field, value):
    tenant, vendor, source, run = history(session)
    upload = UploadReceipt(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
                           idempotency_key=str(uuid4()), payload_hash="c" * 64)
    suggestion = Suggestion(tenant_id=tenant, run_id=run.id, row_id="line-1", candidates=[],
                            method="none", outcome="no_match", reason="Synthetic no match")
    event = ReviewEvent(tenant_id=tenant, run_id=run.id, row_id="line-1", action="no_match",
                       reviewer="Synthetic reviewer", reason="Inspected source", evidence_reference={"page": 1})
    session.add_all([upload, suggestion, event])
    session.flush()
    id_ = {"source_documents": source.id, "upload_receipts": upload.id,
           "suggestions": suggestion.id, "review_events": event.id}[table]
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text(f"UPDATE {table} SET {field}=:value WHERE id=:id"), {"value": value, "id": id_})
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": id_})


def test_run_evidence_may_be_assigned_once_then_retained(session):
    tenant, vendor, source, run = history(session)
    run.state = "processing"
    session.flush()
    run.result = {"raw_identifier": "0007"}
    run.parses = {"quantity": "2.00"}
    run.state = "completed"
    session.flush()
    run.review_state = "in_progress"
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("UPDATE processing_runs SET result='{}'::jsonb WHERE id=:id"), {"id": run.id})
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("UPDATE processing_runs SET parses=NULL WHERE id=:id"), {"id": run.id})
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("DELETE FROM processing_runs WHERE id=:id"), {"id": run.id})
    reprocess = ProcessingRun(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
        provider="synthetic", state="created", review_state="not_started", idempotency_key=str(uuid4()), payload_hash="d" * 64)
    session.add(reprocess)
    session.flush()
    assert reprocess.id != run.id and run.result == {"raw_identifier": "0007"}


def test_attempt_records_interruption_then_finalizes_exactly_once(session):
    tenant, vendor, source, run = history(session)
    attempt = ProviderAttempt(tenant_id=tenant, run_id=run.id, state="unknown_outcome",
        model="synthetic", prompt_version="v1", schema_version="v1", usage={}, latency_ms=0,
        error_code="attempt_in_progress_or_interrupted", synthetic=True)
    session.add(attempt)
    session.flush()
    assert attempt.finished_at is None and attempt.state == "unknown_outcome"
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("UPDATE provider_attempts SET model='changed',finished_at=now() WHERE id=:id"), {"id": attempt.id})
    attempt.state = "completed"
    attempt.actual_model = "synthetic-returned-snapshot"
    attempt.usage = {"input_tokens": 10, "output_tokens": 20}
    attempt.request_id = "synthetic-request"
    attempt.latency_ms = 5
    attempt.finished_at = datetime.now(timezone.utc)
    session.flush()
    assert attempt.model == "synthetic" and attempt.actual_model == "synthetic-returned-snapshot"
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("UPDATE provider_attempts SET usage='{}'::jsonb WHERE id=:id"), {"id": attempt.id})
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("DELETE FROM provider_attempts WHERE id=:id"), {"id": attempt.id})


def test_review_candidate_must_be_in_frozen_same_row_snapshot(session):
    tenant, vendor, source, run = history(session)
    candidate = import_products(session, tenant, vendor, [product()])[0]
    session.add(Suggestion(tenant_id=tenant, run_id=run.id, row_id="line-1", candidates=[candidate],
                           method="exact", outcome="suggested", reason="Human review required"))
    session.flush()
    base = dict(tenant_id=tenant, run_id=run.id, row_id="line-1", action="approve",
                reviewer="Synthetic reviewer", reason="Confirmed printed evidence", evidence_reference={"page": 1})
    from uuid import UUID
    good = ReviewEvent(**base, selected_candidate_id=UUID(candidate["candidate_id"]))
    session.add(good)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(ReviewEvent(**base, selected_candidate_id=uuid4()))
        session.flush()
    base["row_id"] = "line-2"
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(ReviewEvent(**base, selected_candidate_id=UUID(candidate["candidate_id"])))
        session.flush()


def test_upload_and_processing_idempotency_is_tenant_scoped(session):
    tenant, vendor, source, run = history(session)
    session.add(UploadReceipt(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
                             idempotency_key="same-key", payload_hash="d" * 64))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(UploadReceipt(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
                                 idempotency_key="same-key", payload_hash="e" * 64))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(ProcessingRun(tenant_id=tenant, vendor_id=vendor, source_document_id=source.id,
            provider="synthetic", state="created", review_state="not_started", idempotency_key=run.idempotency_key,
            payload_hash="e" * 64))
        session.flush()
