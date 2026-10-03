"""Tenant-scoped local backend history; extracted evidence is never a catalog row.

Database migrations install append-only guards in addition to these constraints.
The existing Gate A tenant identity and metadata remain the shared foundation.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gate_a.models import Base


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )


class Vendor(Identity, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_vendors_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_vendors_tenant_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_vendors_name"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class CatalogProduct(Identity, Base):
    __tablename__ = "catalog_products"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id"], ["vendors.tenant_id", "vendors.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "vendor_id", "id", name="uq_products_scope_id"),
        UniqueConstraint("tenant_id", "vendor_id", "sku", name="uq_products_scope_sku"),
        CheckConstraint("length(trim(sku)) > 0", name="ck_products_sku"),
        CheckConstraint("length(trim(description)) > 0", name="ck_products_description"),
        Index("ix_products_scope_normalized", "tenant_id", "vendor_id", "normalized_sku"),
        Index("ix_products_sku_trgm", "normalized_sku", postgresql_using="gin", postgresql_ops={"normalized_sku": "public.gin_trgm_ops"}),
        Index("ix_products_description_trgm", "description", postgresql_using="gin", postgresql_ops={"description": "public.gin_trgm_ops"}),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sku: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sku: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class CatalogAlias(Identity, Base):
    __tablename__ = "catalog_aliases"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id", "product_id"], ["catalog_products.tenant_id", "catalog_products.vendor_id", "catalog_products.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "vendor_id", "source_role", "value", name="uq_aliases_scope_role_value"),
        CheckConstraint("length(trim(value)) > 0", name="ck_aliases_value"),
        CheckConstraint("length(trim(source_role)) > 0", name="ck_aliases_role"),
        Index("ix_aliases_scope_normalized", "tenant_id", "vendor_id", "source_role", "normalized_value"),
        Index("ix_aliases_value_trgm", "normalized_value", postgresql_using="gin", postgresql_ops={"normalized_value": "public.gin_trgm_ops"}),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(200), nullable=False)
    source_role: Mapped[str] = mapped_column(String(80), nullable=False)


class SourceDocument(Identity, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id"], ["vendors.tenant_id", "vendors.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "catalog_pool_id"], ["catalog_pools.tenant_id", "catalog_pools.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "vendor_id", "id", name="uq_sources_scope_id"),
        CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_sources_sha256"),
        CheckConstraint("byte_size > 0 AND page_count > 0", name="ck_sources_sizes"),
        CheckConstraint("width IS NULL OR width > 0", name="ck_sources_width"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_sources_height"),
        CheckConstraint("length(storage_reference) > 0", name="ck_sources_reference"),
        Index("uq_sources_legacy_scope_hash", "tenant_id", "vendor_id", "sha256", unique=True,
              postgresql_where=text("catalog_pool_id IS NULL")),
        Index("uq_sources_pool_scope_hash", "tenant_id", "vendor_id", "catalog_pool_id", "sha256", unique=True,
              postgresql_where=text("catalog_pool_id IS NOT NULL")),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    catalog_pool_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    storage_reference: Mapped[str] = mapped_column(String(200), nullable=False)


class ProcessingRun(Identity, Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id", "source_document_id"], ["source_documents.tenant_id", "source_documents.vendor_id", "source_documents.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "catalog_pool_id"], ["catalog_pools.tenant_id", "catalog_pools.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_runs_tenant_idempotency"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_runs_idempotency"),
        CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'", name="ck_runs_payload_hash"),
        CheckConstraint("state IN ('created','validating','processing','completed','partial','failed','cancelled')", name="ck_runs_state"),
        CheckConstraint("review_state IN ('not_started','in_progress','resolved')", name="ck_runs_review_state"),
        Index("ix_runs_tenant_source", "tenant_id", "source_document_id"),
    )
    source_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    catalog_pool_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    review_state: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    parses: Mapped[dict | list | None] = mapped_column(JSONB(none_as_null=True))
    outcome_code: Mapped[str | None] = mapped_column(String(80))
    external_authorization: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadReceipt(Identity, Base):
    """Upload request identity remains separate from immutable content deduplication."""

    __tablename__ = "upload_receipts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id", "source_document_id"], ["source_documents.tenant_id", "source_documents.vendor_id", "source_documents.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_uploads_tenant_key"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_uploads_key"),
        CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'", name="ck_uploads_hash"),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ProviderAttempt(Identity, Base):
    __tablename__ = "provider_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["processing_runs.tenant_id", "processing_runs.id"], ondelete="RESTRICT"),
        CheckConstraint("latency_ms >= 0", name="ck_attempts_latency"),
        Index("ix_attempts_tenant_run", "tenant_id", "run_id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    actual_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(200))
    response_id: Mapped[str | None] = mapped_column(String(200))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Suggestion(Identity, Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["processing_runs.tenant_id", "processing_runs.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "run_id", "row_id", name="uq_suggestions_run_row"),
        CheckConstraint("outcome IN ('suggested','ambiguous','no_match')", name="ck_suggestions_outcome"),
        CheckConstraint("jsonb_typeof(candidates) = 'array'", name="ck_suggestions_candidates"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    row_id: Mapped[str] = mapped_column(String(120), nullable=False)
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    retrieval_version: Mapped[str] = mapped_column(String(80), nullable=False, default="catalog-retrieval-v1",
                                                    server_default=text("'catalog-retrieval-v1'"))
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list,
                                           server_default=text("'[]'::jsonb"))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class ReviewEvent(Identity, Base):
    __tablename__ = "review_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["processing_runs.tenant_id", "processing_runs.id"], ondelete="RESTRICT"),
        CheckConstraint("length(trim(reviewer)) > 0 AND length(trim(reason)) > 0", name="ck_reviews_attribution"),
        Index("ix_reviews_tenant_run", "tenant_id", "run_id", "created_at"),
        UniqueConstraint("tenant_id", "run_id", "event_sequence", name="uq_reviews_run_sequence"),
        CheckConstraint("event_sequence IS NULL OR event_sequence > 0", name="ck_reviews_positive_sequence"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_sequence: Mapped[int | None] = mapped_column(BigInteger)
    row_id: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[dict] = mapped_column(JSONB, nullable=False)
    old_value: Mapped[dict | list | str | None] = mapped_column(JSONB(none_as_null=True))
    new_value: Mapped[dict | list | str | None] = mapped_column(JSONB(none_as_null=True))
    selected_candidate_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))

    @classmethod
    def audit_order(cls):
        # Preserve the established ordering of legacy NULL records, followed by
        # the serialized sequence of new records regardless of clock changes.
        return cls.event_sequence.asc().nullsfirst(), cls.created_at, cls.id


class CatalogNamespace(Identity, Base):
    """An immutable source revision assigned explicitly to one local scope."""
    __tablename__ = "catalog_namespaces"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id"], ["vendors.tenant_id", "vendors.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "vendor_id", name="uq_namespace_vendor"),
        UniqueConstraint("tenant_id", "vendor_id", "id", name="uq_namespace_scope_id"),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_catalog_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    workbook_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    database_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(200), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(200), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CatalogPool(Identity, Base):
    """An explicit tenant-local group of source namespaces for candidate search."""
    __tablename__ = "catalog_pools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_catalog_pools_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_catalog_pools_tenant_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_catalog_pools_name"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class CatalogPoolMember(Identity, Base):
    """Membership is by original namespace; products are never copied or merged."""
    __tablename__ = "catalog_pool_members"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "pool_id"], ["catalog_pools.tenant_id", "catalog_pools.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "vendor_id", "namespace_id"],
            ["catalog_namespaces.tenant_id", "catalog_namespaces.vendor_id", "catalog_namespaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "pool_id", "namespace_id", name="uq_catalog_pool_member"),
        UniqueConstraint("tenant_id", "pool_id", "vendor_id", "namespace_id", name="uq_catalog_pool_member_scope"),
    )
    pool_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class CatalogSourceProduct(Identity, Base):
    """Literal workbook fields, attributes and details remain separate from search."""
    __tablename__ = "catalog_source_products"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vendor_id", "product_id"],
            ["catalog_products.tenant_id", "catalog_products.vendor_id", "catalog_products.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "vendor_id", "namespace_id"],
            ["catalog_namespaces.tenant_id", "catalog_namespaces.vendor_id", "catalog_namespaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "vendor_id", "product_id", name="uq_source_product_scope"),
    )
    vendor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attributes: Mapped[list] = mapped_column(JSONB, nullable=False)
    detail_sections: Mapped[list] = mapped_column(JSONB, nullable=False)
