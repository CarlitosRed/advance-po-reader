"""Persist explicit same-tenant catalog pools without copying source products.

Revision ID: 0008_catalog_pools
Revises: 0006_catalog_description_hint
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_catalog_pools"
down_revision = "0006_catalog_description_hint"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("catalog_pools",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_catalog_pools_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_catalog_pools_tenant_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_catalog_pools_name"),
    )
    op.create_index("uq_catalog_pools_one_default", "catalog_pools", ["tenant_id"], unique=True,
                    postgresql_where=sa.text("is_default"))
    op.create_table("catalog_pool_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("namespace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "pool_id"], ["catalog_pools.tenant_id", "catalog_pools.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "vendor_id", "namespace_id"],
            ["catalog_namespaces.tenant_id", "catalog_namespaces.vendor_id", "catalog_namespaces.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "pool_id", "namespace_id", name="uq_catalog_pool_member"),
        sa.UniqueConstraint("tenant_id", "pool_id", "vendor_id", "namespace_id", name="uq_catalog_pool_member_scope"),
    )
    op.create_index("ix_catalog_pool_members_products", "catalog_pool_members",
                    ["tenant_id", "pool_id", "vendor_id", "namespace_id"])
    op.add_column("source_documents", sa.Column("catalog_pool_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_sources_catalog_pool", "source_documents", "catalog_pools",
                          ["tenant_id", "catalog_pool_id"], ["tenant_id", "id"], ondelete="RESTRICT")
    op.drop_constraint("uq_sources_scope_hash", "source_documents", type_="unique")
    op.create_index("uq_sources_legacy_scope_hash", "source_documents",
                    ["tenant_id", "vendor_id", "sha256"], unique=True,
                    postgresql_where=sa.text("catalog_pool_id IS NULL"))
    op.create_index("uq_sources_pool_scope_hash", "source_documents",
                    ["tenant_id", "vendor_id", "catalog_pool_id", "sha256"], unique=True,
                    postgresql_where=sa.text("catalog_pool_id IS NOT NULL"))
    op.add_column("processing_runs", sa.Column("catalog_pool_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_runs_catalog_pool", "processing_runs", "catalog_pools",
                          ["tenant_id", "catalog_pool_id"], ["tenant_id", "id"], ondelete="RESTRICT")
    # Historical source/run association and immutable suggestion snapshots remain unchanged.
    op.execute("CREATE TRIGGER catalog_pool_members_immutable BEFORE UPDATE OR DELETE ON catalog_pool_members "
               "FOR EACH ROW EXECUTE FUNCTION backend_append_only()")
    op.execute("""CREATE OR REPLACE FUNCTION backend_review_candidate_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.action='propose_candidate' AND (
        jsonb_typeof(NEW.new_value->'candidates') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.new_value->'candidates') NOT BETWEEN 1 AND 5
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.new_value->'candidates') c
          WHERE NOT EXISTS (SELECT 1 FROM catalog_products p JOIN processing_runs r
            ON r.tenant_id=p.tenant_id AND r.id=NEW.run_id
            WHERE r.tenant_id=NEW.tenant_id AND p.id::text=c->>'candidate_id'
              AND ((r.catalog_pool_id IS NULL AND p.vendor_id=r.vendor_id)
                OR (r.catalog_pool_id IS NOT NULL AND EXISTS (
                  SELECT 1 FROM catalog_source_products sp JOIN catalog_pool_members m
                    ON m.tenant_id=sp.tenant_id AND m.vendor_id=sp.vendor_id AND m.namespace_id=sp.namespace_id
                  WHERE sp.tenant_id=p.tenant_id AND sp.vendor_id=p.vendor_id AND sp.product_id=p.id
                    AND m.tenant_id=r.tenant_id AND m.pool_id=r.catalog_pool_id)))))
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Proposed candidates must belong to the run catalog pool';
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
    raise RuntimeError("Pool memberships and run boundaries are audit history; create a fresh local database to downgrade")
