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


def row_with_codes(*values, role="vendor_product_code"):
    data = fixture_payload().model_dump(mode="json")
    row = next(item for item in data["rows"] if item["row_kind"] == "product")
    template = row["identifiers"][0]
    row["identifiers"] = [{**template, "raw_value": value, "source_role": role, "source_label": "Part No."}
                          for value in values]
    row["description"]["raw_value"] = "Synthetic widget"
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
