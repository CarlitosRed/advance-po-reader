"""Gate A contract checks. Every example is synthetic, with no source files."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from gate_a.contracts import (
    EvidenceReference,
    FieldObservation,
    IdentifierObservation,
    ObservationState,
    ParsedDecimal,
    ProductDocumentV1,
    ReviewState,
    RowKind,
    RunState,
    validate_review_transition,
    validate_run_transition,
)


EVIDENCE = {"page_number": 1, "region_reference": "synthetic-row-1/quantity"}
REFERENCES = {
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "source_document_id": "00000000-0000-4000-8000-000000000002",
    "run_id": "00000000-0000-4000-8000-000000000003",
}
ENVELOPE = {**REFERENCES, "schema_version": "1.0", "document_type": "purchase_order"}


def observed(raw_value: object = " 006.00 ", **extra: object) -> FieldObservation:
    return FieldObservation.model_validate(
        {"state": "observed", "raw_value": raw_value, "evidence": [EVIDENCE], **extra}
    )


def test_literal_source_spelling_survives_validation_and_json_round_trip() -> None:
    observation = observed()
    assert observation.raw_value == " 006.00 "
    assert FieldObservation.model_validate_json(observation.model_dump_json()) == observation


@pytest.mark.parametrize("raw_value", [6, 6.0, True, ["006.00"]])
def test_raw_values_are_strict_strings(raw_value: object) -> None:
    with pytest.raises(ValidationError):
        observed(raw_value)


def test_state_and_raw_value_must_be_explicit() -> None:
    with pytest.raises(ValidationError):
        FieldObservation.model_validate({"raw_value": None})
    with pytest.raises(ValidationError):
        FieldObservation.model_validate({"state": "not_present"})


@pytest.mark.parametrize("state", ["observed", "uncertain", "unreadable"])
def test_present_observations_require_evidence(state: str) -> None:
    with pytest.raises(ValidationError, match="page/region evidence"):
        FieldObservation(state=state, raw_value=None if state == "unreadable" else "006.00")


@pytest.mark.parametrize("page_number", [0, -1, 1.0, True, "1"])
def test_evidence_uses_a_strict_one_based_page(page_number: object) -> None:
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate({**EVIDENCE, "page_number": page_number})


@pytest.mark.parametrize("region_reference", ["", "   ", 1])
def test_evidence_requires_a_region(region_reference: object) -> None:
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate({**EVIDENCE, "region_reference": region_reference})


@pytest.mark.parametrize("raw_value", [None, "", "  "])
def test_observed_needs_a_literal_reading(raw_value: object) -> None:
    with pytest.raises(ValidationError):
        observed(raw_value)


def test_alternatives_force_uncertain_instead_of_observed() -> None:
    with pytest.raises(ValidationError, match="uncertain state"):
        observed("10O", alternative_readings=["100"])
    uncertain = FieldObservation(
        state="uncertain",
        raw_value=" 10O ",
        alternative_readings=("100", "I00"),
        evidence=(EvidenceReference(**EVIDENCE),),
    )
    assert uncertain.state == ObservationState.UNCERTAIN
    assert uncertain.raw_value == " 10O "
    assert uncertain.alternative_readings == ("100", "I00")


def test_uncertain_can_have_only_alternative_readings() -> None:
    uncertain = FieldObservation(
        state="uncertain", raw_value=None, alternative_readings=("100", "10O"), evidence=(EVIDENCE,)
    )
    assert uncertain.raw_value is None
    assert uncertain.alternative_readings == ("100", "10O")
    with pytest.raises(ValidationError, match="best reading or an alternative"):
        FieldObservation(state="uncertain", raw_value=None, evidence=(EVIDENCE,))


@pytest.mark.parametrize("alternative", [6, 6.0, "", "   "])
def test_alternative_readings_are_literal_nonempty_strings(alternative: object) -> None:
    with pytest.raises(ValidationError):
        FieldObservation.model_validate(
            {"state": "uncertain", "raw_value": None, "evidence": [EVIDENCE], "alternative_readings": [alternative]}
        )


@pytest.mark.parametrize("state", ["unreadable", "not_present", "not_applicable"])
def test_absent_and_unreadable_states_cannot_invent_values(state: str) -> None:
    evidence = [EVIDENCE] if state == "unreadable" else []
    observation = FieldObservation(state=state, raw_value=None, evidence=evidence)
    assert observation.raw_value is None
    with pytest.raises(ValidationError, match="cannot invent readings"):
        FieldObservation(state=state, raw_value="guessed", evidence=evidence)
    with pytest.raises(ValidationError, match="cannot invent readings"):
        FieldObservation(state=state, raw_value=None, evidence=evidence, alternative_readings=["guessed"])


def test_identifier_label_and_role_are_preserved_and_required() -> None:
    data = {
        "state": "observed",
        "raw_value": "0000-XO",
        "evidence": [EVIDENCE],
        "source_label": " Vendor Item # ",
        "source_role": "vendor_product_code",
    }
    identifier = IdentifierObservation.model_validate(data)
    assert identifier.raw_value == "0000-XO"
    assert identifier.source_label == " Vendor Item # "
    assert identifier.source_role == "vendor_product_code"
    for field in ("source_label", "source_role"):
        with pytest.raises(ValidationError):
            IdentifierObservation.model_validate({key: value for key, value in data.items() if key != field})
    unknown_role = IdentifierObservation.model_validate({**data, "source_label": None, "source_role": None})
    assert unknown_role.source_role is None
    with pytest.raises(ValidationError):
        IdentifierObservation.model_validate({**data, "canonical_product_id": "invented"})


def test_observations_and_nested_evidence_are_immutable() -> None:
    observation = observed()
    with pytest.raises(ValidationError, match="frozen"):
        observation.raw_value = "6"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        observation.evidence[0].region_reference = "rewritten"  # type: ignore[misc]
    assert isinstance(observation.evidence, tuple)
    with pytest.raises(ValidationError):
        observed(canonical_sku="not-an-observation")


def test_decimal_parse_is_separate_from_unchanged_source() -> None:
    observation = observed("006.00")
    parsed = ParsedDecimal(status="parsed", value="6.00", method="synthetic-dot-decimal-v1")
    assert parsed.value == "6.00"
    assert observation.raw_value == "006.00"
    assert "value" not in observation.model_dump()
    assert "raw_value" not in parsed.model_dump()
    assert ParsedDecimal.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize("value", [6, 6.0, True, "NaN", "Infinity", "1,234", "1e3", " 6.00 ", ""])
def test_parsed_value_must_be_a_plain_finite_decimal_string(value: object) -> None:
    with pytest.raises(ValidationError):
        ParsedDecimal.model_validate({"status": "parsed", "value": value, "method": "synthetic-v1"})


@pytest.mark.parametrize("value", ["0", "6.00", "006.00", "-0.50", "+2"])
def test_plain_decimal_strings_are_supported(value: str) -> None:
    assert ParsedDecimal(status="parsed", value=value, method="synthetic-v1").value == value


def test_parse_status_and_method_retain_unresolved_attempts() -> None:
    not_attempted = ParsedDecimal(status="not_attempted", value=None, method=None)
    unresolved = ParsedDecimal(status="unresolved", value=None, method="ambiguous-locale-v1")
    assert not_attempted.value is None
    assert unresolved.method == "ambiguous-locale-v1"
    invalid = [
        {"status": "parsed", "value": None, "method": "synthetic-v1"},
        {"status": "parsed", "value": "6", "method": None},
        {"status": "unresolved", "value": "1.234", "method": "ambiguous-locale-v1"},
        {"status": "unresolved", "value": None, "method": " "},
        {"status": "not_attempted", "value": "6", "method": None},
        {"status": "not_attempted", "value": None, "method": "synthetic-v1"},
    ]
    for data in invalid:
        with pytest.raises(ValidationError):
            ParsedDecimal.model_validate(data)


def test_v1_envelope_is_versioned_tenant_scoped_and_has_no_extraction_payload() -> None:
    envelope = ProductDocumentV1.model_validate(ENVELOPE)
    assert envelope.contract_name == "ProductDocument"
    assert envelope.schema_version == "1.0"
    assert envelope.document_type == "purchase_order"
    assert envelope.tenant_id == UUID(REFERENCES["tenant_id"])
    assert envelope.run_state == RunState.CREATED
    assert envelope.review_state == ReviewState.NOT_STARTED
    assert ProductDocumentV1.model_validate_json(envelope.model_dump_json()) == envelope
    for invalid in (
        {"schema_version": "2.0"},
        {"contract_name": "LegacyPageExtraction"},
        {"document_type": "invoice"},
        {"document_type": "unknown"},
        {"tenant_id": "synthetic-not-a-uuid"},
        {"extracted_lines": []},
        {"canonical_product_id": "not-an-observation"},
        {"review_state": "completed"},
        {"run_state": "resolved"},
    ):
        with pytest.raises(ValidationError):
            ProductDocumentV1.model_validate({**ENVELOPE, **invalid})
    for field in ENVELOPE:
        with pytest.raises(ValidationError):
            ProductDocumentV1.model_validate({key: value for key, value in ENVELOPE.items() if key != field})


@pytest.mark.parametrize("field", ["schema_version", "document_type"])
def test_envelope_requires_explicit_version_and_purchase_order_classification(field: str) -> None:
    with pytest.raises(ValidationError) as error:
        ProductDocumentV1.model_validate({key: value for key, value in ENVELOPE.items() if key != field})
    assert any(item["loc"] == (field,) and item["type"] == "missing" for item in error.value.errors())


def test_run_completion_does_not_resolve_review() -> None:
    envelope = ProductDocumentV1.model_validate({**ENVELOPE, "run_state": "completed"})
    assert envelope.review_state == ReviewState.NOT_STARTED
    reviewed = ProductDocumentV1.model_validate({**ENVELOPE, "run_state": "partial", "review_state": "in_progress"})
    assert reviewed.run_state == RunState.PARTIAL
    assert reviewed.review_state == ReviewState.IN_PROGRESS


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("created", "validating"),
        ("validating", "processing"),
        ("processing", "completed"),
        ("processing", "partial"),
        *((stage, terminal) for stage in ("created", "validating", "processing") for terminal in ("failed", "cancelled")),
    ],
)
def test_valid_run_transitions(current: str, target: str) -> None:
    assert validate_run_transition(current, target) is None


@pytest.mark.parametrize("terminal", ["completed", "partial", "failed", "cancelled"])
@pytest.mark.parametrize("target", list(RunState))
def test_terminal_runs_have_no_escape_or_in_place_reprocess(terminal: str, target: RunState) -> None:
    with pytest.raises(ValueError, match="invalid run transition"):
        validate_run_transition(terminal, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [("created", "completed"), ("created", "processing"), ("validating", "partial"), ("processing", "validating"), ("created", "created")],
)
def test_run_transitions_cannot_skip_or_reverse_stages(current: str, target: str) -> None:
    with pytest.raises(ValueError, match="invalid run transition"):
        validate_run_transition(current, target)


def test_run_and_review_transition_vocabularies_are_separate() -> None:
    assert validate_review_transition("not_started", "in_progress") is None
    assert validate_review_transition(ReviewState.IN_PROGRESS, ReviewState.RESOLVED) is None
    for current, target in (("not_started", "resolved"), ("resolved", "in_progress"), ("in_progress", "not_started")):
        with pytest.raises(ValueError):
            validate_review_transition(current, target)
    with pytest.raises(ValueError):
        validate_review_transition("completed", "resolved")
    with pytest.raises(ValueError):
        validate_run_transition("created", "resolved")


def test_row_vocabulary_keeps_non_product_and_unknown_kinds_distinct() -> None:
    assert {kind.value for kind in RowKind} == {"product", "charge", "tax", "subtotal", "total", "note", "unknown"}
