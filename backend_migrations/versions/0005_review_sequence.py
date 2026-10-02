"""Order new human audit events independently of wall-clock adjustments.

Existing records keep NULL and their established timestamp/UUID order. No old
source, value, reviewer or timestamp is rewritten by this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_review_sequence"
down_revision = "0004_website_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("review_events", sa.Column("event_sequence", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_reviews_run_sequence", "review_events", ["tenant_id", "run_id", "event_sequence"])
    op.create_check_constraint("ck_reviews_positive_sequence", "review_events", "event_sequence IS NULL OR event_sequence > 0")


def downgrade():
    op.drop_constraint("ck_reviews_positive_sequence", "review_events", type_="check")
    op.drop_constraint("uq_reviews_run_sequence", "review_events", type_="unique")
    op.drop_column("review_events", "event_sequence")
