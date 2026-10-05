"""The canonical exclusion action stays clear without breaking old clients."""
from backend.api_models import ReviewRequest


def test_legacy_exclusion_alias_is_deprecated_and_still_accepted():
    schema = ReviewRequest.model_json_schema()["properties"]["action"]
    canonical, legacy = schema["anyOf"]
    assert "not_a_product" in canonical["enum"]
    assert "not_product" not in canonical["enum"]
    assert legacy["const"] == "not_product" and legacy["deprecated"] is True
    for action in ("not_a_product", "not_product"):
        assert ReviewRequest(action=action, row_id="fictional-line", reviewer="Fictional QA",
            reason="Checked fixture", evidence_reference=[{"page_number": 1, "region_reference": "line"}]).action == action
