"""Sample-derived catalog. Building it is explicit; reading new POs never grows it."""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/catalog.sqlite3"
SEED = ROOT / "data/catalog-seed.json"


def normalize_id(value):
    # Hyphens and suffixes are significant until someone verifies an alias.
    return str(value).strip().upper()


def build_catalog(seed=SEED, destination=DB):
    try:
        document = json.loads(Path(seed).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            "The catalog seed file is private and is not in Git. "
            "For the free demo, see README.md: Run the free demo on Windows."
        ) from None
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as db:
        db.execute("CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT NOT NULL, variants TEXT NOT NULL, provenance TEXT NOT NULL)")
        if db.execute("SELECT count(*) FROM products").fetchone()[0]:
            raise ValueError("Catalog already exists; preserve it and use a separate destination to rebuild")
        for item in document["products"]:
            db.execute("INSERT INTO products VALUES (?, ?, ?, ?)", (normalize_id(item["id"]), item["name"],
                       json.dumps(item["variants"]), json.dumps(item["provenance"])))
    return len(document["products"])


def load_catalog(path=DB):
    with sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True) as db:
        return {row[0]: dict(id=row[0], name=row[1], variants=json.loads(row[2]), provenance=json.loads(row[3]),
                            authority="sample_catalog") for row in db.execute("SELECT * FROM products ORDER BY id")}


CODE = re.compile(r"\b\d{5,9}(?:-\d{1,3})?[A-Z]?\b", re.I)


def tokens(description):
    text = CODE.sub(" ", description.upper())
    text = re.sub(r"\(TO\d+\)", " ", text)
    # Tokens are used for comparison only. Source descriptions are never rewritten.
    words = re.findall(r"[A-Z]+|\d+(?:\.\d+)?", text)
    return set(words) - {"WERNER", "UK", "BS", "EN", "131", "THE", "AND", "FOR"}


def similarity(description, product):
    current = tokens(description)
    best = 0.0
    for variant in product["variants"]:
        observed = tokens(variant)
        numeric_a = {t for t in current if t.isdigit() and len(t) < 3}
        numeric_b = {t for t in observed if t.isdigit() and len(t) < 3}
        if numeric_a and numeric_b and numeric_a != numeric_b:
            continue
        overlap = len(current & observed) / max(1, len(current | observed))
        best = max(best, overlap)
    return round(best, 3)


def match_line(line, catalog):
    if line["kind"] == "charge":
        return dict(status="excluded_charge", product_id=None, reason="Shipping charge, not a product.", suggestions=[])
    explicit = normalize_id(line.get("vendor_id") or "")
    embedded = list(dict.fromkeys(CODE.findall(line["description"])))
    supplier = normalize_id(line.get("supplier_id") or "")
    codes = list(dict.fromkeys(c for c in [explicit, supplier, *embedded] if c))
    candidates = sorted(((similarity(line["description"], p), p) for p in catalog.values()), key=lambda x:(-x[0], x[1]["id"]))
    suggestions = [dict(id=p["id"], name=p["name"], description_similarity=s) for s, p in candidates[:3] if s > 0.15]
    selected = explicit or (embedded[0] if len(embedded) == 1 else "")
    product = catalog.get(selected)
    conflicts = [c for c in codes if c != selected]
    # A shortened suffix in description is evidence worth surfacing, not an alias.
    if conflicts:
        return dict(status="review_needed", product_id=selected if product else None,
                    reason="The row contains different product identifiers: " + ", ".join(codes) + ". Please confirm the Werner product number.", suggestions=suggestions)
    if not product:
        return dict(status="not_in_catalog" if selected else "review_needed", product_id=None,
                    reason=(f"Product {selected} was not found in the sample catalog. It may exist outside this catalog. Please specify a catalog product number." if selected else
                            "No single Werner product number was found. Select a suggested product or specify its number."), suggestions=suggestions)
    score = similarity(line["description"], product)
    if score < 0.45:
        return dict(status="review_needed", product_id=selected, reason="The ID matches, but the description is missing or differs from the sample catalog. Confirm this product.", suggestions=suggestions)
    if not line.get("quantity"):
        return dict(status="review_needed", product_id=selected, reason="Product ID and description match; confirm the missing quantity before adding.", suggestions=suggestions)
    if line["uom"] == "PK":
        return dict(status="review_needed", product_id=selected, reason="Product matches; confirm the pack unit and quantity. No pack-to-each conversion is assumed.", suggestions=suggestions)
    return dict(status="matched", product_id=selected, reason="Exact sample-catalog ID and compatible description.", suggestions=[],
                description_similarity=score)
