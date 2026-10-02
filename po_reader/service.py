"""Persisted local review sessions. The server validates every cart entry."""
import json
import io
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from .catalog import ROOT, load_catalog, normalize_id
from .engine import analyze, quantity
from .rendering import RegionRenderer
from .retrieval import ProductRetriever

SESSIONS = ROOT / "output/sessions"


def session_folder(session_id):
    if not re.fullmatch(r"[a-f0-9]{32}", session_id or ""):
        raise ValueError("Unknown review session")
    return SESSIONS / session_id


def save(document):
    folder = session_folder(document["session_id"])
    target = folder / "review.json"
    temp = folder / "review.tmp"
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(target)


def read(session_id):
    return json.loads((session_folder(session_id) / "review.json").read_text(encoding="utf-8"))


def create(raw, filename, render=False, provider=None):
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("Use a PDF of 20 MB or fewer for this prototype")
    if provider is None and b"%PDF-" not in raw[:1024]:
        raise ValueError("Choose a PDF file")
    filename = filename.replace("\\", "/").split("/")[-1][:200] or "purchase-order.pdf"
    if provider is None:
        document = analyze(raw, filename, load_catalog())
    else:
        from .vision import analyze_vision
        document = analyze_vision(raw, filename, load_catalog(), provider)
    document["session_id"] = uuid.uuid4().hex
    document["created_utc"] = datetime.now(timezone.utc).isoformat()
    document["audit"] = []
    document["cart"] = []
    folder = session_folder(document["session_id"])
    folder.mkdir(parents=True)
    source_name = "source.pdf"
    if document.get("source_type") == "image":
        with Image.open(io.BytesIO(raw)) as image:
            source_name = "source" + {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image.format]
    document["source_file"] = source_name
    (folder / source_name).write_bytes(raw)
    if render:
        renderer = RegionRenderer(budget_bytes=0)
        if document.get("source_type") == "image":
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source)
                try:
                    image.save(folder / "page-1.png", format="PNG")
                finally:
                    if image is not source:
                        image.close()
        else:
            for page in document["pages"]:
                scale = min(1.5, math.sqrt(3_900_000 / (page["width"] * page["height"])))
                (folder / f"page-{page['page']}.png").write_bytes(renderer.render(raw,page["page"],scale=scale))
    save(document)
    return document


def cart_change(request):
    document = read(request.get("session_id"))
    line_id = request.get("line_id")
    line = next((r for r in document["lines"] if r["line_id"] == line_id), None)
    if request.get("action") == "remove":
        document["cart"] = [r for r in document["cart"] if r["line_id"] != line_id]
        document["audit"].append(dict(action="cart_remove", line_id=line_id, at=datetime.now(timezone.utc).isoformat()))
        save(document)
        return document
    if line_id is not None and line is None:
        raise ValueError("This product row was not found")
    if line and line["kind"] == "charge":
        raise ValueError("Shipping charges cannot be added as products")
    product_id = normalize_id(request.get("product_id", ""))
    catalog = load_catalog()
    if product_id not in catalog:
        raise ValueError("This product number is not in the sample catalog. Specify one of its 18 product IDs.")
    requested_quantity = request.get("quantity")
    if not isinstance(requested_quantity, str) or len(requested_quantity)>40 or not quantity(requested_quantity):
        raise ValueError("Enter a positive quantity")
    uom = request.get("uom") or None
    if uom not in (None, "EA", "EACH", "PK"):
        raise ValueError("Choose Each, Pack, or Not stated")
    source_match = line and line["match"]["status"] == "matched" and line["match"]["product_id"] == product_id
    if source_match:
        retriever = ProductRetriever(catalog)
        try:
            source_match = line.get("retrieval",{}).get("catalog_fingerprint") == retriever.fingerprint
        finally:
            retriever.close()
    unchanged = source_match and quantity(requested_quantity) == line["quantity"] and uom == line["uom"]
    if not unchanged and request.get("confirmed") is not True:
        raise ValueError("Confirm the product number, quantity and unit before adding this uncertain or edited row")
    line_id = line_id or "manual-" + uuid.uuid4().hex[:8]
    entry = dict(line_id=line_id, product_id=product_id, product_name=catalog[product_id]["name"],
                 quantity=quantity(requested_quantity), uom=uom,
                 resolution=("vision_catalog_match" if line.get("extraction_method") == "vision_model" else "sample_match") if unchanged else "user_confirmed",
                 evidence=line["evidence"] if line else [])
    document["cart"] = [r for r in document["cart"] if r["line_id"] != line_id] + [entry]
    document["audit"].append(dict(action="cart_add", entry=entry, at=datetime.now(timezone.utc).isoformat()))
    save(document)
    return document


def shipping_change(request):
    document = read(request.get("session_id"))
    if request.get("confirmed") is not True:
        raise ValueError("Confirm the company and shipping details")
    values = {key:request.get(key, "") for key in ("company", "address", "postcode", "country_code", "phone")}
    if any(not isinstance(v, str) or len(v) > 2000 for v in values.values()):
        raise ValueError("Invalid shipping details")
    if not values["company"].strip() or not values["address"].strip() or not values["country_code"].strip():
        raise ValueError("Specify a company, shipping address and country")
    if values["country_code"] not in ("GB", "IE", "OTHER"):
        raise ValueError("Choose a country")
    document["confirmed_shipping"] = dict(**values, status="user_confirmed")
    document["audit"].append(dict(action="shipping_confirm", values=values, at=datetime.now(timezone.utc).isoformat()))
    save(document)
    return document
