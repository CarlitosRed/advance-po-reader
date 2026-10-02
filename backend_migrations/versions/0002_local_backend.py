"""Local tenant/vendor catalogs and append-only document processing history.

Revision ID: 0002_local_backend
Revises: 0001_gate_a
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_local_backend"
down_revision = "0001_gate_a"
branch_labels = None
depends_on = None


def identity():
    return [sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT")]


def column(name, type_, nullable=False, **kwargs):
    return sa.Column(name, type_, nullable=nullable, **kwargs)


def vendor_fk():
    return sa.ForeignKeyConstraint(["tenant_id", "vendor_id"], ["vendors.tenant_id", "vendors.id"], ondelete="RESTRICT")


def source_fk():
    return sa.ForeignKeyConstraint(["tenant_id", "vendor_id", "source_document_id"],
        ["source_documents.tenant_id", "source_documents.vendor_id", "source_documents.id"], ondelete="RESTRICT")


def run_fk():
    return sa.ForeignKeyConstraint(["tenant_id", "run_id"], ["processing_runs.tenant_id", "processing_runs.id"], ondelete="RESTRICT")


def upgrade() -> None:
    op.create_table("vendors", *identity(), column("name", sa.String(200)),
        sa.UniqueConstraint("tenant_id", "id", name="uq_vendors_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_vendors_tenant_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_vendors_name"))
    op.create_table("catalog_products", *identity(), column("vendor_id", sa.Uuid()),
        column("sku", sa.String(200)), column("description", sa.Text()),
        column("normalized_sku", sa.String(200)), column("active", sa.Boolean(), server_default=sa.true()), vendor_fk(),
        sa.UniqueConstraint("tenant_id", "vendor_id", "id", name="uq_products_scope_id"),
        sa.UniqueConstraint("tenant_id", "vendor_id", "sku", name="uq_products_scope_sku"),
        sa.CheckConstraint("length(trim(sku)) > 0", name="ck_products_sku"),
        sa.CheckConstraint("length(trim(description)) > 0", name="ck_products_description"))
    op.create_index("ix_products_scope_normalized", "catalog_products", ["tenant_id", "vendor_id", "normalized_sku"])
    op.create_table("catalog_aliases", *identity(), column("vendor_id", sa.Uuid()),
        column("product_id", sa.Uuid()), column("value", sa.String(200)),
        column("normalized_value", sa.String(200)), column("source_role", sa.String(80)),
        sa.ForeignKeyConstraint(["tenant_id", "vendor_id", "product_id"],
            ["catalog_products.tenant_id", "catalog_products.vendor_id", "catalog_products.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "vendor_id", "source_role", "value", name="uq_aliases_scope_role_value"),
        sa.CheckConstraint("length(trim(value)) > 0", name="ck_aliases_value"),
        sa.CheckConstraint("length(trim(source_role)) > 0", name="ck_aliases_role"))
    op.create_index("ix_aliases_scope_normalized", "catalog_aliases", ["tenant_id", "vendor_id", "source_role", "normalized_value"])
    op.create_table("source_documents", *identity(), column("vendor_id", sa.Uuid()),
        column("sha256", sa.String(64)), column("byte_size", sa.BigInteger()),
        column("media_type", sa.String(80)), column("page_count", sa.Integer()),
        column("width", sa.Integer(), nullable=True), column("height", sa.Integer(), nullable=True),
        column("storage_reference", sa.String(200)), vendor_fk(),
        sa.UniqueConstraint("tenant_id", "vendor_id", "id", name="uq_sources_scope_id"),
        sa.UniqueConstraint("tenant_id", "vendor_id", "sha256", name="uq_sources_scope_hash"),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_sources_sha256"),
        sa.CheckConstraint("byte_size > 0 AND page_count > 0", name="ck_sources_sizes"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="ck_sources_width"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="ck_sources_height"),
        sa.CheckConstraint("length(storage_reference) > 0", name="ck_sources_reference"))
    op.create_table("upload_receipts", *identity(), column("vendor_id", sa.Uuid()),
        column("source_document_id", sa.Uuid()), column("idempotency_key", sa.String(200)),
        column("payload_hash", sa.String(64)), source_fk(),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_uploads_tenant_key"),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_uploads_key"),
        sa.CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'", name="ck_uploads_hash"))
    op.create_table("processing_runs", *identity(), column("source_document_id", sa.Uuid()),
        column("vendor_id", sa.Uuid()), column("provider", sa.String(80)),
        column("state", sa.String(24)), column("review_state", sa.String(24)),
        column("idempotency_key", sa.String(200)), column("payload_hash", sa.String(64)),
        column("result", JSONB(), nullable=True), column("parses", JSONB(), nullable=True),
        column("outcome_code", sa.String(80), nullable=True), column("external_authorization", JSONB(), nullable=True),
        column("finished_at", sa.DateTime(timezone=True), nullable=True), source_fk(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_runs_tenant_idempotency"),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_runs_idempotency"),
        sa.CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'", name="ck_runs_payload_hash"),
        sa.CheckConstraint("state IN ('created','validating','processing','completed','partial','failed','cancelled')", name="ck_runs_state"),
        sa.CheckConstraint("review_state IN ('not_started','in_progress','resolved')", name="ck_runs_review_state"))
    op.create_index("ix_runs_tenant_source", "processing_runs", ["tenant_id", "source_document_id"])
    op.create_table("provider_attempts", *identity(), column("run_id", sa.Uuid()),
        column("state", sa.String(80)), column("model", sa.String(120)),
        column("prompt_version", sa.String(80)), column("schema_version", sa.String(80)),
        column("request_id", sa.String(200), nullable=True), column("response_id", sa.String(200), nullable=True),
        column("usage", JSONB(), server_default=sa.text("'{}'::jsonb")),
        column("latency_ms", sa.Integer()), column("error_code", sa.String(80), nullable=True),
        column("synthetic", sa.Boolean()), column("finished_at", sa.DateTime(timezone=True), nullable=True), run_fk(),
        sa.CheckConstraint("latency_ms >= 0", name="ck_attempts_latency"))
    op.create_index("ix_attempts_tenant_run", "provider_attempts", ["tenant_id", "run_id"])
    op.create_table("suggestions", *identity(), column("run_id", sa.Uuid()),
        column("row_id", sa.String(120)), column("candidates", JSONB()),
        column("method", sa.String(80)), column("outcome", sa.String(24)), column("reason", sa.Text()), run_fk(),
        sa.UniqueConstraint("tenant_id", "run_id", "row_id", name="uq_suggestions_run_row"),
        sa.CheckConstraint("outcome IN ('suggested','ambiguous','no_match')", name="ck_suggestions_outcome"),
        sa.CheckConstraint("jsonb_typeof(candidates) = 'array'", name="ck_suggestions_candidates"))
    op.create_table("review_events", *identity(), column("run_id", sa.Uuid()),
        column("row_id", sa.String(120), nullable=True), column("action", sa.String(80)),
        column("reviewer", sa.String(200)), column("reason", sa.Text()), column("evidence_reference", JSONB()),
        column("old_value", JSONB(), nullable=True), column("new_value", JSONB(), nullable=True),
        column("selected_candidate_id", sa.Uuid(), nullable=True), run_fk(),
        sa.CheckConstraint("length(trim(reviewer)) > 0 AND length(trim(reason)) > 0", name="ck_reviews_attribution"))
    op.create_index("ix_reviews_tenant_run", "review_events", ["tenant_id", "run_id", "created_at"])
    # Optional trusted extension. The exception subtransaction keeps the migration
    # usable where the role has no extension privilege or the module is unavailable.
    op.execute("""DO $$ BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
      EXCEPTION WHEN insufficient_privilege OR undefined_file OR feature_not_supported THEN
        RAISE NOTICE 'pg_trgm unavailable; exact and normalized retrieval remain enabled';
      END $$""")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                 WHERE e.extname='pg_trgm' AND n.nspname='public') THEN
        CREATE INDEX ix_products_sku_trgm ON catalog_products USING gin (normalized_sku public.gin_trgm_ops);
        CREATE INDEX ix_products_description_trgm ON catalog_products USING gin (description public.gin_trgm_ops);
        CREATE INDEX ix_aliases_value_trgm ON catalog_aliases USING gin (normalized_value public.gin_trgm_ops);
      END IF;
      END $$""")
    op.execute("""CREATE FUNCTION backend_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Append-only backend history cannot be changed'; END $$""")
    for table in ("vendors", "catalog_products", "catalog_aliases", "source_documents", "upload_receipts", "suggestions", "review_events"):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION backend_append_only()")
    op.execute("""CREATE FUNCTION backend_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Run history cannot be deleted'; END IF;
      IF ROW(NEW.id,NEW.tenant_id,NEW.source_document_id,NEW.vendor_id,NEW.provider,NEW.idempotency_key,
          NEW.payload_hash,NEW.external_authorization,NEW.created_at) IS DISTINCT FROM
         ROW(OLD.id,OLD.tenant_id,OLD.source_document_id,OLD.vendor_id,OLD.provider,OLD.idempotency_key,
          OLD.payload_hash,OLD.external_authorization,OLD.created_at) OR
          (OLD.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result) OR
          (OLD.parses IS NOT NULL AND NEW.parses IS DISTINCT FROM OLD.parses) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Run identity and recorded evidence cannot be changed';
      END IF; RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER processing_runs_guard BEFORE UPDATE OR DELETE ON processing_runs FOR EACH ROW EXECUTE FUNCTION backend_run_guard()")
    op.execute("""CREATE FUNCTION backend_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Provider attempt history cannot be deleted'; END IF;
      IF OLD.finished_at IS NOT NULL OR NEW.finished_at IS NULL OR
         ROW(NEW.id,NEW.tenant_id,NEW.run_id,NEW.model,NEW.prompt_version,NEW.schema_version,NEW.synthetic,NEW.created_at)
            IS DISTINCT FROM
         ROW(OLD.id,OLD.tenant_id,OLD.run_id,OLD.model,OLD.prompt_version,OLD.schema_version,OLD.synthetic,OLD.created_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Provider attempts permit one finalization only';
      END IF; RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER provider_attempts_guard BEFORE UPDATE OR DELETE ON provider_attempts FOR EACH ROW EXECUTE FUNCTION backend_attempt_guard()")
    op.execute("""CREATE FUNCTION backend_review_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.selected_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM suggestions s WHERE s.tenant_id=NEW.tenant_id AND s.run_id=NEW.run_id AND s.row_id=NEW.row_id
        AND s.candidates @> jsonb_build_array(jsonb_build_object('candidate_id',NEW.selected_candidate_id::text))
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Review choice must belong to its frozen candidate snapshot';
      END IF; RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER review_events_candidate_guard BEFORE INSERT ON review_events FOR EACH ROW EXECUTE FUNCTION backend_review_candidate_guard()")


def downgrade() -> None:
    # Drop dependent tables before their parent rows; no history DELETE is issued.
    for table in ("review_events", "suggestions", "provider_attempts", "processing_runs",
                  "upload_receipts", "source_documents", "catalog_aliases", "catalog_products", "vendors"):
        op.drop_table(table)
    for function in ("backend_review_candidate_guard", "backend_attempt_guard", "backend_run_guard", "backend_append_only"):
        op.execute(f"DROP FUNCTION {function}()")
    # pg_trgm may predate this migration or be shared by other local schemas.
