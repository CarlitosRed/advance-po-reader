"""Header-based candidate recovery for unrecognized layouts.

This increases coverage without promoting an unvalidated layout to automatic
acceptance. Every recovered row requires confirmation, even for a known ID.
"""
import re


def recover_lines(pages, catalog):
    from .engine import compact, quantity, rows
    from .grounding import interpret_line
    from .retrieval import ProductRetriever
    output = []
    for page in pages:
        grouped = rows(page["words"])
        bands = []
        for group in grouped:
            qty_words = [w for w in group["words"] if compact(w["text"]) in ("qty", "quantity")]
            if len(qty_words) != 1:
                continue
            band = [w for w in page["words"] if group["top"]-7 <= w["top"] <= group["top"]+17]
            descriptions = [w for w in band if compact(w["text"]) in ("description", "productdescription", "name")]
            identifiers = [w for w in band if compact(w["text"]) in ("code", "number", "mpn", "sku", "id", "itemcode", "partno")]
            if len(descriptions) != 1 or len(identifiers) != 1:
                continue
            desc,identifier,qty = descriptions[0],identifiers[0],qty_words[0]
            identifier_x = min([identifier["x0"]]+[w["x0"] for w in band if abs(w["x0"]-identifier["x0"])<35 and compact(w["text"]) in ("item", "stock", "product", "part")])
            positions = [(identifier_x,"id"),(desc["x0"],"description"),(qty["x0"],"quantity")]
            positions += [(w["x0"],"other") for w in band if compact(w["text"]) in ("price","total","amount","uom","unit") and w["x0"]>qty["x0"]]
            positions.sort()
            if len({round(x) for x,_ in positions[:3]})<3:
                continue
            columns = {name:(max(0,x-6),positions[i+1][0]-6 if i+1<len(positions) else page["width"])
                       for i,(x,name) in enumerate(positions) if name != "other"}
            bottom=max(w["bottom"] for w in band)
            bands.append((bottom,columns))
        # Multiple tables may be legitimate; each needs its own tested adapter.
        if len(bands) != 1:
            continue
        bottom,columns = bands[0]
        last=None
        for group in grouped:
            if group["top"] <= bottom:
                continue
            cells={name:" ".join(w["text"] for w in group["words"] if left<=w["x0"]<right) for name,(left,right) in columns.items()}
            identifier=cells.get("id","")
            description=cells.get("description","")
            if re.fullmatch(r"[A-Z0-9-]{2,20}",identifier,re.I) and any(c.isdigit() for c in identifier) and description:
                entry=dict(line_id=f"line-{len(output)+1}",page=page["page"],vendor_id=identifier,customer_id=None,supplier_id=None,
                           description=description,quantity_raw=cells.get("quantity"),quantity=quantity(cells.get("quantity")),uom=None,
                           kind="product",evidence=[],extraction_method="generic_header_candidates")
                output.append(entry);last=entry
            elif last and not identifier and not cells.get("quantity") and description and group["top"]-last["evidence"][-1]["bbox"][3]<25:
                last["description"] += " " + description
            else:
                continue
            last["evidence"].append(dict(page=page["page"],text=group["text"],bbox=[min(w["x0"] for w in group["words"]),group["top"],max(w["x1"] for w in group["words"]),max(w["bottom"] for w in group["words"])]))
    retriever = ProductRetriever(catalog)
    try:
        for entry in output:
            interpret_line(entry,retriever)
            if entry["match"]["status"] == "matched":
                entry["match"].update(status="review_needed",reason="A known ID and compatible description were found, but this table layout has not been validated. Confirm the product number and quantity.")
            entry["cart"] = None
    finally:
        retriever.close()
    return output
