"""Create or verify an explicit tenant-scoped catalog pool and select its default."""
import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from backend.config import Settings
from gate_a.database import create_db_engine
from backend.models import CatalogPoolMember, CatalogNamespace, Vendor
from backend.pools import configure_pool, pool_product_count
from sqlalchemy import select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--namespace-id", action="append", type=UUID,
                        help="Authorized source namespace UUID; repeat once per member")
    parser.add_argument("--name", default="All products")
    parser.add_argument("--default", action="store_true", help="Make this the tenant's default upload pool")
    parser.add_argument("--list", action="store_true", help="List non-synthetic namespace IDs for this tenant, then exit")
    args = parser.parse_args()
    settings = Settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine, expire_on_commit=False) as session:
            if args.list:
                rows = session.execute(select(CatalogNamespace, Vendor).join(Vendor,
                    (Vendor.tenant_id == CatalogNamespace.tenant_id) & (Vendor.id == CatalogNamespace.vendor_id)).where(
                        CatalogNamespace.tenant_id == args.tenant_id,
                        CatalogNamespace.synthetic.is_(False)).order_by(CatalogNamespace.source_catalog_id)).all()
                print([{"namespace_id": str(namespace.id), "vendor_id": str(vendor.id),
                        "vendor_name": vendor.name, "source_catalog_id": namespace.source_catalog_id,
                        "source_filename": namespace.source_filename, "assigned_by": namespace.assigned_by}
                       for namespace, vendor in rows])
                return
            if not args.namespace_id:
                parser.error("provide --namespace-id at least once or use --list")
            pool = configure_pool(session, args.tenant_id, args.name, args.namespace_id,
                                  make_default=args.default)
            members = session.scalars(select(CatalogPoolMember).where(
                CatalogPoolMember.tenant_id == args.tenant_id, CatalogPoolMember.pool_id == pool.id)).all()
            # Same scope predicate as browse/retrieval: imported namespace rows plus this pool's review entries.
            products = pool_product_count(session, args.tenant_id, pool.id)
            session.commit()
            print({"pool_id": str(pool.id), "tenant_id": str(args.tenant_id), "name": pool.name,
                   "is_default": pool.is_default, "member_count": len(members), "product_count": products})
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
