"""CLI for the PO interpretation logic. No UI, website, or import schema."""
import argparse
import json
import logging
import zipfile
from pathlib import Path

from po_reader.catalog import DB, build_catalog, load_catalog
from po_reader.service import cart_change, create, read, shipping_change


def input_documents(path, images=False):
    extensions = {".pdf"} | ({".png", ".jpg", ".jpeg", ".webp"} if images else set())
    if path.is_dir():
        for item in sorted(path.iterdir()):
            if item.is_file() and item.suffix.lower() in extensions:
                yield item.name, item.read_bytes()
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).suffix.lower() in extensions]
            if len(members) > 100 or sum(item.file_size for item in members) > 200 * 1024 * 1024:
                raise ValueError("Use an archive with at most 100 documents and 200 MB uncompressed")
            for item in members:
                if item.file_size > 20 * 1024 * 1024:
                    raise ValueError("Each archive document must be at most 20 MB")
                with archive.open(item) as source:
                    raw = source.read(20 * 1024 * 1024 + 1)
                yield Path(item.filename.replace("\\", "/")).name, raw
    else:
        yield path.name, path.read_bytes()


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog")
    analyze = commands.add_parser("analyze", help="Analyze PDFs with the native text engine (vision analysis is unavailable)", description="Use the local native PDF text engine only. Vision analysis is unavailable; image-only PDFs need OCR and are not analyzed.")
    analyze.add_argument("input", type=Path)
    analyze.add_argument("--summary", action="store_true", help="Print only the key fields and match states")
    analyze.add_argument("--render", action="store_true", help="Also save page images; off by default")
    analyze.add_argument("--limit", type=int, help="Process at most this many input documents")
    show = commands.add_parser("show")
    show.add_argument("session_id")
    add = commands.add_parser("add")
    add.add_argument("session_id")
    add.add_argument("product_id")
    add.add_argument("quantity")
    add.add_argument("--line-id")
    add.add_argument("--unit", choices=["EA", "EACH", "PK"])
    add.add_argument("--confirm", action="store_true", help="Explicitly confirm an uncertain, manual, or edited row")
    remove = commands.add_parser("remove")
    remove.add_argument("session_id")
    remove.add_argument("line_id")
    shipping = commands.add_parser("shipping")
    shipping.add_argument("session_id")
    shipping.add_argument("details", type=Path, help="Local JSON with company/address/postcode/country_code/phone strings")
    shipping.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not DB.exists():
        build_catalog()
    if args.command == "catalog":
        result = dict(authority="sample_catalog", products=list(load_catalog().values()))
    elif args.command == "analyze":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")
        result = []
        for filename, raw in input_documents(args.input, images=True):
            if args.limit is not None and len(result) >= args.limit:
                break
            logging.info("Reading %s", filename)
            try:
                doc = create(raw, filename, render=args.render)
            except Exception as error:
                result.append(dict(filename=filename,status="failed",error=str(error)))
                continue
            if args.summary:
                doc = {key:doc[key] for key in ("session_id", "filename", "status", "profile", "company", "shipping", "order_number", "lines", "warnings", "extraction") if key in doc}
                if "extraction" in doc:
                    doc["extraction"] = {key:doc["extraction"][key] for key in ("provider", "model", "failures", "usage") if key in doc["extraction"]}
                doc["lines"] = [{key:line[key] for key in ("line_id", "vendor_id", "customer_id", "supplier_id", "identifiers", "description", "quantity", "uom", "kind", "match", "source_validation") if key in line} for line in doc["lines"]]
            result.append(doc)
        if not result:
            parser.error("No supported documents found")
    elif args.command == "show":
        result = read(args.session_id)
    elif args.command == "add":
        result = cart_change(dict(session_id=args.session_id, line_id=args.line_id, product_id=args.product_id,
                                 quantity=args.quantity, uom=args.unit, confirmed=args.confirm))
    elif args.command == "remove":
        result = cart_change(dict(session_id=args.session_id, line_id=args.line_id, action="remove"))
    elif args.command == "shipping":
        request = json.loads(args.details.read_text(encoding="utf-8-sig"))
        request.update(session_id=args.session_id, confirmed=args.confirm)
        result = shipping_change(request)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    if args.command == "analyze" and any(d.get("status") in ("failed", "partial") for d in result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
