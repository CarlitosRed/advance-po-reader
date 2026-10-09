"""Private catalog provenance and explicit human candidate proposals.

Revision ID: 0004_website_catalog
Revises: 0003_provider_receipt
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_website_catalog"
down_revision = "0003_provider_receipt"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
    ]


def upgrade():
    op.create_table("catalog_namespaces", *identity(),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("source_catalog_id", sa.String(120), nullable=False),
        sa.Column("source_filename", sa.String(200), nullable=False),
        sa.Column("workbook_sha256", sa.String(64), nullable=False),
        sa.Column("database_sha256", sa.String(64), nullable=False),
        sa.Column("source_sheet", sa.String(200), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("assigned_by", sa.String(200), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id","vendor_id"], ["vendors.tenant_id","vendors.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id","vendor_id",name="uq_namespace_vendor"),
        sa.UniqueConstraint("tenant_id","vendor_id","id",name="uq_namespace_scope_id"))
    op.create_table("catalog_source_products", *identity(),
        sa.Column("vendor_id",sa.Uuid(),nullable=False),
        sa.Column("product_id",sa.Uuid(),nullable=False),
        sa.Column("namespace_id",sa.Uuid(),nullable=False),
        sa.Column("source_row_number",sa.Integer(),nullable=False),
        sa.Column("raw_fields",JSONB(),nullable=False),
        sa.Column("attributes",JSONB(),nullable=False),
        sa.Column("detail_sections",JSONB(),nullable=False),
        sa.ForeignKeyConstraint(["tenant_id","vendor_id","product_id"],
            ["catalog_products.tenant_id","catalog_products.vendor_id","catalog_products.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id","vendor_id","namespace_id"],
            ["catalog_namespaces.tenant_id","catalog_namespaces.vendor_id","catalog_namespaces.id"],ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id","vendor_id","product_id",name="uq_source_product_scope"))
    for table in ("catalog_namespaces","catalog_source_products"):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION backend_append_only()")
    # A manually searched candidate must first have a named, immutable proposal
    # within this run/row. Approval never accepts an arbitrary browser ID.
    op.execute("""CREATE OR REPLACE FUNCTION backend_review_candidate_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.action='propose_candidate' AND (
        jsonb_typeof(NEW.new_value->'candidates') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.new_value->'candidates') NOT BETWEEN 1 AND 5
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.new_value->'candidates') c
          WHERE NOT EXISTS (SELECT 1 FROM catalog_products p JOIN processing_runs r
            ON r.tenant_id=p.tenant_id AND r.vendor_id=p.vendor_id
            WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND p.id::text=c->>'candidate_id'))
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Proposed candidates must belong to the run catalog';
      END IF;
      IF NEW.selected_candidate_id IS NOT NULL AND NOT (
        EXISTS (SELECT 1 FROM suggestions s WHERE s.tenant_id=NEW.tenant_id AND s.run_id=NEW.run_id
          AND s.row_id=NEW.row_id
          AND s.candidates @> jsonb_build_array(jsonb_build_object('candidate_id',NEW.selected_candidate_id::text)))
        OR EXISTS (SELECT 1 FROM review_events e WHERE e.tenant_id=NEW.tenant_id AND e.run_id=NEW.run_id
          AND e.row_id=NEW.row_id AND e.action='propose_candidate'
          AND e.new_value->'candidates' @> jsonb_build_array(jsonb_build_object('candidate_id',NEW.selected_candidate_id::text)))
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Review candidate must belong to an immutable row candidate set';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")


def downgrade():
    # Downgrade would discard source evidence and manual candidate audit semantics.
    raise RuntimeError("Evidence-preserving migration; create a fresh local database instead of downgrading")
