from backend.evaluation import EvaluationCase, ExpectedDocument, evaluate_cases
import pytest


def expectation(case_id="complete"):
    return ExpectedDocument(
        case_id=case_id,
        fields={"rows.0.quantity.raw_value": "006.00", "rows.0.quantity.state": "observed"},
        product_row_ids=("r1",),
        candidate_skus={"r1": "SKU-01"},
    )


def completed():
    return EvaluationCase(
        expected=expectation(),
        run={"id": "run1", "state": "completed", "review_state": "resolved"},
        extraction={"rows": [{"row_id": "r1", "row_kind": "product", "quantity": {"raw_value": "006.00", "state": "observed"}}]},
        suggestions=[{"row_id": "r1", "suggested_candidate_id": "p1", "candidates": [{"candidate_id": "p1", "sku": "SKU-01"}]}],
        reviews=[{"action": "approve", "row_id": "r1"}],
        attempts=[{"provider": "synthetic", "latency_ms": 2}],
    )


def report(cases, **kwargs):
    return evaluate_cases(cases, dataset_name="declared-fixtures", dataset_version="1", **kwargs)


def test_failures_and_partial_runs_remain_in_field_line_and_candidate_denominators():
    cases = [completed(),
             EvaluationCase(expectation("failure"), {"state": "failed"}, None),
             EvaluationCase(expectation("partial"), {"state": "partial"}, {"rows": []})]
    result = report(cases)
    assert result["completion"] == {"numerator": 1, "denominator": 3, "rate": 1 / 3}
    assert result["extraction_fidelity"]["literal_field_exactness"] == {"numerator": 2, "denominator": 6, "rate": 1 / 3}
    assert result["extraction_fidelity"]["product_line_recall"]["denominator"] == 3
    assert result["extraction_fidelity"]["components"]["quantity_exactness"]["denominator"] == 6
    assert result["candidate_recall_at_k"]["denominator"] == 3
    assert result["candidate_recall_at_k"]["numerator"] == 1
    assert result["cases"][1]["missing_product_rows"] == ["r1"]
    assert result["provider_cost"]["realized_cost_usd"] == "0"
    assert "not real model performance" in result["interpretation"]


@pytest.mark.parametrize("wrong_value", ["6.00", 6.0, 6, None])
def test_raw_literal_fidelity_never_coerces_printed_values(wrong_value):
    case = completed()
    case.extraction["rows"][0]["quantity"]["raw_value"] = wrong_value
    assert report([case])["extraction_fidelity"]["literal_field_exactness"]["numerator"] == 1


def test_candidate_recall_is_independent_of_suggestion_precision_and_bounded_at_k():
    case = completed()
    case.suggestions[0]["candidates"].insert(0, {"candidate_id": "wrong", "sku": "OTHER"})
    case.suggestions[0]["suggested_candidate_id"] = "wrong"
    result = report([case], candidate_k=1)
    assert result["candidate_recall_at_k"]["rate"] == 0
    assert result["suggestion_precision"]["rate"] == 0
    assert report([case], candidate_k=2)["candidate_recall_at_k"]["rate"] == 1


def test_usage_does_not_invent_realized_provider_cost_or_reviewer_time():
    case = completed()
    unknown = EvaluationCase(case.expected, case.run, case.extraction, case.suggestions, attempts=[
        {"provider": "openai", "latency_ms": 200, "usage": {"input_tokens": 20, "output_tokens": 10}},
        {"provider": "openai", "realized_cost_usd": "0.012345", "usage": {"total_tokens": 30}},
    ])
    result = report([unknown])
    assert result["provider_cost"]["realized_cost_usd"] is None
    assert result["provider_cost"]["known_reported_cost_usd"] == "0.012345"
    assert result["provider_cost"]["unknown_cost_attempt_count"] == 1
    assert result["provider_usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    assert result["review_burden"]["recorded_reviewer_seconds"] is None
    assert result["auto_accept"] == {"enabled": False, "coverage": 0, "precision": None}


def test_uncalled_or_synthetic_attempts_and_cached_usage_are_distinguished():
    case = completed()
    value = EvaluationCase(case.expected, case.run, case.extraction, attempts=[
        {"synthetic": True, "state": "succeeded", "latency_ms": 1},
        {"state": "provider_not_configured", "latency_ms": 0},
        {"provider": "openai", "realized_cost_usd": "0.1", "usage": {"input_tokens_details": {"cached_tokens": 4}}},
    ])
    result = report([value])
    assert result["provider_cost"]["external_attempt_count"] == 1
    assert result["provider_cost"]["realized_cost_usd"] == "0.1"
    assert result["provider_usage"]["cached_input_tokens"] == 4


def test_extra_rows_no_match_and_correction_counts_are_visible():
    case = completed()
    case.extraction["rows"].append({"row_id": "invented", "row_kind": "product"})
    case.reviews.append({"action": "correct", "row_id": "r1", "reviewer_seconds": 3})
    result = report([case])
    assert result["extraction_fidelity"]["extra_product_rows"] == 1
    assert result["review_burden"]["correction_events"] == 1
    assert result["review_burden"]["recorded_reviewer_seconds"] == 3


def test_empty_evaluation_returns_unknown_rates_without_claiming_accuracy():
    result = report([])
    assert result["completion"]["rate"] is None
    assert result["candidate_recall_at_k"]["rate"] is None
    assert result["suggestion_precision"]["rate"] is None


def test_duplicate_cases_or_prediction_labels_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        report([completed(), completed()])
    with pytest.raises(ValueError, match="independent"):
        report([completed()], evidence_kind="model_prediction")
    with pytest.raises(ValueError, match="positive"):
        report([completed()], candidate_k=0)
