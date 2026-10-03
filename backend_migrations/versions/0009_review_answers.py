"""Mark customer-reviewed products and preserve explicit binding snapshots.

Revision ID: 0009_review_answers
Revises: 0008_catalog_pools
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_review_answers"
down_revision = "0008_catalog_pools"
branch_labels = None
depends_on = None

PREVIOUS_GUARD = """CREATE OR REPLACE FUNCTION backend_review_candidate_guard() RETURNS trigger AS $$
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
    END; $$ LANGUAGE plpgsql"""
GUARD = """CREATE OR REPLACE FUNCTION backend_review_candidate_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.action IN ('propose_candidate','this_is_product','new_product') AND (
        jsonb_typeof(NEW.new_value->'candidates') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.new_value->'candidates') NOT BETWEEN 1 AND 5
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.new_value->'candidates') c
          WHERE NOT EXISTS (SELECT 1 FROM catalog_products p JOIN processing_runs r
            ON r.tenant_id=p.tenant_id AND r.id=NEW.run_id
            WHERE r.tenant_id=NEW.tenant_id AND p.id::text=c->>'candidate_id'
              AND ((r.catalog_pool_id IS NULL AND p.vendor_id=r.vendor_id)
                OR (r.catalog_pool_id IS NOT NULL AND p.origin='review' AND p.review_pool_id=r.catalog_pool_id AND EXISTS (SELECT 1 FROM catalog_pool_members rm WHERE rm.tenant_id=r.tenant_id AND rm.pool_id=r.catalog_pool_id AND rm.vendor_id=p.vendor_id))
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
          AND e.row_id=NEW.row_id AND e.action IN ('propose_candidate','this_is_product','new_product')
          AND e.new_value->'candidates' @> jsonb_build_array(jsonb_build_object('candidate_id',NEW.selected_candidate_id::text)))
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Review candidate must belong to an immutable row candidate set';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql"""


def upgrade():
    op.add_column("catalog_products", sa.Column("origin", sa.String(16), nullable=False, server_default="import"))
    op.add_column("catalog_products", sa.Column("review_pool_id", sa.Uuid(), nullable=True))
    op.create_check_constraint("ck_products_origin", "catalog_products",
        "origin IN ('import', 'review') AND (origin = 'review' OR review_pool_id IS NULL)")
    op.create_foreign_key("fk_products_review_pool", "catalog_products", "catalog_pools",
        ["tenant_id", "review_pool_id"], ["tenant_id", "id"], ondelete="RESTRICT")
    op.execute(GUARD)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM catalog_products WHERE origin='review') OR EXISTS (SELECT 1 FROM review_events WHERE action IN ('this_is_product','new_product','not_a_product','not_product'))")).scalar():
        raise RuntimeError("Downgrade would discard review-origin catalog or decision evidence")
    op.execute(PREVIOUS_GUARD)
    op.drop_constraint("fk_products_review_pool", "catalog_products", type_="foreignkey")
    op.drop_constraint("ck_products_origin", "catalog_products", type_="check")
    op.drop_column("catalog_products", "review_pool_id")
    op.drop_column("catalog_products", "origin")
