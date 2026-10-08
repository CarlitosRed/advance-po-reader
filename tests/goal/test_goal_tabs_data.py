"""Three tabs on real API data: tiers, regions and the page picture come from the actual routes (no new route)."""
from io import BytesIO
import json
import os
import shutil
import subprocess

from PIL import Image
import pytest

from tests.goal.conftest import ROOT, PRODUCTS, ok, process, product_row

pytestmark = pytest.mark.goal


def test_goal_9_tabs_get_their_data_from_existing_routes_and_snapshots_have_regions(desk, tmp_path):
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the three-tab data check")
    probable = product_row(2, description=PRODUCTS[1]["description"], quantity="3")
    probable["identifiers"] = []
    probable["description"]["raw_value"] += ", code GOAL-002"
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2"),
            probable,
            product_row(3, description="Synthetic accessory to classify", quantity="1", kind="unknown"),
            product_row(4, description="Deliver to dock 4", kind="note"),
            product_row(5, description="Order total", kind="total")]
    result = process(desk, rows)
    assert [s["tier"] for s in result.suggestions] == ["certain", "probable", "uncertain"]
    # The picture of the page comes from the existing, tenant-scoped page route.
    response = desk.client.get(f"/documents/{result.source['id']}/pages/1")
    assert response.status_code == 200 and response.headers["content-type"].startswith("image/")
    width, height = Image.open(BytesIO(response.content)).size
    assert width > 100 and height > 100
    regions = {r["region_reference"]: r["bbox"] for r in result.result["extraction"]["pages"][0]["regions"]}
    for row in result.result["extraction"]["rows"]:
        box = regions[row["evidence"][0]["region_reference"]]
        assert 0 <= box["x0"] < box["x1"] <= 1 and 0 <= box["y0"] < box["y1"] <= 1
    expect = {"sure": ["line-1"], "check": ["line-2", "line-3"], "not": ["line-4", "line-5"]}
    seed = tmp_path / "tabs-data.json"
    seed.write_text(json.dumps({"result": result.result, "suggestions": result.suggestions, "expect": expect,
                                "page": {"width": width, "height": height}}), encoding="utf-8")
    completed = subprocess.run([node, str(ROOT / "tests/goal/tabs-data.cjs"), str(seed)], capture_output=True, text=True, timeout=30,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "three-tab real data passed" in completed.stdout
