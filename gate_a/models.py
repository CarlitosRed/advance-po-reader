"""Gate A persistence: a tenant identity foundation, using synthetic data only."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEVELOPMENT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEVELOPMENT_TENANT_NAME = "Gate A synthetic development tenant"


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """A future tenant scope anchor, not authentication or an access policy."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_tenants_name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
