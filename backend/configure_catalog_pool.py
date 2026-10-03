"""Create or verify an explicit tenant-scoped catalog pool and select its default."""
import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import create_db_engine
from backend.models import CatalogPoolMember, CatalogNamespace, CatalogProduct
from backend.pools import configure_pool
from sqlalchemy import func, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--namespace-id", required=True, action="append", type=UUID,
                        help="Authorized source namespace UUID; repeat once per member")
    parser.add_argument("--name", default="All products")
    parser.add_argument("--default", action="store_true", help="Make this the tenant's default upload pool")
    args = parser.parse_args()
    settings = Settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine, expire_on_commit=False) as session:
            pool = configure_pool(session, args.tenant_id, args.name, args.namespace_id,
                                  make_default=args.default)
            members = session.scalars(select(CatalogPoolMember).where(
                CatalogPoolMember.tenant_id == args.tenant_id, CatalogPoolMember.pool_id == pool.id)).all()
            products = session.scalar(select(func.count()).select_from(CatalogProduct).join(
                CatalogPoolMember, (CatalogPoolMember.tenant_id == CatalogProduct.tenant_id) &
                (CatalogPoolMember.vendor_id == CatalogProduct.vendor_id)).join(CatalogNamespace,
                (CatalogNamespace.tenant_id == CatalogPoolMember.tenant_id) &
                (CatalogNamespace.vendor_id == CatalogPoolMember.vendor_id) &
                (CatalogNamespace.id == CatalogPoolMember.namespace_id)).where(
                    CatalogPoolMember.tenant_id == args.tenant_id, CatalogPoolMember.pool_id == pool.id,
                    CatalogNamespace.synthetic.is_(False), CatalogProduct.active.is_(True)))
            session.commit()
            print({"pool_id": str(pool.id), "tenant_id": str(args.tenant_id), "name": pool.name,
                   "is_default": pool.is_default, "member_count": len(members), "product_count": products})
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
