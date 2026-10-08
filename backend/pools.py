"""Explicit tenant-local catalog pool configuration and scope resolution."""
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.errors import BackendError
from backend.models import CatalogProduct, CatalogNamespace, CatalogPool, CatalogPoolMember, CatalogSourceProduct


def default_pool(session: Session, tenant_id: UUID) -> CatalogPool | None:
    return session.scalar(select(CatalogPool).where(
        CatalogPool.tenant_id == tenant_id, CatalogPool.is_default.is_(True)))


def pool_members(session: Session, tenant_id: UUID, pool_id: UUID, *, require_real=True) -> list[CatalogPoolMember]:
    pool = session.scalar(select(CatalogPool).where(CatalogPool.tenant_id == tenant_id, CatalogPool.id == pool_id))
    if pool is None:
        raise BackendError("catalog_pool_not_found", 404)
    rows = session.execute(select(CatalogPoolMember, CatalogNamespace).join(CatalogNamespace,
        (CatalogNamespace.tenant_id == CatalogPoolMember.tenant_id) &
        (CatalogNamespace.vendor_id == CatalogPoolMember.vendor_id) &
        (CatalogNamespace.id == CatalogPoolMember.namespace_id)).where(
            CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id
        ).order_by(CatalogPoolMember.vendor_id, CatalogPoolMember.namespace_id)).all()
    if require_real and any(namespace.synthetic for _, namespace in rows):
        raise BackendError("synthetic_catalog_outside_pool", 422)
    return [member for member, _ in rows]


def pool_vendor_ids(session: Session, tenant_id: UUID, pool_id: UUID) -> list[UUID]:
    members = pool_members(session, tenant_id, pool_id)
    if not members:
        raise BackendError("catalog_pool_empty", 409)
    return sorted({member.vendor_id for member in members}, key=str)


def pool_product_scope(tenant_id: UUID, pool_id: UUID):
    """Imported namespace rows or marked review entries bound to this pool."""
    imported = select(CatalogSourceProduct.product_id).join(CatalogPoolMember,
        (CatalogPoolMember.tenant_id == CatalogSourceProduct.tenant_id) &
        (CatalogPoolMember.vendor_id == CatalogSourceProduct.vendor_id) &
        (CatalogPoolMember.namespace_id == CatalogSourceProduct.namespace_id)).where(
            CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id,
            CatalogSourceProduct.tenant_id == tenant_id)
    member_vendors = select(CatalogPoolMember.vendor_id).where(
        CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id)
    return or_(CatalogProduct.id.in_(imported), and_(CatalogProduct.origin == "review",
        CatalogProduct.review_pool_id == pool_id, CatalogProduct.vendor_id.in_(member_vendors)))


def pool_product_count(session: Session, tenant_id: UUID, pool_id: UUID):
    return session.scalar(select(func.count()).select_from(CatalogProduct).where(
        CatalogProduct.tenant_id == tenant_id, CatalogProduct.active.is_(True),
        pool_product_scope(tenant_id, pool_id)))


def validate_pool_candidate(session: Session, tenant_id: UUID, pool_id: UUID | None,
                            vendor_id: UUID, product_id: UUID) -> bool:
    if pool_id is None:
        return False
    reviewed = session.scalar(select(CatalogProduct.id).join(CatalogPoolMember,
        (CatalogPoolMember.tenant_id == CatalogProduct.tenant_id) &
        (CatalogPoolMember.vendor_id == CatalogProduct.vendor_id)).where(
            CatalogProduct.tenant_id == tenant_id, CatalogProduct.id == product_id,
            CatalogProduct.vendor_id == vendor_id, CatalogProduct.origin == "review",
            CatalogProduct.review_pool_id == pool_id, CatalogPoolMember.pool_id == pool_id).limit(1))
    if reviewed:
        return True
    return bool(session.scalar(select(CatalogSourceProduct.id).join(CatalogPoolMember,
        (CatalogPoolMember.tenant_id == CatalogSourceProduct.tenant_id) &
        (CatalogPoolMember.vendor_id == CatalogSourceProduct.vendor_id) &
        (CatalogPoolMember.namespace_id == CatalogSourceProduct.namespace_id)).join(CatalogNamespace,
        (CatalogNamespace.tenant_id == CatalogPoolMember.tenant_id) &
        (CatalogNamespace.vendor_id == CatalogPoolMember.vendor_id) &
        (CatalogNamespace.id == CatalogPoolMember.namespace_id)).where(
            CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id,
            CatalogPoolMember.vendor_id == vendor_id, CatalogNamespace.synthetic.is_(False),
            CatalogSourceProduct.product_id == product_id).limit(1)))


def _release_default(session: Session, tenant_id: UUID) -> None:
    """Clear and flush the tenant's current default so the one-default index never sees two."""
    current = default_pool(session, tenant_id)
    if current is not None:
        current.is_default = False
        session.flush()


def configure_pool(session: Session, tenant_id: UUID, name: str, namespace_ids: list[UUID], *, make_default: bool):
    """Create one immutable membership set, or verify an identical rerun."""
    if not name.strip() or not namespace_ids or len(namespace_ids) != len(set(namespace_ids)):
        raise ValueError("Provide a pool name and a non-empty, duplicate-free namespace ID list")
    namespaces = session.scalars(select(CatalogNamespace).where(
        CatalogNamespace.tenant_id == tenant_id, CatalogNamespace.id.in_(namespace_ids),
        CatalogNamespace.synthetic.is_(False)).order_by(CatalogNamespace.id)).all()
    if len(namespaces) != len(namespace_ids):
        raise ValueError("Every namespace must exist in the tenant and be non-synthetic")
    pool = session.scalar(select(CatalogPool).where(CatalogPool.tenant_id == tenant_id, CatalogPool.name == name))
    expected = {(n.vendor_id, n.id) for n in namespaces}
    if pool is None:
        if make_default:
            _release_default(session, tenant_id)
        pool = CatalogPool(tenant_id=tenant_id, name=name, is_default=make_default)
        session.add(pool)
        session.flush()
        for namespace in namespaces:
            session.add(CatalogPoolMember(tenant_id=tenant_id, pool_id=pool.id,
                vendor_id=namespace.vendor_id, namespace_id=namespace.id))
        session.flush()
    else:
        actual = {(m.vendor_id, m.namespace_id) for m in session.scalars(select(CatalogPoolMember).where(
            CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool.id)).all()}
        if actual != expected:
            raise ValueError("Existing pool has a different membership; create a versioned pool instead")
        if make_default and not pool.is_default:
            _release_default(session, tenant_id)
            pool.is_default = True
            session.flush()
    return pool
