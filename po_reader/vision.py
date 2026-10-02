"""Read PDF/image pages with vision, reconcile their lines with catalog records."""
import copy
import hashlib
import io
import logging
import math
import re
import time
from collections import Counter

from PIL import Image, ImageOps
import pypdfium2 as pdfium

from .catalog import normalize_id
from .engine import quantity, read_pages, rows
from .model_matching import ModelMatcher
from .model_provider import PAGE_EXTRACTION_SCHEMA, ProviderError, validate_schema
from .rendering import PDFIUM_LOCK, RegionRenderer

LOGGER = logging.getLogger(__name__)

QUANTITY_PARSING_VERSION = "explicit-observed-unit-v1"


def _observed_quantity_parts(raw, unit):
    """Separate an exact numeric literal from its explicitly observed unit only."""
    if not isinstance(raw, str) or not isinstance(unit, str) or len(raw) > 80 or len(unit) > 24:
        return None, "invalid_or_missing_quantity_or_unit"
    explicit_unit = "".join(unit.split()).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,11}", explicit_unit):
        return None, "invalid_or_missing_explicit_unit"
    text = raw.strip()
    number = r"[0-9]+(?:\.[0-9]+)?"
    if re.fullmatch(number, text):
        numeric, method = text, "explicit_numeric_literal"
    else:
        unit_pattern = r"\s*".join(re.escape(character) for character in explicit_unit)
        match = re.fullmatch(r"(" + number + r")\s*" + unit_pattern, text, re.I)
        if match is None:
            return None, "quantity_not_exact_number_or_number_with_observed_unit"
        numeric, method = match.group(1), "explicit_number_with_observed_unit_suffix"
    if len(numeric) > 40 or quantity(numeric) is None:
        return None, "invalid_or_nonpositive_numeric_literal"
    # Keep numeric spelling, including leading zeros and decimal precision.
    return numeric, method


def parse_observed_quantity(raw, unit):
    """Return a positive decimal literal without inferring units or converting packs.

    A combined value such as '006.00ea' parses only when a separate observed unit
    explicitly says EA. Its raw strings and the original page record stay intact.
    This helper may be applied to saved observations without another model call.
    """
    return _observed_quantity_parts(raw, unit)[0]


def _contains(text, value):
    if not isinstance(value, str) or not value.strip():
        return False
    return bool(re.search(r"(?<![A-Z0-9_-])" + re.escape(value.strip()) + r"(?![A-Z0-9_-])", text, re.I))


def _prepare(raw):
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("Use a document of 20 MB or fewer for this prototype")
    if b"%PDF-" in raw[:1024]:
        warnings = []
        try:
            pages = read_pages(raw)
        except Exception:
            # A failed text extractor need not prevent rendering readable PDF pages.
            with PDFIUM_LOCK, pdfium.PdfDocument(raw) as source:
                if len(source) > 50:
                    raise ValueError("Use a PDF of 50 pages or fewer")
                pages = []
                for index in range(len(source)):
                    page = source[index]
                    try:
                        width, height = page.get_size()
                    finally:
                        page.close()
                    pages.append(dict(page=index + 1, width=width, height=height, text="", independent_text="",
                                      words=[], image_count=None, classification="native_reader_failure"))
            warnings.append("Native text extraction failed; source readings require visual confirmation.")
        if not pages:
            raise ValueError("The PDF contains no readable pages")
        renderer = RegionRenderer(budget_bytes=0, max_pixels=8_000_000)
        images = []
        for page in pages:
            if page["width"] <= 0 or page["height"] <= 0:
                raise ValueError("Invalid PDF page dimensions")
            scale = min(3.0, math.sqrt(7_900_000 / (page["width"] * page["height"])))
            page["rendering"] = dict(requested_dpi=216, effective_dpi=round(scale * 72, 2),
                                      pixel_budget=7_900_000, bounded=scale < 3.0)
            images.append(renderer.render(raw, page["page"], scale=scale))
        return pages, images, "pdf", warnings
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Choose a PDF or a single PNG, JPEG, or WebP image")
            if source.width * source.height > 20_000_000:
                raise ValueError("Use an image of 20 million pixels or fewer")
            image = ImageOps.exif_transpose(source).convert("RGB")
            try:
                output = io.BytesIO()
                image.save(output, format="PNG")
                width, height = image.size
            finally:
                image.close()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Choose a readable PDF, PNG, JPEG, or WebP image") from exc
    page = dict(page=1, width=width, height=height, text="", independent_text="", words=[], image_count=1, classification="image")
    return [page], [output.getvalue()], "image", []


def _merge(records, path):
    observations = []
    for record in records:
        node = record
        for key in path:
            node = node[key]
        if node["value"] is not None and node["value"].strip():
            observations.append(dict(**node, page=record["page"]))
    if not observations:
        return dict(value=None, status="review_needed", reason="This field was not observed.", evidence=[])
    values = {" ".join(item["value"].upper().split()) for item in observations}
    uncertain = len(values) > 1 or any(item["status"] != "observed" or not item["evidence_text"]
                                     or not item["evidence_text"].strip() for item in observations)
    return dict(value=observations[0]["value"], status="review_needed" if uncertain else "extracted",
                reason="Different or uncertain page observations need review." if uncertain else "Observed by the vision reader.",
                evidence=[dict(page=item["page"], text=item["evidence_text"], origin="vision_model") for item in observations],
                observations=observations)


def _validate_order(order, pages):
    """Require a printed PO label and both native readings for automatic use."""
    if order["status"] != "extracted":
        order["source_validation"] = dict(status="missing_evidence", reason="The PO observation is missing or uncertain.")
        return
    value = order["value"]
    by_page = {page["page"]: page for page in pages}
    label = re.compile(r"\b(?:PURCHASE\s+ORDER|P\.?\s*O\.?|ORDER)(?:\s*(?:NUMBER|NO\.?|#))?\b", re.I)
    for observation in order["observations"]:
        page = by_page[observation["page"]]
        evidence = observation["evidence_text"] or ""
        if not _contains(evidence, value) or not _contains(page["independent_text"], value):
            continue
        if any(_contains(group["text"], value) and label.search(group["text"]) for group in rows(page["words"])):
            order["source_validation"] = dict(status="corroborated", reason="A positioned PO header and the independent native reader corroborate the observed number.")
            return
    order.update(status="review_needed", reason="Confirm the PO number; its printed header was not corroborated by both native readings.")
    order["source_validation"] = dict(status="vision_only", reason=order["reason"])


def _source_check(line, page):
    evidence = line["evidence"][0]["text"]
    if not evidence or not evidence.strip():
        return dict(status="missing_evidence", reason="No visible row transcription was returned.")
    identifiers = [item["raw_value"] for item in line["identifiers"]
                   if item["role"] in ("vendor_product_code", "manufacturer_part_number")]
    if not identifiers:
        return dict(status="vision_only", reason="No authoritative product identifier can be corroborated.")
    if not all(_contains(evidence, code) for code in identifiers):
        return dict(status="missing_evidence", reason="The returned row transcription does not contain its identifiers.")
    groups = rows(page["words"])
    found = [group for group in groups if all(_contains(group["text"], code) for code in identifiers)]
    if not found:
        return dict(status="vision_only", reason="Native row evidence did not corroborate every printed identifier.")
    description_tokens = set(re.findall(r"[A-Z]{3,}", line["description"].upper()))
    raw_qty, raw_unit = line["quantity_raw"], line["uom_raw"]
    parsed_quantity = parse_observed_quantity(raw_qty, raw_unit)
    if parsed_quantity is None:
        return dict(status="vision_only", reason="Quantity or ordering unit was not observed.")
    qty = re.escape(parsed_quantity)
    unit = r"\s*".join(re.escape(character) for character in "".join(raw_unit.split()))
    pair = r"(?<![A-Z0-9_-])(?:" + qty + r"\s*" + unit + "|" + unit + r"\s*" + qty + r")(?![A-Z0-9_-])"
    qualified = [group for group in found
                 if description_tokens.intersection(re.findall(r"[A-Z]{3,}", group["text"].upper()))
                 and re.search(pair, group["text"], re.I)]
    if len(qualified) != 1:
        return dict(status="vision_only", reason="No unique native row corroborates the product description and quantity/unit pair.")
    row_text = qualified[0]["text"]
    independent = page["independent_text"]
    if not independent.strip():
        return dict(status="vision_only", reason="The independent native reader could not corroborate the row.")
    if not all(_contains(independent, code) for code in identifiers):
        return dict(status="disagreement", reason="The native readers disagree about a printed identifier.")
    positions = qualified[0]["words"]
    line["evidence"].append(dict(page=page["page"], text=row_text, origin="native_row",
                                 bbox=[min(w["x0"] for w in positions), min(w["top"] for w in positions),
                                       max(w["x1"] for w in positions), max(w["bottom"] for w in positions)]))
    return dict(status="corroborated", reason="Positioned native rows and the independent reader corroborate the identifiers; quantity and unit occur in the native row.")


def _line(observed, page, index):
    identifiers = copy.deepcopy(observed["identifiers"])
    parsed_quantity, parsing_method = _observed_quantity_parts(observed["quantity_raw"], observed["uom_raw"])
    def first(role):
        return next((item["raw_value"] for item in identifiers if item["role"] == role), None)
    result = dict(line_id=f"line-{index}", page=page["page"], source_line_label=observed["source_line_label"],
                  identifiers=identifiers, vendor_id=first("vendor_product_code"),
                  supplier_id=first("manufacturer_part_number"), customer_id=first("customer_item_number"),
                  description=observed["description_raw"] or "", quantity_raw=observed["quantity_raw"],
                  quantity=parsed_quantity, uom_raw=observed["uom_raw"],
                  uom=observed["uom_raw"].strip().upper() if observed["uom_raw"] else None,
                  unit_price_raw=observed["unit_price_raw"], amount_raw=observed["amount_raw"],
                  kind=observed["kind"], attributes=copy.deepcopy(observed["attributes"]),
                  uncertainties=copy.deepcopy(observed["uncertainties"]),
                  extraction_method="vision_model", evidence=[dict(page=page["page"], text=observed["evidence_text"],
                                                                   bbox=None, origin="vision_model")], cart=None)
    result["quantity_parsing"] = dict(version=QUANTITY_PARSING_VERSION,
                                       status="parsed" if parsed_quantity is not None else "review_needed",
                                       method=parsing_method, raw=observed["quantity_raw"],
                                       explicit_unit_raw=observed["uom_raw"], numeric_literal=parsed_quantity,
                                       unit_inferred=False, unit_conversion=False)
    result["source_validation"] = _source_check(result, page)
    if observed["uncertainties"]:
        result["source_validation"] = dict(status="vision_only", reason="The reader reported uncertainty in this row.")
    return result


def analyze_vision(raw, filename, catalog, provider):
    pages, images, source_type, warnings = _prepare(raw)
    usage_start = len(getattr(provider, "usage", []))
    if hasattr(provider, "refresh_model_identities"):
        provider.refresh_model_identities()
    records, lines, failures = [], [], []
    image_hashes = [hashlib.sha256(image).hexdigest() for image in images]
    counts = Counter(image_hashes)
    repeated_pages = {index + 1 for index, digest in enumerate(image_hashes) if counts[digest] > 1}
    for page, image in zip(pages, images):
        native = f"Positioned reader:\n{page['text']}\nIndependent reader:\n{page['independent_text']}"
        started = time.monotonic()
        LOGGER.info("  Reading page %s/%s with %s", page["page"], len(pages), provider.model)
        try:
            observed = validate_schema(provider.extract_page(image, page["page"], native), PAGE_EXTRACTION_SCHEMA)
        except (ProviderError, OSError, TimeoutError) as exc:
            LOGGER.warning("  Page %s failed after %.1fs: %s", page["page"], time.monotonic() - started, exc)
            failures.append(dict(page=page["page"], error=str(exc)))
            warnings.append(f"Page {page['page']} extraction failed; this document requires review.")
            continue
        LOGGER.info("  Page %s extracted %s rows in %.1fs", page["page"], len(observed["lines"]), time.monotonic() - started)
        record = dict(**observed, page=page["page"], image_sha256=image_hashes[page["page"] - 1])
        records.append(record)
        for observed_line in observed["lines"]:
            candidate = _line(observed_line, page, len(lines) + 1)
            candidate["document_type"] = observed["document_type"]
            if observed["document_type"] != "purchase_order":
                candidate["source_validation"] = dict(status="vision_only", reason="This source page was not identified as a purchase order; confirm its rows.")
            if page["page"] in repeated_pages:
                candidate["source_validation"] = dict(status="vision_only", reason="This page image repeats within the document; confirm the requested rows.")
            lines.append(candidate)
    if repeated_pages:
        warnings.append("Repeated page images were detected; repeated rows need confirmation.")
    signatures = Counter((line["page"], line["source_line_label"], line["description"],
                          tuple(normalize_id(i["raw_value"]) for i in line["identifiers"]),
                          line["quantity_raw"], line["uom_raw"]) for line in lines)
    for line in lines:
        signature = (line["page"], line["source_line_label"], line["description"],
                     tuple(normalize_id(i["raw_value"]) for i in line["identifiers"]), line["quantity_raw"], line["uom_raw"])
        if signatures[signature] > 1:
            line["source_validation"] = dict(status="vision_only", reason="Possible repeated extraction of the same source row; confirm each line.")
    company = _merge(records, ["buyer"])
    order = _merge(records, ["po_number"])
    _validate_order(order, pages)
    shipping = _merge(records, ["shipping", "address"])
    country = _merge(records, ["shipping", "country"])
    explicit_countries = {"IRELAND": "IE", "GREAT BRITAIN": "GB", "UNITED KINGDOM": "GB", "UK": "GB", "GB": "GB",
                          "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "USA": "US", "US": "US", "CANADA": "CA", "CA": "CA"}
    shipping.update(company=_merge(records, ["shipping", "company"])["value"],
                    postcode=_merge(records, ["shipping", "postcode"])["value"],
                    phone=_merge(records, ["shipping", "phone"])["value"], country_raw=country["value"],
                    country_code=explicit_countries.get((country["value"] or "").strip().upper()) if country["status"] == "extracted" else None,
                    country_status=country["status"])
    if not lines:
        warnings.append("No product or charge rows were observed; review the source document.")
    if failures or not any(record["document_type"] == "purchase_order" for record in records) or order["status"] != "extracted":
        for line in lines:
            line["source_validation"] = dict(status="vision_only", reason="The document or PO number is incomplete or uncertain.")
    with ModelMatcher(provider, catalog) as matcher:
        for line in lines:
            LOGGER.info("  Checking catalog candidates for %s", line["line_id"])
            matcher.match_line(line)
    extraction = dict(provider=provider.name, model=provider.model, pages=records, failures=failures,
                      usage=getattr(provider, "usage", [])[usage_start:])
    extraction["rendering"] = dict(requested_pdf_dpi=216, max_pixels=7_900_000,
                                   page_settings=[dict(page=page["page"], **page.get("rendering", {})) for page in pages],
                                   limitation="Large pages are rendered below the target DPI to stay within the pixel budget; image inputs retain supplied resolution.")
    if hasattr(provider, "metadata"):
        extraction["cascade"] = provider.metadata
        extraction["cascade"]["stage_counts"] = provider.stage_counts(usage_start)
    return dict(filename=filename, sha256=hashlib.sha256(raw).hexdigest(), source_type=source_type,
                catalog_authority="sample_catalog",
                architecture_version="pretrained_visual_text_cascade_v1" if hasattr(provider, "metadata") else "vision_catalog_v1",
                profile="vision",
                status="partial" if failures else "extracted", pages=pages, company=company, shipping=shipping,
                order_number=order, lines=lines, warnings=warnings,
                extraction=extraction)
