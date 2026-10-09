"""Retain the model returned in a provider receipt separately from the request.

Revision ID: 0003_provider_receipt
Revises: 0002_local_backend
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_provider_receipt"
down_revision = "0002_local_backend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_attempts", sa.Column("actual_model", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_attempts", "actual_model")
