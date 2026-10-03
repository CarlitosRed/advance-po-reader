"""Persist retrieval method version and source provenance on suggestions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_catalog_description_hint"
down_revision = "0005_review_sequence"
branch_labels = None
depends_on = None


def upgrade():
    # Defaults populate historical rows at the DDL boundary without UPDATE;
    # suggestions are protected by append-only triggers.
    op.add_column("suggestions", sa.Column("retrieval_version", sa.String(80), nullable=False,
                                           server_default=sa.text("'catalog-retrieval-v1'")))
    op.add_column("suggestions", sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()),
                                           nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column("suggestions", "evidence")
    op.drop_column("suggestions", "retrieval_version")
