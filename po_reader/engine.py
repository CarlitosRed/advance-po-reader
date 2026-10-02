"""Position-aware PO parsing with auditable regions and explicit review states."""
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation

import pdfplumber
from pypdf import PdfReader

from .catalog import CODE
from .grounding import interpret_line
from .retrieval import ProductRetriever
from .profiles import PROFILES


def compact(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def rows(words):
    groups = []
    for word in sorted(words, key=lambda w:(w["top"], w["x0"])):
        if not groups or abs(groups[-1]["top"] - word["top"]) > 3:
            groups.append(dict(top=word["top"], words=[]))
        groups[-1]["words"].append(word)
    for group in groups:
        group["words"].sort(key=lambda w:w["x0"])
        group["text"] = " ".join(w["text"] for w in group["words"])
    return groups


def region(page, bbox):
    x0, y0, x1, y1 = bbox
    selected = [w for w in page["words"] if x0*page["width"] <= w["x0"] < x1*page["width"] and
                y0*page["height"] <= w["top"] < y1*page["height"]]
    return dict(text="\n".join(r["text"] for r in rows(selected)), page=page["page"],
                bbox=[round(x0*page["width"],2), round(y0*page["height"],2), round(x1*page["width"],2), round(y1*page["height"],2)])


def field(evidence, reason=""):
    return dict(value=evidence["text"] or None, status="extracted" if evidence["text"] else "review_needed", evidence=evidence, reason=reason)


def quantity(value):
    try:
        # The inspected formats use a decimal point. A comma may mean either a
        # decimal or thousands separator; require review instead of guessing.
        if not isinstance(value,str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value.strip()):
            return None
        decimal = Decimal(value.strip())
        return str(decimal) if decimal.is_finite() and decimal > 0 else None
    except (InvalidOperation, AttributeError):
        return None


def read_pages(raw):
    independent = PdfReader(io.BytesIO(raw))
    if independent.is_encrypted and not independent.decrypt(""):
        raise ValueError("This PDF needs a password. Provide an unlocked local copy; the original is not changed.")
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if len(pdf.pages) > 50:
            raise ValueError("Please use a PDF of 50 pages or fewer for this prototype.")
        extracted = []
        for i,p in enumerate(pdf.pages):
            text = p.extract_text() or ""
            classification = "text_with_images" if text.strip() and p.images else "text_layer" if text.strip() else "image_only" if p.images else "empty_or_unsupported_text"
            extracted.append(dict(page=i+1,width=p.width,height=p.height,text=text,
                                  independent_text=independent.pages[i].extract_text() or "",words=p.extract_words(),
                                  image_count=len(p.images),classification=classification))
            p.close()
        return extracted


def parse_lines(pages, profile):
    output, last = [], None
    for page in pages:
        table = profile.get("next_table", profile["table"]) if page["page"] > 1 else profile["table"]
        y0, y1 = table[1]*page["height"], table[3]*page["height"]
        scale = page["width"] / 595
        for row in rows([w for w in page["words"] if y0 <= w["top"] < y1]):
            cells = {k:" ".join(w["text"] for w in row["words"] if a*scale <= w["x0"] < b*scale)
                     for k,(a,b) in profile["columns"].items()}
            if profile["id"] == "caulfield" and "Supplier No.:" in row["text"]:
                supplied = row["text"].split("Supplier No.:")[-1].strip()
                if last:
                    last["supplier_id"] = supplied
                    last["evidence"].append(dict(page=page["page"], text=row["text"], bbox=[25*scale, row["top"], 312*scale, max(w["bottom"] for w in row["words"])]))
                continue
            starter = cells.get(profile["start"], "")
            is_start = bool(quantity(starter)) if profile["start"] == "quantity" else bool(re.fullmatch(r"[A-Z0-9-]{2,20}", starter, re.I))
            qty = quantity(cells.get("quantity", ""))
            potential_row = is_start and bool(cells.get("description"))
            if profile["start"] == "quantity" and not is_start:
                potential_row = bool(starter and CODE.match(cells.get("description", "")))
            if potential_row:
                description = cells.get("description", "")
                vendor = cells.get("vendor", "")
                if profile["id"] == "huws":
                    first = description.split(" ", 1)
                    vendor = first[0] if CODE.fullmatch(first[0]) else ""
                    description = first[1] if vendor and len(first) > 1 else description
                last = dict(line_id=f"line-{len(output)+1}", page=page["page"], description=description,
                            vendor_id=vendor or None, customer_id=cells.get("customer") or None, supplier_id=None,
                            quantity_raw=cells.get("quantity"), quantity=qty, uom=cells.get("uom") or None,
                            kind="charge" if vendor.lower() == "sh" and description.lower() == "shipping" else "product",
                            evidence=[])
                output.append(last)
            elif last and cells.get("description") and not any(w["x0"] > 430*scale for w in row["words"]):
                last["description"] += " " + cells["description"]
            else:
                continue
            if last:
                last["evidence"].append(dict(page=page["page"], text=row["text"], bbox=[20*scale, row["top"], 580*scale, max(w["bottom"] for w in row["words"])]))
    return output


def analyze(raw, filename, catalog):
    pages = read_pages(raw)
    whole = compact("\n".join(p["text"] for p in pages))
    found = [p for p in PROFILES if all(a in whole for a in p["anchors"])]
    warnings = []
    result = dict(filename=filename, sha256=hashlib.sha256(raw).hexdigest(), catalog_authority="sample_catalog", architecture_version="retrieval_grounded_v1",
                  pages=pages, profile=None, company=None, shipping=None, order_number=None, lines=[], warnings=warnings)
    if len(found) != 1:
        warnings.append("This document layout has not been validated. Any recovered product rows are suggestions requiring confirmation. Company and shipping details need manual review.")
        from .generic import recover_lines
        result["lines"] = recover_lines(pages,catalog)
        if any(not p["text"].strip() for p in pages):
            warnings.append("At least one page has no extractable text and needs OCR or manual review.")
        return result
    profile = found[0]
    result["profile"] = profile["id"]
    first = pages[0]
    # An anchor match alone is insufficient if the layout moved.
    header_text = compact(region(first, profile["header"])["text"])
    if not all(a in header_text for a in profile["header_anchors"]):
        warnings.append("Recognized customer, but the table position differs from the inspected format. Review this layout manually.")
        from .generic import recover_lines
        result["lines"] = recover_lines(pages,catalog)
        return result
    for page in pages[1:]:
        if "next_header" not in profile or not all(a in compact(region(page, profile["next_header"])["text"]) for a in profile["header_anchors"]):
            warnings.append("An additional page has an unrecognized table layout. Automatic interpretation is disabled for this document.")
            from .generic import recover_lines
            result["lines"] = recover_lines(pages,catalog)
            return result
    company = field(region(first, profile["company"]))
    if company["value"]:
        company["value"] = company["value"].splitlines()[0]
    if profile["id"] == "dulux" and company["value"]:
        company["value"] = company["value"].split(" trading as ")[0]
    shipping_evidence = region(first, profile["shipping"])
    address = field(shipping_evidence, "Shipping fields come only from the delivery region.")
    shipping_text = shipping_evidence["text"]
    uk = re.search(r"\b(?:GIR\s?0AA|[A-Z]{1,2}[0-9][A-Z0-9]?\s?[0-9][A-Z]{2})\b", shipping_text, re.I)
    ie = re.search(r"\b[A-Z][0-9]{2}\s?[A-Z0-9]{4}\b", shipping_text, re.I)
    postcode = (ie or uk).group().upper() if (ie or uk) else None
    if postcode:
        postcode = postcode.replace(" ", "")
        postcode = postcode[:3] + " " + postcode[3:] if ie else postcode[:-3] + " " + postcode[-3:]
    country_match = re.search(r"\b(IRELAND|Great Britain|United Kingdom|UK)\b", shipping_text, re.I)
    country = {"ireland":"IE", "great britain":"GB", "united kingdom":"GB", "uk":"GB"}.get(country_match.group().lower()) if country_match else None
    address.update(postcode=postcode, country_code=country, country_raw=country_match.group() if country_match else None,
                   country_status="extracted" if country else "review_needed", phone=None)
    if profile["phone"]:
        address["phone_evidence"] = region(first, profile["phone"])
        address["phone"] = re.sub(r"^Tel:\s*", "", address["phone_evidence"]["text"], flags=re.I) or None
        address["phone_role"] = "customer_header" if profile["id"] == "ptf" else "delivery_or_branch_contact"
    else:
        address["phone_evidence"] = None
    if not shipping_text:
        address["reason"] = "The Deliver To section is blank. Specify a shipping address; no header or supplier address was substituted."
        address["phone"] = None
    if not country:
        warnings.append("Shipping country is not explicit in the delivery region. Confirm it; supplier country and currency are not used.")
    if profile["id"] == "selco":
        # Preserve the named company from its visible support-center block, not the branch label.
        company["reason"] = "Company name taken from the Selco Support Centre block; delivery is the Dudley branch."
    if any(p["image_count"] for p in pages):
        warnings.append("Embedded images may contain text absent from extraction. Review the page if a field is missing.")
    order = field(region(first, profile["order"]))
    if order["value"]:
        order["value"] = order["value"].splitlines()[0]
    result.update(company=company, shipping=address, order_number=order)
    result["lines"] = parse_lines(pages, profile)
    retriever = ProductRetriever(catalog)
    try:
        for line in result["lines"]:
            interpret_line(line,retriever)
            expected_ids = [c for c in [line.get("vendor_id"), line.get("supplier_id"), line["match"].get("product_id")] if c and CODE.fullmatch(c)]
            source_text = " ".join(p["independent_text"] for p in pages if any(e["page"] == p["page"] for e in line["evidence"]))
            source_codes = {c.upper() for c in CODE.findall(source_text)}
            if any(c.upper() not in source_codes for c in expected_ids):
                line["match"].update(status="review_needed", reason="The independent text reader did not corroborate a product ID. Review the source page.")
            line["cart"] = None
    finally:
        retriever.close()
    if order["value"] and compact(order["value"]) not in compact(first["independent_text"]):
        order["status"] = "review_needed"
        order["reason"] = "The text readers disagree about the order number. Check the original page; no characters were corrected."
    if not result["lines"]:
        warnings.append("No product rows were recognized. Review this document manually.")
    return result
