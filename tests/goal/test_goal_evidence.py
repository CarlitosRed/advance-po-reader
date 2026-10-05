"""Quantity/unit provenance cannot borrow another row, page or shared header."""
from copy import deepcopy
import json
from uuid import uuid4

from pydantic import ValidationError
import pytest

from backend.contracts import ExtractionPayload, validate_payload
from backend.providers import ProviderResult
from conftest import ok, payload, process, product_row, review_body, source_bytes

pytestmark = pytest.mark.goal


def two_rows():
    return [product_row(1, code="GOAL-001", description="Synthetic cobalt ladder", quantity="002"),
            product_row(2, code="GOAL-002", description="Synthetic vermilion bracket", quantity="3")]


@pytest.mark.parametrize("field", ["quantity", "unit"])
@pytest.mark.parametrize("outside", [False, True])
def test_goal_7_cell_region_requires_containment_in_its_own_row(field, outside):
    raw = payload(two_rows())
    raw["pages"][0]["regions"].append({"region_reference": "cell",
        "bbox": {"x0": .5, "y0": .20, "x1": .6, "y1": .26 if outside else .23}})
    raw["rows"][0][field]["evidence"] = [{"page_number": 1, "region_reference": "cell"}]
    if outside:
        with pytest.raises(ValidationError, match=f"{field} evidence must belong to the same row and page"):
            validate_payload(raw, 1)
    else:
        parsed = validate_payload(raw, 1)
        assert getattr(parsed.rows[0], field).raw_value == raw["rows"][0][field]["raw_value"]


def test_goal_7_region_name_does_not_establish_cell_containment():
    raw = payload(two_rows())
    raw["pages"][0]["regions"].append({"region_reference": "line-1.qty",
        "bbox": {"x0": .5, "y0": .28, "x1": .6, "y1": .30}})
    raw["rows"][0]["quantity"]["evidence"] = [{"page_number": 1, "region_reference": "line-1.qty"}]
    with pytest.raises(ValidationError, match="quantity evidence must belong to the same row and page"):
        validate_payload(raw, 1)


@pytest.mark.parametrize("field", ["quantity", "unit"])
@pytest.mark.parametrize("scope", ["another_row", "another_page", "shared_header", "mixed_refs"])
def test_goal_7_quantity_and_unit_reject_evidence_outside_same_row(field, scope):
    raw = payload(two_rows())
    wrong = {"page_number": 1, "region_reference": "line-2"}
    if scope == "another_page":
        other = deepcopy(raw["pages"][0])
        other["page_number"] = 2
        raw["pages"].append(other)
        wrong = {"page_number": 2, "region_reference": "line-1"}
    elif scope == "shared_header":
        wrong["region_reference"] = "header"
    raw["rows"][0][field]["evidence"] = [wrong]
    if scope == "mixed_refs":
        raw["rows"][0][field]["evidence"].insert(0, raw["rows"][0]["evidence"][0])
    with pytest.raises(ValidationError, match=f"{field} evidence must belong to the same row and page"):
        validate_payload(raw, len(raw["pages"]))


@pytest.mark.parametrize("version", ["1.1", "1.2"])
def test_goal_7_valid_same_row_quantity_unit_and_absent_fields_remain_literal(version):
    raw = payload(two_rows())
    raw["schema_version"] = version
    if version == "1.2":
        for row in raw["rows"]:
            row.update(row_role="product_item", item_group_id=row["row_id"], continuation_of=None)
    raw["rows"][1]["unit"].update(state="not_present", raw_value=None, evidence=[])
    parsed = validate_payload(raw, 1)
    assert parsed.rows[0].quantity.raw_value == "002"
    assert parsed.rows[0].unit.raw_value == "EA"
    assert parsed.rows[1].unit.raw_value is None


@pytest.mark.parametrize("field", ["quantity", "unit"])
def test_goal_7_service_revalidates_constructed_cross_row_provider_output(desk, monkeypatch, field):
    rows = two_rows()
    raw = payload(rows)
    raw["rows"][0][field]["evidence"] = raw["rows"][1]["evidence"]
    # Fixed JSON at the provider seam intentionally bypasses its own validation,
    # proving that the real application boundary still rejects invalid evidence.
    fixed_json = json.dumps(raw)
    def extract(*args, **kwargs):
        return ProviderResult(payload=ExtractionPayload.model_construct(**json.loads(fixed_json)),
            state="succeeded", model=desk.provider.model, prompt_version=desk.provider.prompt_version,
            schema_version="1.1", synthetic=True, usage={})
    monkeypatch.setattr(desk.provider, "extract", extract)
    source = ok(desk.client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        data={"vendor_id": desk.vendor["id"]}, files={"file": ("fictional.pdf", source_bytes(rows), "application/pdf")}))
    run = ok(desk.client.post(f"/documents/{source['id']}/runs", headers={"Idempotency-Key": uuid4().hex},
        json={"provider": "synthetic"}))
    failed = ok(desk.client.post(f"/runs/{run['id']}/process"))
    assert failed["state"] == "failed" and failed["outcome_code"] == "invalid_extraction_payload"
    assert ok(desk.client.get(f"/runs/{run['id']}/suggestions"))["suggestions"] == []
    assert not ok(desk.client.get(f"/runs/{run['id']}/summary"))["can_finish_review"]


@pytest.mark.parametrize("field", ["quantity", "unit"])
def test_goal_7_review_correction_rejects_other_row_evidence(desk, field):
    rows = two_rows()
    result = process(desk, rows)
    request = review_body(rows[0], "correct", field_name=field, new_value="004" if field == "quantity" else "BOX")
    request["evidence_reference"] = rows[1]["evidence"]
    endpoint = f"/runs/{result.run['id']}/reviews"
    rejected = desk.client.post(endpoint, json=request)
    assert rejected.status_code == 422 and rejected.json()["error"] == "review_evidence_outside_row"
    assert ok(desk.client.get(endpoint))["events"] == []
    request["evidence_reference"] = rows[0]["evidence"]
    ok(desk.client.post(endpoint, json=request))
    original = ok(desk.client.get(f"/runs/{result.run['id']}/result"))["extraction"]["rows"][0]
    assert original[field]["raw_value"] == rows[0][field]["raw_value"]
