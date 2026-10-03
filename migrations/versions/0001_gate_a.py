"""Create the Gate A tenant baseline and one explicitly synthetic local tenant.

Revision ID: 0001_gate_a
Revises: None
"""

from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "0001_gate_a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tenants = op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_tenants_name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )
    op.bulk_insert(
        tenants,
        [{
            "id": UUID("00000000-0000-0000-0000-000000000001"),
            "name": "Gate A synthetic development tenant",
        }],
    )


def downgrade() -> None:
    op.drop_table("tenants")
