"""Public fictional demo sources; exact deterministic hashes gate fixture output.

These observations are hand-authored synthetic expectations, never OCR/model
performance and never substitutes for extraction from an arbitrary upload.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from types import MappingProxyType
from typing import Literal, Mapping

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path

from backend.contracts import ExtractionPayload

FixtureKind = Literal["purchase_order", "unsupported", "unknown", "partial", "continuation"]
KINDS = ("purchase_order", "unsupported", "unknown", "partial", "continuation")
MEDIA_TYPES = ("application/pdf", "image/png")
FIXTURE_VERSION = "synthetic-po-v1"


def _lines(kind: str) -> list[tuple[float, str]]:
    is_continuation = kind == "continuation"
    heading = {"purchase_order": "PURCHASE ORDER", "partial": "PURCHASE ORDER", "continuation": "PURCHASE ORDER",
               "unsupported": "INVOICE", "unknown": "UNCLASSIFIED DOCUMENT"}[kind]
    lines = [(0.08, f"SYNTHETIC DEMO ONLY - {heading}"),
             (0.12, "PO number: SYN-PO-0001"),
             (0.16, "Vendor: Synthetic Supplies    Currency: USD"),
             (0.24, "Vendor SKU | Description | Quantity | Unit | Unit price | Line total")]
    if is_continuation:
        lines.extend([(0.30, "SYN-001 | Synthetic blue widget adjustable support arm | 4 | EA | 432.2000 | 1728.8000"),
                      (0.35, "20 inch width; 16′ length; zinc-coated steel"),
                      (0.43, "SYN-002 | Synthetic red widget mounting bracket | [quantity blank] | EA | 18.00 | [line total blank]"),
                      (0.56, "Freight charge | 12.00"), (0.62, "Order total | 1740.8000"),
                      (0.70, "Delivery note: synthetic fixture only; no live order." )])
    elif kind in ("purchase_order", "partial"):
        sku = "SYN-00I (uncertain: SYN-001)" if kind == "partial" else "SYN-001"
        lines.extend([(0.30, f"{sku} | Synthetic blue widget | 2 | EA | 12.50 | 25.00"),
                      (0.39, "SYN-002 | Synthetic red widget | 3 | EA | 5.00 | 15.00"),
                      (0.48, "Shipping charge | 4.00"),
                      (0.57, "Total | 44.00")])
    else:
        lines.append((0.30, "No purchase-order product rows are expected."))
    if kind == "partial":
        lines.append((0.68, "Synthetic uncertainty: I or 1 is unresolved."))
    return lines


@lru_cache(maxsize=8)
def generate_fixture(kind: FixtureKind = "purchase_order", media_type: str = "application/pdf") -> bytes:
    """Generate a real one-page PDF or PNG, deterministically and without I/O."""
    if kind not in KINDS or media_type not in MEDIA_TYPES:
        raise ValueError("unknown synthetic fixture or media type")
    output = BytesIO()
    if media_type == "application/pdf":
        width, height = 612, 792
        canvas = Canvas(output, pagesize=(width, height), invariant=1, pageCompression=1)
        canvas.setTitle(f"{FIXTURE_VERSION}:{kind}")
        canvas.setAuthor("Advance PO Reader fictional synthetic fixture")
        font_path = Path("C:/Windows/Fonts/arial.ttf")
        if font_path.exists():
            if "OrderLensFixtureArial" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("OrderLensFixtureArial", str(font_path)))
            canvas.setFont("OrderLensFixtureArial", 10)
        else:
            canvas.setFont("Helvetica", 10)
        for y, text in _lines(kind):
            canvas.drawString(width * 0.08, height * (1 - y), text)
        canvas.showPage()
        canvas.save()
    else:
        width, height = 1400, 1800
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=20)
        for y, text in _lines(kind):
            draw.text((width * 0.08, height * y), text, fill="black", font=font)
        image.save(output, format="PNG", optimize=False)
    return output.getvalue()


@lru_cache(maxsize=1)
def fixture_registry() -> Mapping[str, tuple[str, str]]:
    """Known bytes are regenerated on process restart; filenames grant no trust."""
    return MappingProxyType({sha256(generate_fixture(kind, media_type)).hexdigest(): (kind, media_type)
                             for kind in KINDS for media_type in MEDIA_TYPES})


def fixture_identity(source_bytes: bytes, media_type: str) -> str | None:
    identity = fixture_registry().get(sha256(source_bytes).hexdigest())
    return identity[0] if identity is not None and identity[1] == media_type else None


def fixture_payload(kind: FixtureKind = "purchase_order") -> ExtractionPayload:
    """Human-authored expectations for the exact fixture bytes and version."""
    if kind not in KINDS:
        raise ValueError("unknown synthetic fixture")
    is_continuation = kind in {"continuation", "continuation-v2"}

    def evidence(region: str) -> list[dict]:
        return [{"page_number": 1, "region_reference": region}]

    def field(value: str | None, label: str | None, region: str,
              state: str | None = None) -> dict:
        return {"state": state or ("observed" if value is not None else "not_applicable"),
                "raw_value": value, "source_label": label,
                "evidence": evidence(region) if value is not None else [],
                "alternative_readings": []}

    regions = [{"region_reference": "header", "bbox":
                {"x0": 0.05, "y0": 0.05, "x1": 0.95, "y1": 0.27}}]
    rows = []
    if is_continuation:
        rows.extend([
            {"row_id": "item-101", "row_kind": "product", "item_group_id": "item-101", "row_role": "product_item",
             "evidence": evidence("item-101"), "identifiers": [{"state": "observed", "raw_value": "SYN-001",
             "source_label": "Vendor SKU", "source_role": "vendor_sku", "evidence": evidence("item-101"), "alternative_readings": []}],
             "description": field("Synthetic blue widget adjustable support arm", "Description", "item-101"),
             "quantity": field("4", "Quantity", "item-101"), "unit": field("EA", "Unit", "item-101"),
             "unit_price": field("432.2000", "Unit price", "item-101"), "line_total": field("1728.8000", "Line total", "item-101"), "uncertainty": None},
            {"row_id": "description-cont-101", "row_kind": "unknown", "item_group_id": "item-101", "row_role": "continuation", "continuation_of": "item-101",
             "evidence": evidence("description-cont-101"), "identifiers": [],
             "description": field("20 inch width; 16′ length; zinc-coated steel", "Description continuation", "description-cont-101"),
             "quantity": field(None, None, "description-cont-101"), "unit": field(None, None, "description-cont-101"),
             "unit_price": field(None, None, "description-cont-101"), "line_total": field(None, None, "description-cont-101"), "uncertainty": "Linked description continuation; not an independent item."},
            {"row_id": "item-202", "row_kind": "product", "item_group_id": "item-202", "row_role": "product_item", "evidence": evidence("item-202"),
             "identifiers": [{"state": "observed", "raw_value": "SYN-002", "source_label": "Vendor SKU", "source_role": "vendor_sku", "evidence": evidence("item-202"), "alternative_readings": []}],
             "description": field("Synthetic red widget mounting bracket", "Description", "item-202"), "quantity": field(None, "Quantity", "item-202", "not_present"),
             "unit": field("EA", "Unit", "item-202"), "unit_price": field("18.00", "Unit price", "item-202"),
             "line_total": field(None, "Line total", "item-202", "not_present"), "uncertainty": None},
            *[{"row_id": rid, "row_kind": kind_, "row_role": "document_detail", "item_group_id": None,
               "evidence": evidence(rid), "identifiers": [], "description": field(desc, None, rid),
               "quantity": field(None, None, rid), "unit": field(None, None, rid), "unit_price": field(None, None, rid),
               "line_total": field(total, "Line total" if total else None, rid), "uncertainty": None}
              for rid, kind_, desc, total in (("freight", "charge", "Freight charge", "12.00"),
                                               ("order-total", "total", "Order total", "1740.8000"),
                                               ("delivery-note", "note", "Delivery note: synthetic fixture only", None))]
        ])
        for rid, y0, y1 in (("item-101", .285, .33), ("description-cont-101", .335, .38), ("item-202", .415, .46),
                            ("freight", .54, .575), ("order-total", .605, .64), ("delivery-note", .68, .72)):
            regions.append({"region_reference": rid, "bbox": {"x0": .05, "y0": y0, "x1": .95, "y1": y1}})
        regions.append({"region_reference": "ambiguous-item", "bbox": {"x0": .05, "y0": .475, "x1": .95, "y1": .51}})
        rows.append({"row_id": "ambiguous-item", "row_kind": "unknown", "row_role": "unknown", "item_group_id": None,
            "evidence": evidence("ambiguous-item"), "identifiers": [],
            "description": field("Synthetic accessory row with unclear item status", "Description", "ambiguous-item"),
            "quantity": field(None, "Quantity", "ambiguous-item", "not_present"),
            "unit": field(None, "Unit", "ambiguous-item", "not_present"),
            "unit_price": field(None, "Unit price", "ambiguous-item", "not_present"),
            "line_total": field(None, "Line total", "ambiguous-item", "not_present"),
            "uncertainty": "Synthetic layout does not establish whether this is an ordered item."})
    elif kind in ("purchase_order", "partial"):
        for index, (sku, description, quantity, price, total) in enumerate([
            ("SYN-001", "Synthetic blue widget", "2", "12.50", "25.00"),
            ("SYN-002", "Synthetic red widget", "3", "5.00", "15.00"),
        ], 1):
            region = f"line-{index}"
            identifier = {"state": "observed", "raw_value": sku,
                          "source_label": "Vendor SKU", "source_role": "vendor_sku",
                          "evidence": evidence(region), "alternative_readings": []}
            uncertainty = None
            if kind == "partial" and index == 1:
                identifier.update(state="uncertain", raw_value="SYN-00I",
                                  alternative_readings=["SYN-001"])
                uncertainty = "Synthetic source identifier character I or 1 is unresolved."
            rows.append({"row_id": region, "row_kind": "product", "evidence": evidence(region),
                         "identifiers": [identifier],
                         "description": field(description, "Description", region),
                         "quantity": field(quantity, "Quantity", region),
                         "unit": field("EA", "Unit", region),
                         "unit_price": field(price, "Unit price", region),
                         "line_total": field(total, "Line total", region),
                         "uncertainty": uncertainty})
        for index, row_kind, description, total in [
            (3, "charge", "Shipping charge", "4.00"), (4, "total", "Total", "44.00")
        ]:
            region = f"line-{index}"
            rows.append({"row_id": region, "row_kind": row_kind, "evidence": evidence(region),
                         "identifiers": [], "description": field(description, None, region),
                         "quantity": field(None, None, region), "unit": field(None, None, region),
                         "unit_price": field(None, None, region),
                         "line_total": field(total, "Line total", region), "uncertainty": None})
        for index in range(1, 5):
            y = 0.30 + (index - 1) * 0.09
            regions.append({"region_reference": f"line-{index}",
                            "bbox": {"x0": 0.05, "y0": y - 0.02, "x1": 0.95, "y1": y + 0.03}})
    document_type = "purchase_order" if kind in ("purchase_order", "partial", "continuation") else kind
    return ExtractionPayload.model_validate({
        "contract_name": "ProductDocument", "schema_version": "1.2" if is_continuation else "1.1",
        "document_type": document_type,
        "document_type_reason": None if document_type == "purchase_order" else
        ("This source is explicitly an invoice." if kind == "unsupported" else
         "The synthetic source has no supported document type."),
        "document_number": field("SYN-PO-0001", "PO number", "header"),
        "vendor_name": field("Synthetic Supplies", "Vendor", "header"),
        "currency": field("USD", "Currency", "header"),
        "pages": [{"page_number": 1, "state": "partial" if kind == "partial" else "complete",
                   "regions": regions,
                   "uncertainty": "Synthetic character ambiguity." if kind == "partial" else None}],
        "rows": rows, "warnings": [],
    })
