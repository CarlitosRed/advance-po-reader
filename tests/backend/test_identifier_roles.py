"""Identifier roles: the prompt gives the vocabulary and certain is reachable (offline, synthetic data)."""
import json

import httpx
import pytest

from backend.catalog import CANONICAL_SKU_ROLES
from backend.contracts import validate_payload
from backend.providers import EXTRACTION_PROMPT, OpenAIProvider, PROMPT_VERSION
from backend.synthetic import fixture_payload, generate_fixture
from backend.tiers import confidence_tier


def payload_with_role(role, label="Vendor SKU"):
    data = fixture_payload().model_dump(mode="json")
    identifier = data["rows"][0]["identifiers"][0]
    identifier["source_role"], identifier["source_label"] = role, label
    return validate_payload(data, 1)


def first_row(payload):
    return next(row for row in payload.rows if row.row_kind == "product")


def suggestion(method, sku="SYN-001"):
    return {"outcome": "suggested", "method": method,
            "candidates": [{"candidate_id": "c1", "sku": sku}]}


def test_provider_sends_the_role_vocabulary_and_accepts_vendor_product_code():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        data = payload_with_role("vendor_product_code", "Part No.").model_dump(mode="json")
        return httpx.Response(200, json={
            "id": "resp_test", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data)}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
    provider = OpenAIProvider(api_key="offline-placeholder", enabled=True, transport=httpx.MockTransport(handler))
    result = provider.extract(generate_fixture(), "application/pdf", 1)
    assert result.state == "succeeded" and result.prompt_version == PROMPT_VERSION
    instructions = " ".join(sent[0]["instructions"].split())
    for role in CANONICAL_SKU_ROLES:
        assert f"- {role}:" in instructions
    assert "never the header text" in instructions and "line_number" in instructions
    identifier = first_row(result.payload).identifiers[0]
    assert (identifier.source_label, identifier.source_role) == ("Part No.", "vendor_product_code")


def test_prompt_keeps_label_literal_and_forbids_line_numbers_as_codes():
    flat = " ".join(EXTRACTION_PROMPT.split())
    assert "source_label is the literal printed column/field header text" in flat
    assert "Never use a line number, row sequence number, quantity or price column as a product code" in flat


@pytest.mark.parametrize("role", sorted(CANONICAL_SKU_ROLES))
def test_canonical_role_with_single_exact_match_is_certain(role):
    row = first_row(payload_with_role(role))
    assert confidence_tier(row, suggestion("exact"))[0] == "certain"


@pytest.mark.parametrize("role", ["Part No.", "Item ID", "vendor item number", "line_number", "other", None])
def test_header_text_or_noncode_role_is_never_certain(role):
    row = first_row(payload_with_role(role, "Part No."))
    assert confidence_tier(row, suggestion("trigram"))[0] == "probable"
    # Even if some lookup were exact, no canonical-role code means no literal code-column proof.
    assert confidence_tier(row, suggestion("exact"))[0] == "probable"


def test_certain_still_needs_literal_equality_and_unique_candidate():
    row = first_row(payload_with_role("vendor_product_code"))
    assert confidence_tier(row, suggestion("exact", sku="syn-001"))[0] != "certain"
    two = {**suggestion("exact"), "candidates": [{"candidate_id": "a", "sku": "SYN-001"},
                                                 {"candidate_id": "b", "sku": "SYN-001"}]}
    assert confidence_tier(row, two)[0] == "uncertain"


def row_with_codes(*values, role="vendor_product_code", description="Synthetic widget"):
    data = fixture_payload().model_dump(mode="json")
    row = next(item for item in data["rows"] if item["row_kind"] == "product")
    template = row["identifiers"][0]
    row["identifiers"] = [{**template, "raw_value": value, "source_role": role, "source_label": "Part No."}
                          for value in values]
    row["description"]["raw_value"] = description
    return next(item for item in validate_payload({**data, "rows": [
        item if item is not row else row for item in data["rows"]]}, 1).rows if item.row_kind == "product")


@pytest.mark.parametrize("codes", [("WER SYN-001", "SYN-001"), ("WER-SYN-001", "SYN-001"),
                                   ("WER/SYN-001", "SYN-001"), ("SYN-001", "SYN-001")])
def test_printed_vendor_prefix_plus_literal_sku_stays_certain(codes):
    assert confidence_tier(row_with_codes(*codes), suggestion("exact"))[0] == "certain"


@pytest.mark.parametrize("codes", [("WER SYN-001",),                      # no literal SKU among the codes
                                   ("SYN-001", "OTHER-77"),               # one literal + one different product
                                   ("SYN-001", "WER OTHER-77"),
                                   ("SYN-001", "XSYN-001"),               # substring, not a whole token
                                   ("SYN-001", "WER XSYN-001"),
                                   ("SYN-001", "SYN-0011"),
                                   ("SYN-001", "A1 SYN-001"),             # prefix holding digits is not a vendor prefix
                                   ("SYN-001", "SYN-001 WER")])           # SKU must be the trailing token
def test_prefix_relaxation_does_not_hide_a_different_product(codes):
    assert confidence_tier(row_with_codes(*codes), suggestion("exact"))[0] != "certain"


def test_different_code_is_uncertain_and_prefix_needs_exact_method():
    assert confidence_tier(row_with_codes("SYN-001", "OTHER-77"), suggestion("exact"))[0] == "uncertain"
    assert confidence_tier(row_with_codes("SYN-001", "WER SYN-001"), suggestion("trigram"))[0] == "probable"


# ---- description tokens: only evidence of a DIFFERENT product may veto -------------------------------------

def tier(description, known=None, method="exact", codes=("SYN-001",)):
    row = row_with_codes(*codes, description=description)
    return confidence_tier(row, suggestion(method), known)


@pytest.mark.parametrize("description", ["Widget 10MM", "Widget 250ML 100MIL", "Widget 12IN48IN10.5"])
@pytest.mark.parametrize("known", [None, set(), {"OTHERSKU77"}])
def test_measurement_like_description_token_does_not_veto(description, known):
    assert tier(description, known)[0] == "certain"
    assert "ignored" in tier(description, known)[1]


@pytest.mark.parametrize("description", ["Widget 10MM", "Widget 12IN48IN10.5", "Widget QQ77-ZZ"])
def test_description_token_equal_to_a_different_catalog_sku_still_vetoes(description):
    key = {"Widget 10MM": "10MM", "Widget 12IN48IN10.5": "12IN48IN105", "Widget QQ77-ZZ": "QQ77ZZ"}[description]
    assert tier(description, {key})[0] == "uncertain"
    assert tier(description, {key})[1].startswith("Code-column and description readings conflict")


@pytest.mark.parametrize("description", ["Widget WER SYN-001", "Widget WER-SYN-001", "Widget syn-001", "Widget SYN001"])
def test_description_token_that_is_the_candidate_sku_or_its_prefix_variant_does_not_veto(description):
    assert tier(description, None)[0] == "certain"
    assert tier(description, {"SYN001"})[0] == "certain"


def test_unrelated_code_shaped_token_vetoes_only_when_it_is_a_catalog_product():
    assert tier("Widget QQ77-ZZ", None)[0] == "uncertain"           # catalog unknown: stay strict
    assert tier("Widget QQ77-ZZ", {"QQ77ZZ"})[0] == "uncertain"     # it is another product
    unlisted = tier("Widget QQ77-ZZ", set())                        # catalog known: not any product
    assert unlisted[0] == "certain" and "ignored" in unlisted[1]


def test_labeled_other_code_is_not_waved_through_when_catalog_is_known():
    assert tier("Widget SKU: QQ77-ZZ", set())[0] == "uncertain"
    assert tier("Widget SKU: QQ77-ZZ", {"QQ77ZZ"})[0] == "uncertain"
    assert tier("Widget SKU: SYN-001", set())[0] == "certain"


def test_ignored_hints_are_reported_without_their_text():
    from backend.tiers import ignored_hint_evidence
    row = row_with_codes("SYN-001", description="Widget 10MM QQ77-ZZ WER SYN-001")
    found = ignored_hint_evidence(row, suggestion("exact"), set())
    assert {item["reason"] for item in found} == {"measurement", "not_a_catalog_code"}
    assert all(set(item) == {"kind", "extractor", "reason", "length"} for item in found)
    assert ignored_hint_evidence(row, {**suggestion("exact"), "candidates": []}, set()) == []


def test_ignored_hints_never_lift_the_core_certain_requirements():
    assert tier("Widget 10MM", set(), method="trigram")[0] == "probable"
    assert tier("Widget 10MM", {"OTHER77"}, codes=("SYN-001", "OTHER-77"))[0] == "uncertain"
    assert confidence_tier(row_with_codes("SYN-001", description="Widget 10MM"),
                           {**suggestion("exact"), "candidates": [{"candidate_id": "a", "sku": "SYN-001"},
                                                                   {"candidate_id": "b", "sku": "OTHER-77"}]},
                           set())[0] == "uncertain"


# ---- a second printed code beside the literal SKU conflicts only when it is another catalog product -------------

@pytest.mark.parametrize("other", ["99887", "ZZ-4451", "WER 777", "SYN", "001", "N-001", "syn 001-X"])
def test_second_code_that_is_not_a_catalog_sku_does_not_veto_a_literal_match(other):
    result = tier("Synthetic widget", set(), codes=("SYN-001", other))
    assert result[0] == "certain" and "ignored" in result[1]
    assert tier("Synthetic widget", set(), codes=(other, "SYN-001"))[0] == "certain"


@pytest.mark.parametrize("other", ["OTHER-77", "other 77", "Other77"])
def test_second_code_equal_to_a_different_catalog_sku_still_vetoes(other):
    assert tier("Synthetic widget", {"OTHER77"}, codes=("SYN-001", other))[0] == "uncertain"


def test_second_code_is_not_waved_through_without_catalog_info_or_literal_proof():
    assert tier("Synthetic widget", None, codes=("SYN-001", "99887"))[0] == "uncertain"      # catalog unknown
    assert tier("Synthetic widget", set(), codes=("WER SYN-001", "99887"))[0] != "certain"  # no literal SKU
    assert tier("Synthetic widget", set(), codes=("SYN-001", "99887"), method="trigram")[0] == "probable"
    assert tier("Synthetic widget", set(), codes=("SYN-001", "ÉÉ1234"))[0] == "uncertain"  # not checkable


def test_ignored_second_code_is_reported_without_its_text_and_is_a_lookup_key():
    from backend.tiers import hint_keys, ignored_hint_evidence
    row = row_with_codes("SYN-001", "99887", description="Synthetic widget")
    assert "99887" in hint_keys(row)
    found = ignored_hint_evidence(row, suggestion("exact"), set())
    assert found == [{"kind": "code_reading_ignored", "extractor": "code_column", "reason": "not_a_catalog_code", "length": 5}]
    assert ignored_hint_evidence(row, suggestion("exact"), {"99887"}) == []


# ---- review findings: catalog veto before prefix equivalence, unnormalizable readings, bounded readings -------

@pytest.mark.parametrize("codes", [("SYN-001", "WER-SYN-001"), ("SYN-001", "wer syn-001")])
def test_prefixed_form_that_is_a_catalog_sku_vetoes_before_prefix_equivalence(codes):
    assert tier("Synthetic widget", {"SYN001", "WERSYN001"}, codes=codes)[0] == "uncertain"
    assert tier("Synthetic widget", {"SYN001"}, codes=codes)[0] == "certain"      # not a catalog SKU: still the vendor prefix
    assert tier("Widget WER-SYN-001", {"SYN001", "WERSYN001"})[0] == "uncertain"
    assert tier("Widget WER-SYN-001", {"SYN001"})[0] == "certain"


@pytest.mark.parametrize("codes", [("ÉÉ1234", "ББ9999"), ("SYN-001", "ſer SYN-001"), ("SYN-001", "ſYN-001")])
def test_unnormalizable_readings_never_compare_equal_or_prefix_match(codes):
    sku = codes[0]
    assert confidence_tier(row_with_codes(*codes), suggestion("exact", sku), set())[0] == "uncertain"
    assert confidence_tier(row_with_codes(*codes), suggestion("exact", sku), None)[0] == "uncertain"


def test_unnormalizable_reading_is_reported_without_its_text():
    from backend.tiers import ignored_hint_evidence
    found = ignored_hint_evidence(row_with_codes("SYN-001", "ББ9999"), suggestion("exact"), set())
    assert found == [{"kind": "reading_unverifiable", "extractor": "code_column", "reason": "not_normalizable",
                      "length": 6}]


def test_row_with_too_many_readings_is_never_certain_and_contributes_no_lookup_keys():
    from backend.tiers import MAX_READINGS_PER_ROW, hint_keys, ignored_hint_evidence
    heavy = " ".join(f"SKU: ZX{number:04d}" for number in range(MAX_READINGS_PER_ROW + 1))
    row = row_with_codes("SYN-001", description=heavy)
    assert hint_keys(row) == set()
    assert confidence_tier(row, suggestion("exact"), set())[0] == "uncertain"
    assert ignored_hint_evidence(row, suggestion("exact"), set()) == [
        {"kind": "readings_not_checked", "reason": "too_many_readings"}]
