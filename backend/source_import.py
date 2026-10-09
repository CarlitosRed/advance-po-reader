"""Explicit, versioned local import of staging catalogs and the confirmed corpus.

Read only copied snapshots. Never import draft VLM targets, training labels,
aliases, prices, or media. Source observations are not extraction results.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.catalog import ProductInput, import_products
from backend.config import ROOT, Settings
from backend.models import CatalogNamespace, CatalogProduct, CatalogSourceProduct, Vendor
from backend.synthetic import FIXTURE_VERSION
from backend.uploads import digest, validate_file
from gate_a.database import create_db_engine
from gate_a.models import Tenant

ADAPTER_VERSION = "regional-catalog-adapter-v1"
PRIVATE = ROOT / "data" / "website"


def checked_snapshot(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash = digest(source.read_bytes())
    if destination.exists():
        if digest(destination.read_bytes()) != source_hash:
            raise ValueError("Existing private snapshot differs; use a new worktree/source revision")
    else:
        shutil.copyfile(source, destination)
    if digest(destination.read_bytes()) != source_hash:
        raise ValueError("Source changed during snapshot copy")
    return source_hash


def import_catalogs(session, database, expected_hash, assigned_by, mapping):
    if not assigned_by.strip() or mapping not in {"single-workspace", "separate-workspaces"}:
        raise ValueError("Explicit local mapping and named assignment required")
    if digest(database.read_bytes()) != expected_hash:
        raise ValueError("Staging database does not match its source manifest")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Staging database integrity check failed")
        catalogs = [dict(r) for r in connection.execute("SELECT c.*, w.filename, w.sha256 FROM catalogs c "
            "JOIN source_workbooks w ON w.source_id=c.source_id ORDER BY c.catalog_id")]
        if not catalogs:
            raise ValueError("No source catalog namespaces")
        # Idempotency is source-revision + explicit mapping, not a filename guess.
        existing = session.scalars(select(CatalogNamespace).where(
            CatalogNamespace.synthetic.is_(False), CatalogNamespace.adapter_version == ADAPTER_VERSION)).all()
        if existing:
            if {n.source_catalog_id for n in existing} != {c["catalog_id"] for c in catalogs} or any(
                n.database_sha256 != expected_hash for n in existing):
                raise ValueError("Existing catalog revision differs; explicit versioning required")
            tenant_count = len({n.tenant_id for n in existing})
            if (mapping == "single-workspace" and tenant_count != 1) or (
                    mapping == "separate-workspaces" and tenant_count != len(catalogs)):
                raise ValueError("Existing mapping differs; explicit migration required")
            return catalog_receipt(session, existing)
        attributes, details = defaultdict(list), defaultdict(list)
        for table, destination in [("product_attributes", attributes), ("product_detail_sections", details)]:
            for row in connection.execute("SELECT * FROM " + table + " ORDER BY source_row_number"):
                entry = dict(row)
                destination[(entry["catalog_id"], entry["product_id_display"])].append(entry)
        shared = None
        if mapping == "single-workspace":
            shared = Tenant(name="Local catalog test workspace")
            session.add(shared)
            session.flush()
        namespaces = []
        imported_keys = set()
        for catalog in catalogs:
            tenant = shared or Tenant(name="Local test — " + catalog["region_label"])
            if shared is None:
                session.add(tenant)
                session.flush()
            vendor = Vendor(tenant_id=tenant.id, name=catalog["region_label"])
            session.add(vendor)
            session.flush()
            namespace = CatalogNamespace(tenant_id=tenant.id, vendor_id=vendor.id,
                source_catalog_id=catalog["catalog_id"], source_filename=catalog["filename"],
                workbook_sha256=catalog["sha256"], database_sha256=expected_hash,
                source_sheet=catalog["primary_sheet"], adapter_version=ADAPTER_VERSION,
                assigned_by=assigned_by, synthetic=False)
            session.add(namespace)
            session.flush()
            products = [dict(row) for row in connection.execute(
                "SELECT * FROM catalog_products WHERE catalog_id=? ORDER BY source_row_number", (catalog["catalog_id"],))]
            if not products:
                raise ValueError("Empty source catalog")
            for start in range(0, len(products), 500):
                inputs = [ProductInput(sku=p["product_id_display"], description=p["product_name_raw"]
                    or p["product_description_raw"] or p["product_id_display"]) for p in products[start:start + 500]]
                # The legacy API calls this search field SKU. It is the unchanged
                # catalog primary product ID, not an inferred printed SKU alias.
                records = import_products(session, tenant.id, vendor.id, inputs)
                for source, record in zip(products[start:start + 500], records):
                    key = (catalog["catalog_id"], source["product_id_display"])
                    imported_keys.add(key)
                    session.add(CatalogSourceProduct(tenant_id=tenant.id, vendor_id=vendor.id,
                        product_id=record["candidate_id"], namespace_id=namespace.id,
                        source_row_number=source["source_row_number"], raw_fields=source,
                        attributes=attributes[key], detail_sections=details[key]))
            namespaces.append(namespace)
        if (set(attributes) | set(details)) - imported_keys:
            raise ValueError("Source attributes/details refer to missing products")
        session.flush()
        # Fictional sample catalog stays visibly distinct from the real catalogs.
        tenant_id = namespaces[0].tenant_id
        demo = Vendor(tenant_id=tenant_id, name="Synthetic sample — fictional products")
        session.add(demo)
        session.flush()
        session.add(CatalogNamespace(tenant_id=tenant_id, vendor_id=demo.id, source_catalog_id="synthetic",
            source_filename="Generated fictional fixture", workbook_sha256="0"*64, database_sha256="0"*64,
            source_sheet="Not applicable", adapter_version=FIXTURE_VERSION, assigned_by=assigned_by, synthetic=True))
        import_products(session, tenant_id, demo.id, [
            ProductInput(sku="SYN-001", description="Synthetic blue widget"),
            ProductInput(sku="SYN-002", description="Synthetic red widget")])
        session.flush()
        return catalog_receipt(session, namespaces)
    finally:
        connection.close()


def catalog_receipt(session, namespaces):
    from sqlalchemy import func
    return [{"tenant_id": str(n.tenant_id), "vendor_id": str(n.vendor_id),
        "source_catalog_id": n.source_catalog_id,
        "products": session.scalar(select(func.count()).select_from(CatalogProduct).where(
            CatalogProduct.tenant_id == n.tenant_id, CatalogProduct.vendor_id == n.vendor_id))}
        for n in namespaces]


def import_corpus(archive, source_manifest, settings):
    expected = source_manifest["pdf_evidence"]
    archive_hash = digest(archive.read_bytes())
    if archive_hash != expected["archive_sha256"]:
        raise ValueError("PDF archive differs from preserved evidence")
    folder = PRIVATE / "corpus"
    folder.mkdir(parents=True, exist_ok=True)
    documents = []
    with zipfile.ZipFile(archive) as source:
        pdfs = [i for i in source.infolist() if not i.is_dir() and i.filename.lower().endswith(".pdf")]
        if len(pdfs) != expected["documents"]:
            raise ValueError("PDF member count differs from source manifest")
        members = {}
        for info in pdfs:
            if info.file_size > settings.max_upload_bytes:
                raise ValueError("Archive member exceeds the validated upload limit")
            data = source.read(info)
            members[(Path(info.filename).name, digest(data))] = data
        for document_id, record in expected["documents_by_id"].items():
            data = members.pop((record["filename"], record["sha256"]))
            metadata = validate_file(data, settings)
            if metadata["media_type"] != "application/pdf" or metadata["page_count"] != record["pages"]:
                raise ValueError("Original PDF page count differs from source manifest")
            path = folder / (record["sha256"] + ".pdf")
            if path.exists() and digest(path.read_bytes()) != record["sha256"]:
                raise ValueError("Existing corpus file integrity failed")
            if not path.exists():
                path.write_bytes(data)
            documents.append({"document_id": document_id, "filename": record["filename"],
                "sha256": record["sha256"], "byte_size": len(data), "page_count": metadata["page_count"],
                "extraction_status": "not_processed"})
        if members:
            raise ValueError("Unaccounted PDF member")
    index = {"version": "local-corpus-v1", "archive_sha256": archive_hash,
        "documents": documents, "pages": sum(d["page_count"] for d in documents),
        "legacy_predictions_imported": False}
    manifest = folder / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")) != index:
        raise ValueError("Existing corpus inventory differs")
    manifest.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"documents": len(documents), "pages": index["pages"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf-archive", type=Path, required=True)
    parser.add_argument("--mapping", choices=["single-workspace", "separate-workspaces"], required=True)
    parser.add_argument("--assigned-by", required=True)
    args = parser.parse_args()
    snapshot = PRIVATE / "source-snapshot"
    checked_snapshot(args.manifest, snapshot / "source-manifest.json")
    checked_snapshot(args.catalog_database, snapshot / "catalog.sqlite3")
    checked_snapshot(args.pdf_archive, snapshot / "corpus.zip")
    manifest = json.loads((snapshot / "source-manifest.json").read_text(encoding="utf-8"))
    settings = Settings()
    corpus = import_corpus(snapshot / "corpus.zip", manifest, settings)
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as session:
            receipt = import_catalogs(session, snapshot / "catalog.sqlite3",
                manifest["database_files"]["regional-product-catalog.sqlite3"]["sha256"], args.assigned_by, args.mapping)
            session.commit()
        result = {"adapter_version": ADAPTER_VERSION, "mapping": args.mapping,
            "catalogs": receipt, "corpus": corpus, "provider_calls": 0, "legacy_predictions_imported": False}
        (PRIVATE / "import-receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"catalogs": len(receipt), "products": sum(r["products"] for r in receipt),
            **corpus, "provider_calls": 0}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
