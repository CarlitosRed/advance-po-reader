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

from backend.contracts import ExtractionPayload

FixtureKind = Literal["purchase_order", "unsupported", "unknown", "partial"]
KINDS = ("purchase_order", "unsupported", "unknown", "partial")
MEDIA_TYPES = ("application/pdf", "image/png")
FIXTURE_VERSION = "synthetic-po-v1"


def _lines(kind: str) -> list[tuple[float, str]]:
    heading = {"purchase_order": "PURCHASE ORDER", "partial": "PURCHASE ORDER",
               "unsupported": "INVOICE", "unknown": "UNCLASSIFIED DOCUMENT"}[kind]
    lines = [(0.08, f"SYNTHETIC DEMO ONLY - {heading}"),
             (0.12, "PO number: SYN-PO-0001"),
             (0.16, "Vendor: Synthetic Supplies    Currency: USD"),
             (0.24, "Vendor SKU | Description | Quantity | Unit | Unit price | Line total")]
    if kind in ("purchase_order", "partial"):
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
    if kind in ("purchase_order", "partial"):
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
    document_type = "purchase_order" if kind in ("purchase_order", "partial") else kind
    return ExtractionPayload.model_validate({
        "contract_name": "ProductDocument", "schema_version": "1.1",
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
