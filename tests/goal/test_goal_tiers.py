from copy import deepcopy

import pytest

from tests.goal.conftest import PRODUCTS, ok, process, product_row, review_body

pytestmark = pytest.mark.goal


def test_goal_4_only_certain_lines_cannot_resolve_without_approval(desk):
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2")]
    result = process(desk, rows)
    suggestion, = result.suggestions
    assert suggestion["tier"] == "certain" and suggestion["approval_status"] == "needs_approval"
    request = {"action": "resolve", "reviewer": "Fictional reviewer", "reason": "Explicit finish"}
    response = desk.client.post(f"/runs/{result.run['id']}/reviews", json=request)
    assert response.status_code == 409
    assert result.summary["approved_products"] == []
    ok(desk.client.post(f"/runs/{result.run['id']}/page-counts", json={
        "page_number": 1, "source_sha256": result.source["sha256"], "product_count": 1,
        "source_discrepancy": False, "reviewer": "Fictional reviewer", "reason": "Counted the generated page"}))
    ok(desk.client.post(f"/runs/{result.run['id']}/reviews", json=review_body(
        rows[0], "approve", selected_candidate_id=suggestion["suggested_candidate_id"])))
    assert desk.client.post(f"/runs/{result.run['id']}/reviews", json=request).status_code == 201


@pytest.mark.parametrize("case", ["embedded", "description", "normalized", "alternate", "unreadable", "conflict", "short_conflict", "year_conflict", "unknown"])
def test_goal_5_only_literal_unconflicted_code_column_is_preselected(desk, case):
    row = product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2")
    expected = "probable"
    if case in {"embedded", "description"}:
        row["identifiers"] = []
        if case == "embedded":
            row["description"]["raw_value"] += ", code GOAL-001"
    elif case == "normalized":
        row["identifiers"][0]["raw_value"] = "GOAL001"
    elif case == "alternate":
        row["identifiers"][0]["state"] = "uncertain"
        row["identifiers"][0]["alternative_readings"] = ["GOAL-002"]
        expected = "uncertain"
    elif case == "unreadable":
        row["quantity"].update(state="unreadable", raw_value=None)
        expected = "uncertain"
    elif case == "conflict":
        row["description"]["raw_value"] += ", code GOAL-002"
        expected = "uncertain"
    elif case in {"short_conflict", "year_conflict"}:
        row["description"]["raw_value"] += ", code " + ("A123" if case == "short_conflict" else "2026")
        expected = "uncertain"
    else:
        row = product_row(1, description="Unclassified synthetic accessory", kind="unknown")
        expected = "uncertain"
    result = process(desk, [deepcopy(row)])
    suggestion, = result.suggestions
    assert suggestion["tier"] == expected
    assert suggestion["suggested_candidate_id"] is None
    assert suggestion["approval_status"] == "needs_approval"
    assert result.summary["approved_products"] == []
