"""Measure the inspected sample corpus; no general accuracy claim."""
import json
import logging
from pathlib import Path

from po_reader.catalog import ROOT,load_catalog
from po_reader.engine import analyze
from tests.test_logic import EXPECTED

logging.getLogger("pdfminer").setLevel(logging.ERROR)
if not EXPECTED:
    raise SystemExit('Private independent expectations unavailable. See docs/agent-handoff.md.')
catalog=load_catalog()
report=dict(scope="Seven inspected PDFs also seed the provisional catalog. This is a regression measurement, not held-out accuracy.",
            documents=7,pages=8,catalog_products=len(catalog),expected_product_rows=23,extracted_product_rows=0,
            id_and_quantity_agreements=0,matched_without_manual_product_resolution=0,product_rows_needing_review=0,
            excluded_charges=0,retrieval_expected_id_hits=0,documents_detail=[])
for name,expected in EXPECTED.items():
    doc=analyze((ROOT/"data/originals"/name).read_bytes(),name,catalog)
    products=[r for r in doc["lines"] if r["kind"]=="product"]
    detail=dict(filename=name,profile=doc["profile"],rows=[])
    for index,row in enumerate(products):
        expected_id,expected_qty=expected[4][index]
        report["extracted_product_rows"]+=1
        report["id_and_quantity_agreements"]+=int((row["match"]["product_id"],row["quantity"])==(expected_id,expected_qty))
        report["retrieval_expected_id_hits"]+=int(expected_id in {h["product_id"] for h in row["retrieval"]["hits"]})
        report["matched_without_manual_product_resolution"]+=int(row["match"]["status"]=="matched")
        report["product_rows_needing_review"]+=int(row["match"]["status"]!="matched")
        detail["rows"].append(dict(id=row["match"]["product_id"],quantity=row["quantity"],status=row["match"]["status"],reason=row["match"]["reason"]))
    report["excluded_charges"]+=sum(r["kind"]=="charge" for r in doc["lines"])
    report["documents_detail"].append(detail)
destination=ROOT/"output/logic-evaluation.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k!="documents_detail"},indent=2))
