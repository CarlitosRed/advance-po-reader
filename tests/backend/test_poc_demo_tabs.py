"""The free demo's "every kind of line" sample must fill all three tabs and give every line a snapshot region."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from poc_demo_support import FIXTURES, payload_for  # noqa: E402

from backend.contracts import validate_payload  # noqa: E402


def _case():
    cases = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]
    return next(case for case in cases if case["id"] == "demo-all-tabs")


def test_all_tabs_sample_has_product_lines_and_printed_non_products_and_validates():
    payload = payload_for(_case())
    parsed = validate_payload(payload, 1)
    kinds = [row.row_kind for row in parsed.rows]
    assert kinds.count("product") == 5 and kinds.count("unknown") == 1
    assert {"note", "charge", "total"} <= set(kinds)
    assert len(set(row.row_id for row in parsed.rows)) == len(parsed.rows)


def test_every_line_has_its_own_region_inside_the_page_for_its_snapshot():
    payload = payload_for(_case())
    regions = {r["region_reference"]: r["bbox"] for r in payload["pages"][0]["regions"]}
    spots = set()
    for row in payload["rows"]:
        box = regions[row["evidence"][0]["region_reference"]]
        assert 0 <= box["x0"] < box["x1"] <= 1 and 0 <= box["y0"] < box["y1"] <= 1, row["row_id"]
        spots.add((box["y0"], box["y1"]))
    assert len(spots) == len(payload["rows"]), "two lines share one spot, so their snapshots would look the same"
