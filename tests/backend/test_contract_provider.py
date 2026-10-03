from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError
import pymupdf

from backend.contracts import (
    BoundingBox, ExtractionPayload, FieldObservation, parse_decimal, parsed_payload,
    strict_schema, validate_payload,
)
from backend.providers import OpenAIProvider, PROMPT_VERSION, RESPONSES_URL, SyntheticProvider
from backend.config import Settings
from backend.synthetic import (
    KINDS, MEDIA_TYPES, fixture_identity, fixture_payload, fixture_registry, generate_fixture,
)
from gate_a.contracts import ProductDocumentV1


def _payload():
    return fixture_payload().model_dump(mode="json")


def _observation(state="observed", value="2", alternatives=()):
    return FieldObservation(state=state, raw_value=value, source_label="Quantity",
                            evidence=({"page_number": 1, "region_reference": "line-1"},),
                            alternative_readings=alternatives)


def _response(payload=None, status="completed", content=None):
    if content is None:
        content = [{"type": "output_text", "text": json.dumps(payload or _payload())}]
    return {"id": "resp_test", "status": status,
            "output": [{"type": "message", "content": content}],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
                      "input_tokens_details": {"cached_tokens": 2},
                      "output_tokens_details": {"reasoning_tokens": 3}}}


def _provider(handler):
    return OpenAIProvider(api_key="offline-placeholder", enabled=True,
                          transport=httpx.MockTransport(handler))


def _extract(provider, media_type="application/pdf", page_count=1):
    return provider.extract(generate_fixture(media_type=media_type), media_type, page_count)


def test_new_payload_does_not_modify_gate_a_envelope():
    schema = ProductDocumentV1.model_json_schema()
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "rows" not in schema["properties"]
    assert fixture_payload().schema_version == "1.1"


def test_v12_continuation_group_is_evidence_bound_and_keeps_literal_values():
    payload = fixture_payload("continuation")
    assert payload.schema_version == "1.2"
    assert [(row.row_id, row.row_kind, row.row_role) for row in payload.rows] == [
        ("item-101", "product", "product_item"), ("description-cont-101", "unknown", "continuation"),
        ("item-202", "product", "product_item"), ("freight", "charge", "document_detail"),
        ("order-total", "total", "document_detail"), ("delivery-note", "note", "document_detail"),
        ("ambiguous-item", "unknown", "unknown")]
    assert payload.rows[1].description.raw_value == "20 inch width; 16′ length; zinc-coated steel"
    assert payload.rows[0].quantity.raw_value == "4" and payload.rows[0].unit_price.raw_value == "432.2000"
    assert payload.rows[2].quantity.raw_value is None and payload.rows[2].row_role == "product_item"
    assert {ref.region_reference for ref in payload.rows[0].evidence}.isdisjoint(
        {ref.region_reference for ref in payload.rows[1].evidence})


@pytest.mark.parametrize("change", ["independent_fields", "far_region", "wrong_group", "missing_role"])
def test_v12_rejects_unsupported_continuation_links(change):
    raw = fixture_payload("continuation").model_dump(mode="json")
    cont = raw["rows"][1]
    if change == "independent_fields": cont["quantity"] = deepcopy(raw["rows"][0]["quantity"])
    elif change == "far_region": raw["pages"][0]["regions"][1]["bbox"]["y0"] = 0.7
    elif change == "wrong_group": cont["item_group_id"] = "item-202"
    else: raw["rows"][2]["row_role"] = None
    with pytest.raises(ValidationError): validate_payload(raw, 1)


def test_payload_deeply_immutable_and_raw_strings_preserved():
    payload = fixture_payload()
    with pytest.raises(ValidationError):
        payload.rows[0].quantity.raw_value = "3"
    with pytest.raises(TypeError):
        payload.rows[0] = payload.rows[1]
    assert payload.rows[0].unit_price.raw_value == "12.50"
    result = parsed_payload(payload)
    assert result["rows"][0]["unit_price"]["value"] == "12.50"
    assert result["rows"][0]["quantity"]["value"] == "2"
    assert payload.rows[0].quantity.raw_value == "2"


def test_contract_preserves_large_varied_purchase_order_without_sample_row_assumptions():
    raw = _payload()
    template = deepcopy(raw["rows"][0])
    raw_values = [("0007", "1.2500", "0008.7500"), ("4", "1,234.50", "4,938.00"),
                  ("2.00", "0.075", "0.150"), ("1/2", "9.99", "5.00")]
    rows, regions = [], []
    for index in range(100):
        row = deepcopy(template)
        row_id = f"vendor-line-{index + 1:03d}"
        reference = {"page_number": 1, "region_reference": row_id}
        row["row_id"] = row_id
        row["evidence"] = [reference]
        ident = row["identifiers"][0]
        ident.update(raw_value=f"LOT-{index + 1:04d}", evidence=[reference])
        for field_name, value in (("description", f"Fictional varied product {index + 1}"),
                                  ("quantity", raw_values[index % len(raw_values)][0]),
                                  ("unit_price", raw_values[index % len(raw_values)][1]),
                                  ("line_total", raw_values[index % len(raw_values)][2])):
            row[field_name]["raw_value"] = value
            row[field_name]["evidence"] = [reference]
        row["unit"]["raw_value"] = "EA" if index % 2 == 0 else "BOX"
        row["unit"]["evidence"] = [reference]
        rows.append(row)
        regions.append({"region_reference": row_id,
                        "bbox": {"x0": 0.05, "y0": 0.25, "x1": 0.95, "y1": 0.30}})
    raw["rows"] = rows
    raw["pages"][0]["regions"].extend(regions)

    parsed = validate_payload(raw, page_count=1)
    assert len(parsed.rows) == 100
    assert [parsed.rows[index].quantity.raw_value for index in range(4)] == ["0007", "4", "2.00", "1/2"]
    assert [parsed.rows[index].unit_price.raw_value for index in range(4)] == ["1.2500", "1,234.50", "0.075", "9.99"]
    assert parsed.rows[99].identifiers[0].raw_value == "LOT-0100"


@pytest.mark.parametrize("name", ["selected_product_id", "catalog_id", "reviewer_correction"])
def test_catalog_and_review_fields_do_not_enter_observations(name):
    payload = _payload()
    payload["rows"][0][name] = "invented"
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)


@pytest.mark.parametrize("name", ["evidence", "alternative_readings", "source_label", "state", "raw_value"])
def test_provider_field_keys_must_be_explicit(name):
    payload = _payload()
    del payload["rows"][0]["quantity"][name]
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)


@pytest.mark.parametrize("name", ["source_role", "source_label", "evidence", "alternative_readings"])
def test_identifier_keys_must_be_explicit(name):
    payload = _payload()
    del payload["rows"][0]["identifiers"][0][name]
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)


@pytest.mark.parametrize("value", [2, 2.0, True])
def test_numeric_source_values_are_never_coerced(value):
    with pytest.raises(ValidationError):
        _observation(value=value)


@pytest.mark.parametrize("state,value,alternatives", [
    ("observed", None, ()), ("observed", "1", ("I",)),
    ("uncertain", None, ()), ("unreadable", "2", ()),
    ("not_present", "2", ()), ("not_applicable", None, ("2",)),
])
def test_invalid_five_state_combinations(state, value, alternatives):
    with pytest.raises(ValidationError):
        _observation(state, value, alternatives)


@pytest.mark.parametrize("state,value,alternatives", [
    ("observed", "002", ()), ("uncertain", "I", ("1",)),
    ("uncertain", None, ("1", "I")), ("unreadable", None, ()),
    ("not_present", None, ()), ("not_applicable", None, ()),
])
def test_all_five_observation_states_supported(state, value, alternatives):
    assert _observation(state, value, alternatives).raw_value == value


@pytest.mark.parametrize("raw", ["1,000", "1.000", "12,50", "1e3", "$12.00", "2 EA", "NaN", "Infinity"])
def test_ambiguous_or_unrecognized_decimal_parse_abstains(raw):
    observation = _observation(value=raw)
    parsed = parse_decimal(observation)
    assert parsed.status == "unresolved" and parsed.value is None
    assert observation.raw_value == raw


@pytest.mark.parametrize("raw,expected", [("002", "2"), ("12.50", "12.50"), (" 2 ", "2"), ("-2.5", "-2.5")])
def test_plain_decimal_parse_separate_from_literal(raw, expected):
    observation = _observation(value=raw)
    assert parse_decimal(observation).value == expected
    assert observation.raw_value == raw


def test_uncertain_numeric_field_not_parsed_as_fact():
    assert parse_decimal(_observation("uncertain", "2", ("3",))).value is None


@pytest.mark.parametrize("page_count", [0, 2, True, 1.0])
def test_source_page_coverage_cannot_be_silently_lost(page_count):
    with pytest.raises(ValueError):
        validate_payload(fixture_payload(), page_count)


def test_preconstructed_payload_is_revalidated_at_application_boundary():
    payload = fixture_payload().model_copy(update={"document_type": "invoice"})
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)
    payload = fixture_payload()
    bad_quantity = payload.rows[0].quantity.model_copy(update={"raw_value": 2})
    row = payload.rows[0].model_copy(update={"quantity": bad_quantity})
    unvalidated = payload.model_copy(update={"rows": (row, *payload.rows[1:])})
    with pytest.raises(ValidationError):
        validate_payload(unvalidated, 1)


@pytest.mark.parametrize("change", ["missing_region", "duplicate_page", "duplicate_row", "failed_page_reading"])
def test_evidence_graph_semantics(change):
    payload = _payload()
    if change == "missing_region":
        payload["rows"][0]["quantity"]["evidence"][0]["region_reference"] = "undeclared"
    elif change == "duplicate_page":
        payload["pages"].append(deepcopy(payload["pages"][0]))
    elif change == "duplicate_row":
        payload["rows"].append(deepcopy(payload["rows"][0]))
    else:
        payload["pages"][0].update(state="failed", uncertainty="Unreadable source.")
    with pytest.raises(ValidationError):
        validate_payload(payload, len(payload["pages"]))


def test_failed_second_page_recorded_and_marks_partial():
    payload = _payload()
    payload["pages"].append({"page_number": 2, "state": "failed", "regions": [],
                             "uncertainty": "Source page could not be read."})
    parsed = validate_payload(payload, 2)
    assert parsed.partial
    assert parsed.pages[1].state == "failed"


@pytest.mark.parametrize("box", [
    {"x0": 0.5, "y0": 0, "x1": 0.5, "y1": 1},
    {"x0": 0, "y0": 0.9, "x1": 1, "y1": 0.5},
    {"x0": -0.1, "y0": 0, "x1": 1, "y1": 1},
    {"x0": 0, "y0": 0, "x1": float("nan"), "y1": 1},
])
def test_normalized_region_geometry(box):
    with pytest.raises(ValidationError):
        BoundingBox(**box)


def test_unknown_row_requires_uncertainty_and_marks_partial():
    payload = _payload()
    payload["rows"][0]["row_kind"] = "unknown"
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)
    payload["rows"][0]["uncertainty"] = "Unresolved continuation."
    assert validate_payload(payload, 1).partial


def test_generated_row_reference_has_persistence_bound_without_truncating_source_values():
    payload = _payload()
    payload["rows"][0]["row_id"] = "r" * 121
    with pytest.raises(ValidationError):
        validate_payload(payload, 1)
    payload["rows"][0]["row_id"] = "r" * 120
    payload["rows"][0]["identifiers"][0]["raw_value"] = "literal-source-" * 100
    assert validate_payload(payload, 1).rows[0].identifiers[0].raw_value == "literal-source-" * 100


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("media_type", MEDIA_TYPES)
def test_synthetic_bytes_real_valid_deterministic_and_hash_registered(kind, media_type):
    source = generate_fixture(kind, media_type)
    if media_type == "application/pdf":
        with pymupdf.open(stream=source, filetype="pdf") as reader:
            assert len(reader) == 1
            assert "SYNTHETIC DEMO" in reader[0].get_text()
    else:
        image = Image.open(BytesIO(source))
        image.verify()
        assert image.size == (1400, 1800)
    assert fixture_identity(source, media_type) == kind
    generate_fixture.cache_clear()
    assert generate_fixture(kind, media_type) == source
    result = SyntheticProvider().extract(source, media_type, 1, kind)
    assert result.state == "succeeded" and result.synthetic
    assert result.actual_model == result.model == "synthetic-po-v1"
    assert result.payload.partial == (kind in {"partial", "continuation"})


@pytest.mark.parametrize("change", ["bytes", "name", "media", "pages"])
def test_fixture_provider_never_accepts_ordinary_or_modified_upload(change):
    source = generate_fixture()
    media_type, page_count, name = "application/pdf", 1, "purchase_order"
    if change == "bytes":
        source += b"changed"
    elif change == "name":
        name = "partial"
    elif change == "media":
        media_type = "image/png"
    else:
        page_count = 2
    result = SyntheticProvider().extract(source, media_type, page_count, name)
    assert result.payload is None and result.state in ("failed", "invalid_output")


def test_cached_synthetic_hash_registry_cannot_be_modified_by_callers():
    with pytest.raises(TypeError):
        fixture_registry()["a" * 64] = ("purchase_order", "application/pdf")


@pytest.mark.parametrize("kind", ["unsupported", "unknown"])
def test_explicit_unsupported_unknown_type_has_no_product_rows(kind):
    payload = fixture_payload(kind)
    assert payload.document_type == kind and payload.document_type_reason
    assert payload.rows == ()


def test_strict_schema_snapshot_all_properties_required_and_closed():
    schema = strict_schema("1.2")
    assert schema["properties"]["schema_version"]["enum"] == ["1.2"]
    legacy = strict_schema("1.1")
    assert legacy["properties"]["schema_version"]["enum"] == ["1.1"]
    assert "item_group_id" not in legacy["$defs"]["ExtractedRow"]["properties"]
    assert Settings(_env_file=None).extraction_model == "gpt-6-luna"

    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            assert "prefixItems" not in node
            assert not set(node) & {"allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else"}
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for item in node.values():
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)
    check(schema)
    assert len(json.dumps(schema)) < 50000

    def object_depth(node, depth=0):
        if isinstance(node, dict):
            if "$ref" in node:
                node = schema["$defs"][node["$ref"].rsplit("/", 1)[1]]
            depth += node.get("type") == "object"
            return max([depth, *(object_depth(item, depth) for key, item in node.items() if key != "$defs")])
        if isinstance(node, list):
            return max([depth, *(object_depth(item, depth) for item in node)])
        return depth

    assert object_depth(schema) <= 10
    assert sum(len(definition.get("properties", {})) for definition in schema["$defs"].values()) + len(schema["properties"]) < 5000


@pytest.mark.parametrize("enabled,key", [(False, "offline"), (True, None), (True, ""), (True, " ")])
def test_disabled_or_missing_key_makes_zero_network_requests(enabled, key):
    def fail_if_called(request):
        pytest.fail("Network transport must not be invoked.")
    provider = OpenAIProvider(api_key=key, enabled=enabled,
                              transport=httpx.MockTransport(fail_if_called))
    result = _extract(provider)
    assert result.state == "provider_not_configured" and not result.synthetic


@pytest.mark.parametrize("media_type", ["application/pdf", "image/png"])
def test_responses_request_shape_and_metadata(media_type):
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == RESPONSES_URL
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna" and body["store"] is False
        assert body["text"]["format"] == {"type": "json_schema", "name": "product_document_v1_2",
                                             "strict": True, "schema": strict_schema("1.2")}
        media = body["input"][0]["content"][0]
        if media_type == "application/pdf":
            assert media["type"] == "input_file" and media["filename"] == "source.pdf"
            assert media["file_data"].startswith("data:application/pdf;base64,")
        else:
            assert media["type"] == "input_image" and media["image_url"].startswith("data:image/png;base64,")
        return httpx.Response(200, json=_response(), headers={"x-request-id": "req_test"})
    provider = _provider(handler)
    result = _extract(provider, media_type)
    assert len(calls) == 1 and result.state == "succeeded"
    assert result.request_id == "req_test" and result.response_id == "resp_test"
    assert result.usage["input_tokens_details"] == {"cached_tokens": 2}
    assert result.usage["total_tokens"] == 30
    assert result.latency_ms >= 0 and result.prompt_version == PROMPT_VERSION
    assert result.model == provider.model and not result.synthetic


@pytest.mark.parametrize("outcome,body,state,error", [
    ("refusal", _response(content=[{"type": "refusal", "refusal": "sensitive source text"}]), "refused", "provider_refusal"),
    ("incomplete", _response(status="incomplete"), "incomplete", "provider_incomplete"),
    ("missing", _response(content=[]), "invalid_output", "provider_missing_or_multiple_output_text"),
    ("invalid", _response(content=[{"type": "output_text", "text": "secret raw invalid JSON"}]), "invalid_output", "provider_payload_validation_failed"),
    ("progress", _response(status="in_progress"), "unknown_outcome", "provider_unfinished_no_retry"),
])
def test_model_edge_outputs_retain_attempt_metadata_without_raw_errors(outcome, body, state, error):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body, headers={"x-request-id": "req_edge"})
    result = _extract(_provider(handler))
    assert len(calls) == 1 and result.state == state and result.error_code == error
    assert result.payload is None and result.usage["total_tokens"] == 30
    assert result.request_id == "req_edge" and result.response_id == "resp_test"
    assert "secret" not in repr(result) and "sensitive source" not in repr(result)


def test_semantically_wrong_page_count_and_out_of_graph_evidence_rejected():
    payload = _payload()
    payload["rows"][0]["evidence"][0]["region_reference"] = "invented"
    result = _extract(_provider(lambda request: httpx.Response(200, json=_response(payload))))
    assert result.state == "invalid_output"
    result = _extract(_provider(lambda request: httpx.Response(200, json=_response())), page_count=2)
    assert result.state == "invalid_output"


@pytest.mark.parametrize("status,expected", [(401, "failed"), (429, "failed"), (503, "unknown_outcome"), (408, "unknown_outcome"), (302, "failed")])
def test_http_outages_no_retries_no_provider_error_text(status, expected):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "offline-placeholder private source"}},
                              headers={"x-request-id": "req_outage", "Location": "https://untrusted.example"})
    result = _extract(_provider(handler))
    assert len(calls) == 1 and result.state == expected
    assert result.request_id == "req_outage"
    assert "private source" not in repr(result) and "offline-placeholder" not in repr(result)


def test_non_json_server_error_is_unknown_outcome():
    result = _extract(_provider(lambda request: httpx.Response(503, text="private upstream error")))
    assert result.state == "unknown_outcome"


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
def test_timeout_disconnect_unknown_outcome_and_no_hidden_retry(error):
    calls = []
    def handler(request):
        calls.append(request)
        raise error("offline-placeholder private source", request=request)
    result = _extract(_provider(handler))
    assert len(calls) == 1 and result.state == "unknown_outcome"
    assert result.error_code == "remote_outcome_unknown_no_retry"
    assert "offline-placeholder" not in repr(result) and "private source" not in repr(result)


def test_usage_and_request_identifiers_do_not_admit_freeform_strings():
    body = _response()
    body["id"] = "private source content"
    body["usage"].update(raw="private source", output_tokens="offline-placeholder")
    result = _extract(_provider(lambda request: httpx.Response(200, json=body,
                          headers={"x-request-id": "private source"})))
    assert result.state == "succeeded" and result.response_id is None and result.request_id is None
    assert "raw" not in result.usage and "output_tokens" not in result.usage


@pytest.mark.parametrize("status,content,state", [
    ("completed", None, "succeeded"),
    ("completed", [{"type": "refusal", "refusal": "offline refusal"}], "refused"),
    ("incomplete", None, "incomplete"),
    ("completed", [{"type": "output_text", "text": "invalid structured output"}], "invalid_output"),
])
def test_actual_response_model_retained_distinct_from_requested_alias(status, content, state):
    body = _response(status=status, content=content)
    body["model"] = "gpt-6.1-sol-offline-snapshot"
    result = _extract(_provider(lambda request: httpx.Response(200, json=body)))
    assert result.state == state
    assert result.model == "gpt-6-luna"
    assert result.actual_model == "gpt-6.1-sol-offline-snapshot"


@pytest.mark.parametrize("model", [None, "x" * 121, "private source content", 17])
def test_actual_model_absent_or_invalid_is_not_fabricated(model):
    body = _response()
    if model is not None:
        body["model"] = model
    result = _extract(_provider(lambda request: httpx.Response(200, json=body)))
    assert result.state == "succeeded" and result.model == "gpt-6-luna" and result.actual_model is None


def test_duplicate_model_output_json_keys_are_rejected_without_losing_receipt():
    serialized = json.dumps(_payload()).replace('"schema_version": "1.1"', '"schema_version": "1.0", "schema_version": "1.1"')
    body = _response(content=[{"type": "output_text", "text": serialized}])
    result = _extract(_provider(lambda request: httpx.Response(200, json=body)))
    assert result.state == "invalid_output" and result.error_code == "provider_payload_validation_failed"
    assert result.usage["total_tokens"] == 30
