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

from tests.goal.conftest import ROOT, PRODUCTS, field, ok, process, product_row, review_body

pytestmark = pytest.mark.goal

EXTRA = [{"sku": "GOAL-010", "description": "Synthetic cobalt ladder long"},
         {"sku": "GOAL-011", "description": "Synthetic cobalt ladder short"},
         {"sku": "D6224-2", "description": "Synthetic anchor strap kit"},
         {"sku": "WERNER D6224-2", "description": "Synthetic anchor strap kit"},
         {"sku": "4801239", "description": "Synthetic teal hinge"}]

# A non-ASCII catalog code whose same-value alias is held under a customer role (the normalization key of such a value is empty).
UNICODE = {"sku": "ÉX-88", "description": "Synthetic unique amber latch", "aliases": [
    {"value": "ÉX-88", "source_role": "customer_item_number"}]}


ALIASES = {"sku": "GOAL-002", "description": PRODUCTS[1]["description"], "aliases": [
    {"value": "CUSTOM-77", "source_role": "customer_item_number"}, {"value": "OLD-77", "source_role": "vendor_sku"}]}


def _with_role(row, role, index=0):
    row["identifiers"][index]["source_role"] = role
    return row


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
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"], "products": [*EXTRA, ALIASES, UNICODE]}))
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
    two = product_row(15, code="GOAL-002", description=vermilion, quantity="1")
    two["identifiers"].append({**two["identifiers"][0], "raw_value": "GOAL-001"})
    result = process(desk, rows)
    # Alias and conflict lines go through a second fictional run (a page only has room for so many rows).
    more = [
        _with_role(product_row(10, code="CUSTOM77", description=vermilion, quantity="1"), "customer_item_number"),   # alias, written differently
        product_row(11, code="OLD-77", description=vermilion, quantity="1"),                      # vendor alias, exact: not the main code
        product_row(12, description=vermilion + " code ZZ-99", quantity="1"),                    # no code column, unmatched labeled token
        product_row(13, code="GOAL-002", description=vermilion + " GOAL-001", quantity="1"),     # description names another product
        _with_role(product_row(14, code="CUSTOM-77", description=vermilion, quantity="1"), "customer_item_number"), # alias, exact
        two,                                                                                      # two catalog codes printed: two candidates
        product_row(16, code="OLD77", description=vermilion, quantity="1"),                      # vendor alias, written differently
    ]
    second = process(desk, more)
    # Printed codes under customer roles (no customer alias exists for them) next to a description that names the same
    # product: the screen must never call identical values a mismatch.
    role = "customer_item_number"
    scoped = [
        _with_role(product_row(17, code="GOAL-002", description=vermilion + " code GOAL-002", quantity="1"), role),     # same code, found via the description
        _with_role(product_row(18, code="4801239", description="Synthetic teal hinge 4801239", quantity="1"), role),     # same, numeric hint
        _with_role(product_row(19, code="GOAL002", description=vermilion + " code GOAL-002", quantity="1"), role),     # same code written differently
        _with_role(product_row(20, code="CUST-5", description=vermilion + " code GOAL-002", quantity="1"), role),      # unrelated customer number
        _with_role(product_row(21, code="GOAL-002", description=vermilion, quantity="1"), role),                       # same code, found by name
        _with_role(product_row(22, code="GOAL-002", description=vermilion + " code GOAL-001", quantity="1"), role),    # description names another product
        product_row(23, code="ZZZ-9", description=vermilion + " code GOAL-002", quantity="1"),                         # vendor code really differs
        _with_role(product_row(24, code="GOAL-002", description=vermilion + " code ZZ-99", quantity="1"), role),       # unmatched labeled token
    ]
    third = process(desk, scoped)
    # Names and codes whose reason must stay neutral: an exact name with an unrelated customer-role identifier, a literally
    # equal non-ASCII alias, an ASCII alias under its role, a vendor alias, and a page with no identifier column at all.
    neighbours = [
        _with_role(product_row(25, code="CUST-5", description=vermilion, quantity="1"), role),                          # exact name, unrelated customer code
        _with_role(product_row(26, code="ÉX-88", description=UNICODE["description"], quantity="1"), role),         # non-ASCII, literally equal alias
        _with_role(product_row(27, code="CUSTOM-77", description="Synthetic unrelated gadget nobody sells", quantity="1"), role),  # ASCII alias, odd name
        _with_role(product_row(28, code="ÉX-88", description="Synthetic unrelated gadget nobody sells", quantity="1"), role),  # non-ASCII alias, odd name
        product_row(29, code="OLD-77", description=vermilion, quantity="1"),                                              # vendor alias, exact name
    ]
    fourth = process(desk, neighbours)
    bare = process(desk, [product_row(30, description=vermilion, quantity="1")], code_column=False)                      # no identifier column
    suggestions = [*result.suggestions, *second.suggestions, *third.suggestions, *fourth.suggestions, *bare.suggestions]
    by_row = {item["row_id"]: item for item in suggestions}
    seed = tmp_path / "reasons-data.json"
    seed.write_text(json.dumps({"rows": [*result.result["extraction"]["rows"], *second.result["extraction"]["rows"],
                                         *third.result["extraction"]["rows"], *fourth.result["extraction"]["rows"],
                                         *bare.result["extraction"]["rows"]],
                                "suggestions": suggestions}), encoding="utf-8")
    completed = _run(node, "reasons-data.cjs", str(seed))
    assert completed.returncode == 0, completed.stdout + completed.stderr + json.dumps(
        {key: (value["method"], value["tier"], value["tier_reason"], [c["sku"] for c in value["candidates"]]) for key, value in by_row.items()})
    assert "plain reasons on real data passed" in completed.stdout


def test_goal_9_reason_sentences_state_only_what_the_real_api_data_proves(desk, tmp_path):
    """Round-5 review findings and their controls, on real review-API data (fictional): an unsearched unknown row, a
    price note on a product row, a blank Code cell, a short code printed in the description, a normalized match."""
    node = _node()
    latch = "Synthetic ultramarine locking latch assembly"
    ok(desk.client.post("/catalog/import", json={"vendor_id": desk.vendor["id"],
                                                 "products": [{"sku": "77", "description": latch}]}))
    vermilion, role = PRODUCTS[1]["description"], "customer_item_number"
    gadget = "Synthetic unrelated gadget nobody sells"
    note = "Unit price may exclude tax; product classification is clear"
    priced = product_row(3, code="GOAL-002", description=vermilion, quantity="1")
    priced["uncertainty"] = note
    blank_cell = product_row(4, description=vermilion + " code GOAL-002", quantity="1")
    blank_cell["identifiers"] = [{**field(None, "line-4", "Code", state="not_present"), "source_role": "vendor_sku"}]
    crowded = product_row(10, code="X-0", description=vermilion, quantity="1")
    crowded["identifiers"] = [{**crowded["identifiers"][0], "raw_value": f"X-{index}"} for index in range(21)]
    rows = [
        product_row(1, code="GOAL-002", description=vermilion, quantity="1", kind="unknown"),     # never searched
        product_row(2, code="GOAL-002", description=vermilion, quantity="1"),                      # same data, product: found
        priced,                                                                                   # price note, product clear
        blank_cell,                                                                               # empty Code cell + description code
        product_row(5, description=vermilion + " code GOAL-002", quantity="1"),                  # no identifier entry at all
        product_row(6, description=latch + " code 77", quantity="1"),                            # short code in the description
        _with_role(product_row(7, code="CUST-5", description=latch, quantity="1"), role),        # name search, unrelated code
        product_row(8, description=gadget, quantity="1"),                                         # searched, nothing found
        product_row(9, code="goal-002", description=gadget, quantity="1"),                        # capitals only: normalized
        crowded,                                                                                  # 21 identifiers: search input too large
    ]
    result = process(desk, rows)
    seed = tmp_path / "reasons-truth.json"
    seed.write_text(json.dumps({"rows": result.result["extraction"]["rows"], "suggestions": result.suggestions}), encoding="utf-8")
    completed = _run(node, "reasons-truth.cjs", str(seed))
    assert completed.returncode == 0, completed.stdout + completed.stderr + json.dumps(
        {item["row_id"]: (item["method"], item["tier"], item["reason"], [c["sku"] for c in item["candidates"]]) for item in result.suggestions})
    assert "plain reasons truth regressions passed" in completed.stdout


def test_goal_9_every_reason_combination_is_checked_against_an_independent_oracle():
    completed = _run(_node(), "reasons-generated.cjs")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "24 sentences all reachable" in completed.stdout


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
