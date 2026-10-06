"""Plain reasons in Check and the optional Ignored lines tab.

The reason table is checked twice: against fixed, hand-built data (tests/goal/reasons.cjs, Node only) and against the
real suggestions the review API returns for fictional rows (tests/goal/reasons-data.cjs). A last test proves a review
reaches the summary and Finish without opening Ignored lines and without any Agree click.
"""
import json
import os
import shutil
import subprocess

import pytest

from conftest import ROOT, PRODUCTS, ok, process, product_row, review_body

pytestmark = pytest.mark.goal

EXTRA = [{"sku": "GOAL-010", "description": "Synthetic cobalt ladder long"},
         {"sku": "GOAL-011", "description": "Synthetic cobalt ladder short"},
         {"sku": "D6224-2", "description": "Synthetic anchor strap kit"},
         {"sku": "WERNER D6224-2", "description": "Synthetic anchor strap kit"}]


def _node():
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the plain reasons check")
    return node


def _run(node, script, *arguments):
    return subprocess.run([node, str(ROOT / "tests/goal" / script), *arguments], capture_output=True, text=True, timeout=30,
                          **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))


def test_goal_9_plain_reason_table_covers_every_case():
    completed = _run(_node(), "reasons.cjs")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "plain reasons passed" in completed.stdout


def test_goal_9_plain_reasons_match_what_the_real_review_api_returns(desk, tmp_path):
    node = _node()
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"], "products": EXTRA}))
    cobalt, vermilion = PRODUCTS[0]["description"], PRODUCTS[1]["description"]
    conflict = product_row(3, code="GOAL-001", description=cobalt + " GOAL-002", quantity="1")
    embedded = product_row(5, description=vermilion + ", code GOAL-002", quantity="1")
    rows = [
        product_row(1, description="Synthetic unrelated gadget nobody sells", quantity="1"),     # nothing matches
        product_row(2, code="GOAL002", description=vermilion, quantity="1"),                      # code written differently
        conflict,                                                                                 # code and description disagree
        product_row(4, description=vermilion, quantity="1"),                                      # name only
        embedded,                                                                                 # code inside the description
        product_row(6, description=cobalt, quantity="1"),                                         # look-alikes
        product_row(7, code="D6224-2X", description="Synthetic anchor strap", quantity="1"),     # vendor-prefixed twin
        product_row(8, code="GOAL-002", description=vermilion, quantity="1"),                     # control: certain, not in Check
    ]
    unclear = product_row(9, code="GOAL-002", description=vermilion, quantity="1")
    unclear["quantity"].update(state="uncertain")
    rows.append(unclear)                                                                          # part of the line is hard to read
    result = process(desk, rows)
    by_row = {item["row_id"]: item for item in result.suggestions}
    seed = tmp_path / "reasons-data.json"
    seed.write_text(json.dumps({"rows": result.result["extraction"]["rows"], "suggestions": result.suggestions}), encoding="utf-8")
    completed = _run(node, "reasons-data.cjs", str(seed))
    assert completed.returncode == 0, completed.stdout + completed.stderr + json.dumps(
        {key: (value["method"], value["tier"], value["tier_reason"], [c["sku"] for c in value["candidates"]]) for key, value in by_row.items()})
    assert "plain reasons on real data passed" in completed.stdout


def test_goal_9_a_review_finishes_without_opening_ignored_lines_or_any_agree_click(desk):
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2"),
            product_row(2, code="GOAL-002", description=PRODUCTS[1]["description"], quantity="3"),
            product_row(3, description="Deliver to dock 4", kind="note"),
            product_row(4, description="Freight and handling", kind="charge"),
            product_row(5, description="Order total", kind="total")]
    result = process(desk, rows)
    run = result.run["id"]
    # Before any answer the three printed non-product lines are not what is left to do.
    assert len(result.summary["document_details"]) == 3
    assert sorted(result.summary["pending_row_ids"]) == ["line-1", "line-2"]
    finish = {"action": "resolve", "reviewer": "Fictional reviewer", "reason": "Explicit finish"}
    assert desk.client.post(f"/runs/{run}/reviews", json=finish).status_code == 409
    for row, suggestion in zip(rows[:2], result.suggestions):
        ok(desk.client.post(f"/runs/{run}/reviews", json=review_body(row, "approve", selected_candidate_id=suggestion["suggested_candidate_id"])))
    summary = ok(desk.client.get(f"/runs/{run}/summary"))
    # Only product answers were given: no event touches a note, a charge or a total, and nothing is pending or blocking.
    events = ok(desk.client.get(f"/runs/{run}/reviews"))
    assert {event["row_id"] for event in events["events"] if event.get("row_id")} == {"line-1", "line-2"}
    assert summary["pending_row_ids"] == [] and summary["can_finish_review"] is True
    assert desk.client.post(f"/runs/{run}/reviews", json=finish).status_code == 201
    assert ok(desk.client.get(f"/runs/{run}"))["review_state"] == "resolved"
