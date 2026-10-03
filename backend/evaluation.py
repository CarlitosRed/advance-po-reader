"""Inspectable offline evaluation; expectations must be independent of predictions.

This module does not contact a provider. Failed and partial runs remain in every
applicable denominator. Synthetic fixture metrics validate workflow mechanics,
not model performance or production acceptance thresholds.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExpectedDocument:
    """A frozen fixture specification or independently reviewed source label.

    Field paths use dot-separated object keys and numeric list indexes, for
    example ``rows.0.quantity.raw_value``. Values compare literally, including
    leading zeroes, decimal punctuation and observation states. Candidate keys
    are expected catalog SKUs; they are separate from extraction observations.
    """

    case_id: str
    fields: Mapping[str, Any]
    product_row_ids: tuple[str, ...]
    candidate_skus: Mapping[str, str] = field(default_factory=dict)
    expected_no_match_rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationCase:
    expected: ExpectedDocument
    run: Mapping[str, Any]
    extraction: Mapping[str, Any] | None
    suggestions: Sequence[Mapping[str, Any]] = ()
    reviews: Sequence[Mapping[str, Any]] = ()
    attempts: Sequence[Mapping[str, Any]] = ()


_MISSING = object()


def _at_path(document: Mapping[str, Any] | None, path: str) -> Any:
    cursor: Any = document
    for part in path.split("."):
        if isinstance(cursor, Mapping):
            cursor = cursor.get(part, _MISSING)
        elif isinstance(cursor, list) and part.isdigit() and int(part) < len(cursor):
            cursor = cursor[int(part)]
        else:
            return _MISSING
    return cursor


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _field_component(path: str) -> str:
    if ".identifiers." in path:
        return "identifier_label_role_exactness" if path.endswith(("source_label", "source_role")) else "identifier_literal_exactness"
    if ".quantity." in path:
        return "quantity_exactness"
    if ".unit_price." in path or ".line_total." in path:
        return "price_total_exactness"
    if ".unit." in path:
        return "unit_exactness"
    if path.startswith("document_type"):
        return "document_type_exactness"
    if path.startswith("document_number"):
        return "document_number_exactness"
    return "other_declared_field_exactness"


def _rows(document: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if document is None:
        return []
    return list(document.get("rows", []))


def _sku(candidate: Mapping[str, Any]) -> str | None:
    return candidate.get("sku") or candidate.get("product", {}).get("sku")


def evaluate_cases(
    cases: Sequence[EvaluationCase],
    *,
    dataset_name: str,
    dataset_version: str,
    evidence_kind: str = "synthetic_fixture_specification",
    candidate_k: int = 5,
) -> dict[str, Any]:
    """Return JSON-safe denominators, per-case evidence, and separated metrics.

    No expectation is inferred from the extracted response. Realized provider
    cost is reported only when attempts explicitly record it; token usage alone
    is never called a charge. Synthetic/test attempts cost zero externally.
    """
    if candidate_k < 1:
        raise ValueError("candidate_k must be positive")
    if evidence_kind not in {"synthetic_fixture_specification", "independently_reviewed"}:
        raise ValueError("predictions are not independent evaluation labels")
    ids = [case.expected.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case identifiers must be unique")

    counts: Counter[str] = Counter()
    component_total: Counter[str] = Counter()
    component_exact: Counter[str] = Counter()
    states: Counter[str] = Counter()
    outcome_codes: Counter[str] = Counter()
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []
    usage: Counter[str] = Counter()
    cost = Decimal("0")
    unknown_cost_attempts = 0
    external_attempts = 0
    reviewer_seconds: list[float] = []

    for case in cases:
        expected = case.expected
        state = str(case.run.get("state", "unknown"))
        states[state] += 1
        outcome_codes[str(case.run.get("outcome_code") or "none")] += 1
        field_checks = []
        for path, wanted in expected.fields.items():
            actual = _at_path(case.extraction, path)
            exact = actual is not _MISSING and actual == wanted and type(actual) is type(wanted)
            counts["fields"] += 1
            counts["exact_fields"] += exact
            component = _field_component(path)
            component_total[component] += 1
            component_exact[component] += exact
            field_checks.append({"path": path, "exact": exact, "missing": actual is _MISSING})

        observed_products = {
            str(row.get("row_id")) for row in _rows(case.extraction)
            if row.get("row_kind") == "product"
        }
        expected_products = set(expected.product_row_ids)
        counts["expected_product_rows"] += len(expected_products)
        counts["recalled_product_rows"] += len(expected_products & observed_products)
        counts["extra_product_rows"] += len(observed_products - expected_products)
        counts["observed_product_rows"] += len(observed_products)

        by_row = {str(suggestion.get("row_id")): suggestion for suggestion in case.suggestions}
        candidate_checks = []
        for row_id, wanted_sku in expected.candidate_skus.items():
            candidates = by_row.get(row_id, {}).get("candidates", [])[:candidate_k]
            found = wanted_sku in {_sku(candidate) for candidate in candidates}
            counts["candidate_expected_rows"] += 1
            counts["candidate_recalled_rows"] += found
            candidate_checks.append({"row_id": row_id, "expected_sku": wanted_sku, "present_at_k": found})

        for row_id, suggestion in by_row.items():
            selected_id = suggestion.get("selected_candidate_id") or suggestion.get("suggested_candidate_id")
            if selected_id:
                selected = next((candidate for candidate in suggestion.get("candidates", [])
                                 if candidate.get("candidate_id") == selected_id), None)
                counts["selected_suggestions"] += 1
                counts["correct_selected_suggestions"] += (
                    selected is not None and _sku(selected) == expected.candidate_skus.get(row_id)
                    and row_id in expected.candidate_skus
                )
        for row_id in expected.expected_no_match_rows:
            counts["expected_no_match_rows"] += 1
            suggestion = by_row.get(row_id, {})
            counts["correct_no_match_rows"] += suggestion.get("outcome") == "no_match"

        review_rows = {
            str(event["row_id"]) for event in case.reviews
            if event.get("row_id") in expected_products
            and event.get("action") in {"approve", "no_match", "acknowledge", "correct"}
        }
        counts["reviewed_product_rows"] += len(review_rows)
        counts["correction_events"] += sum(event.get("action") == "correct" for event in case.reviews)
        counts["resolved_documents"] += case.run.get("review_state") == "resolved"
        for event in case.reviews:
            if event.get("reviewer_seconds") is not None:
                reviewer_seconds.append(float(event["reviewer_seconds"]))

        for attempt in case.attempts:
            if attempt.get("latency_ms") is not None:
                latencies.append(float(attempt["latency_ms"]))
            attempt_usage = attempt.get("usage") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens"):
                value = attempt_usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] += value
            cached = (attempt_usage.get("input_tokens_details") or {}).get("cached_tokens")
            if type(cached) is int and cached >= 0:
                usage["cached_input_tokens"] += cached
            if attempt.get("synthetic") is True or attempt.get("provider") in {"synthetic", "test", "mock"}:
                continue
            if attempt.get("state") == "provider_not_configured":
                continue
            external_attempts += 1
            reported_cost = attempt.get("realized_cost_usd")
            try:
                parsed_cost = Decimal(str(reported_cost)) if reported_cost is not None else None
            except InvalidOperation:
                parsed_cost = None
            if parsed_cost is None or not parsed_cost.is_finite() or parsed_cost < 0:
                unknown_cost_attempts += 1
            else:
                cost += parsed_cost

        per_case.append({
            "case_id": expected.case_id,
            "run_id": case.run.get("id"),
            "state": state,
            "outcome_code": case.run.get("outcome_code"),
            "has_extraction": case.extraction is not None,
            "field_checks": field_checks,
            "candidate_checks": candidate_checks,
            "missing_product_rows": sorted(expected_products - observed_products),
            "extra_product_rows": sorted(observed_products - expected_products),
        })

    return {
        "report_version": "local-backend-evaluation.v1",
        "dataset": {"name": dataset_name, "version": dataset_version, "evidence_kind": evidence_kind},
        "interpretation": (
            "Synthetic workflow checks; these are not real model performance measurements."
            if evidence_kind == "synthetic_fixture_specification" else
            "Measurements on independently reviewed labels; applicability depends on this dataset."
        ),
        "document_count": len(cases),
        "run_states": dict(states),
        "outcome_codes": dict(outcome_codes),
        "completion": _metric(states["completed"], len(cases)),
        "partial": _metric(states["partial"], len(cases)),
        "failed_or_cancelled": _metric(states["failed"] + states["cancelled"], len(cases)),
        "extraction_fidelity": {
            "literal_field_exactness": _metric(counts["exact_fields"], counts["fields"]),
            "components": {component: _metric(component_exact[component], component_total[component])
                           for component in sorted(component_total)},
            "product_line_recall": _metric(counts["recalled_product_rows"], counts["expected_product_rows"]),
            "extra_product_rows": counts["extra_product_rows"],
        },
        "candidate_recall_at_k": {
            "k": candidate_k,
            **_metric(counts["candidate_recalled_rows"], counts["candidate_expected_rows"]),
        },
        "suggestion_precision": _metric(counts["correct_selected_suggestions"], counts["selected_suggestions"]),
        "no_match_recall": _metric(counts["correct_no_match_rows"], counts["expected_no_match_rows"]),
        "auto_accept": {"enabled": False, "coverage": 0, "precision": None},
        "review_burden": {
            "reviewed_product_rows": _metric(counts["reviewed_product_rows"], counts["expected_product_rows"]),
            "correction_events": counts["correction_events"],
            "resolved_documents": _metric(counts["resolved_documents"], len(cases)),
            "recorded_reviewer_seconds": sum(reviewer_seconds) if reviewer_seconds else None,
            "reviewer_time_event_count": len(reviewer_seconds),
        },
        "provider_latency_ms": {
            "measured_attempt_count": len(latencies),
            "sum": sum(latencies) if latencies else None,
            "mean": sum(latencies) / len(latencies) if latencies else None,
        },
        "provider_usage": dict(usage),
        "provider_cost": {
            "external_attempt_count": external_attempts,
            "unknown_cost_attempt_count": unknown_cost_attempts,
            "realized_cost_usd": str(cost) if not unknown_cost_attempts else None,
            "known_reported_cost_usd": str(cost),
            "basis": "explicit attempt cost records; synthetic attempts incur no external spend",
        },
        "cases": per_case,
    }
