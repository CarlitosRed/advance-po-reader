"""Actual PostgreSQL/API workflow checks on public synthetic bytes only.

Set PO_BACKEND_API_TEST_DATABASE_URL to an isolated loopback database named
gate_a_test_backend_* or orderlens_product_rows*. The fixture never deletes history or touches Gate A's
service/catalog databases. Unique tenant IDs keep reruns separate.
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app import create_app
from backend.config import Settings
from backend.models import ProcessingRun, ProviderAttempt, SourceDocument
from backend.providers import OpenAIProvider
from backend.synthetic import fixture_payload, generate_fixture

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-token-long-enough"
pytestmark = pytest.mark.postgresql


@pytest.fixture(scope="module")
def api_engine():
    value = os.environ.get("PO_BACKEND_API_TEST_DATABASE_URL")
    if not value:
        pytest.skip("isolated PostgreSQL API database is not configured")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith(("gate_a_test_backend_", "orderlens_product_rows")) or url.query):
        pytest.fail("API tests require a loopback isolated test database with no query overrides")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    config = Config(str(ROOT / "backend.alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api_settings(api_engine):
    return Settings(_env_file=None, database_url=SecretStr(api_engine.url.render_as_string(hide_password=False)),
                    local_api_token=SecretStr(TOKEN), openai_api_key=None,
                    storage_directory=ROOT / "data" / "demo-agent" / "tests" / uuid4().hex)


@pytest.fixture
def api_client(api_engine, api_settings):
    with TestClient(create_app(api_settings, engine=api_engine), base_url="http://127.0.0.1:8012",
                    headers={"X-Local-Token": TOKEN}) as client:
        yield client


def accepted(response, codes=(200, 201)):
    assert response.status_code in codes, response.text
    return response.json()


def scope(client, name="A", *, products=True):
    tenant = accepted(client.post("/tenants", json={"name": f"Synthetic API {name} {uuid4()}"}))
    client.headers["X-Tenant-ID"] = tenant["id"]
    vendor = accepted(client.post("/vendors", json={"name": f"Synthetic API vendor {name}"}))
    imported = None
    if products:
        imported = accepted(client.post("/catalog/import", json={"vendor_id": vendor["id"], "products": [
            {"sku": "SYN-001", "description": "Synthetic blue widget", "aliases": []},
            {"sku": "SYN-002", "description": "Synthetic red widget", "aliases": []},
        ]}))
    return tenant, vendor, imported


def upload(client, vendor, *, kind="purchase_order", media_type="application/pdf", key=None, content=None):
    content = generate_fixture(kind=kind, media_type=media_type) if content is None else content
    return client.post("/documents", data={"vendor_id": vendor["id"]},
        files={"file": ("../../untrusted-name.pdf", content, media_type)},
        headers={"Idempotency-Key": key or uuid4().hex})


def batch_upload_pdf(index: int) -> bytes:
    """Unique fictional source bytes for volume tests; never a provider fixture."""
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=(612, 792), invariant=1)
    document.setTitle(f"Synthetic volume-only PO {index:03d}")
    document.drawString(56, 720, "SYNTHETIC TEST ONLY - PURCHASE ORDER")
    document.drawString(56, 690, f"Fictional batch document {index:03d}")
    document.drawString(56, 660, "No extraction or provider request in this test.")
    document.showPage()
    document.save()
    return output.getvalue()


def create_run(client, source, *, provider="synthetic", fixture="purchase_order", key=None, authorization=None):
    return client.post(f"/documents/{source['id']}/runs", json={"provider": provider,
        "fixture_name": fixture, "external_authorization": authorization},
        headers={"Idempotency-Key": key or uuid4().hex})


def process(client, run):
    return accepted(client.post(f"/runs/{run['id']}/process"))


def result(client, run):
    return accepted(client.get(f"/runs/{run['id']}/result"))


def suggestions(client, run):
    return accepted(client.get(f"/runs/{run['id']}/suggestions"))["suggestions"]


def review(client, run, *, action, row=None, candidate=None, field=None, value=None, evidence=None):
    return client.post(f"/runs/{run['id']}/reviews", json={
        "action": action, "row_id": row["row_id"] if row else None,
        "reviewer": "Synthetic integration reviewer", "reason": "Inspected declared synthetic fixture",
        "evidence_reference": row["evidence"] if row and evidence is None else (evidence or []),
        "selected_candidate_id": candidate, "field_name": field, "new_value": value,
    })


def test_pdf_image_upload_retry_conflict_and_tenant_scoped_keys(api_client):
    client = api_client
    tenant_a, vendor_a, _ = scope(client, "upload-A")
    upload_key = uuid4().hex
    source_a = accepted(upload(client, vendor_a, key=upload_key))
    repeated = accepted(upload(client, vendor_a, key=upload_key))
    assert source_a["id"] == repeated["id"]
    assert source_a["page_count"] == 1
    assert source_a["media_type"] == "application/pdf"
    assert len(source_a["sha256"]) == 64
    assert "untrusted-name" not in json.dumps(source_a)
    assert upload(client, vendor_a, key=upload_key, media_type="image/png").status_code == 409
    image = accepted(upload(client, vendor_a, media_type="image/png"))
    assert image["id"] != source_a["id"]
    assert image["media_type"] == "image/png"
    assert image["width"] > 0 and image["height"] > 0
    tenant_b, vendor_b, _ = scope(client, "upload-B")
    source_b = accepted(upload(client, vendor_b, key=upload_key))
    assert source_b["id"] != source_a["id"]
    assert source_b["sha256"] == source_a["sha256"]
    assert client.get(f"/documents/{source_a['id']}/runs").status_code == 404
    client.headers["X-Tenant-ID"] = tenant_a["id"]
    assert create_run(client, source_b).status_code == 404
    assert client.get("/catalog", params={"vendor_id": vendor_b["id"]}).status_code == 404


def test_run_retry_reprocess_retains_attempts_results_and_previous_review(api_client):
    client = api_client
    _, vendor, _ = scope(client)
    source = accepted(upload(client, vendor))
    run_key = uuid4().hex
    first = accepted(create_run(client, source, key=run_key))
    duplicate = accepted(create_run(client, source, key=run_key))
    assert first["id"] == duplicate["id"]
    assert first["state"] == "created"
    assert result(client, first)["attempts"] == []
    assert create_run(client, source, key=run_key, provider="openai", fixture=None).status_code == 409
    first = process(client, first)
    assert first["state"] == "completed" and first["review_state"] == "not_started"
    initial = deepcopy(result(client, first))
    assert len(initial["attempts"]) == 1
    # A repeated process request is a replay of the terminal result, not a second attempt.
    assert process(client, first)["id"] == first["id"]
    assert result(client, first) == initial
    row = initial["extraction"]["rows"][0]
    accepted(review(client, first, action="correct", row=row, field="quantity", value="002"))
    second = accepted(create_run(client, source))
    assert second["id"] != first["id"]
    second = process(client, second)
    assert second["state"] == "completed"
    assert result(client, first) == initial
    assert result(client, second)["extraction"] == initial["extraction"]
    history = accepted(client.get(f"/documents/{source['id']}/runs"))
    runs = history["runs"] if isinstance(history, dict) else history
    assert {item["id"] for item in runs} == {first["id"], second["id"]}
    assert len(accepted(client.get(f"/runs/{first['id']}/reviews"))["events"]) == 1
    assert accepted(client.get(f"/runs/{second['id']}/reviews"))["events"] == []


def test_review_requires_every_line_in_set_approval_and_keeps_observations_immutable(api_client):
    client = api_client
    tenant, vendor, _ = scope(client)
    source = accepted(upload(client, vendor))
    run = process(client, accepted(create_run(client, source)))
    original = deepcopy(result(client, run))
    candidate_rows = suggestions(client, run)
    assert {item["row_id"] for item in candidate_rows} == {"line-1", "line-2"}
    assert all(item["outcome"] == "suggested" for item in candidate_rows)
    assert all(len(item["candidates"]) == 1 for item in candidate_rows)
    assert all(item["suggested_candidate_id"] == item["candidates"][0]["candidate_id"] for item in candidate_rows)
    assert review(client, run, action="resolve").status_code == 409
    row = original["extraction"]["rows"][0]
    assert review(client, run, action="approve", row=row, candidate=str(uuid4())).status_code in (409, 422)
    assert review(client, run, action="approve", row=row,
        candidate=candidate_rows[0]["candidates"][0]["candidate_id"],
        evidence=[{"page_number": 1, "region_reference": "invented-evidence"}]).status_code in (409, 422)
    correction = accepted(review(client, run, action="correct", row=row, field="quantity", value="002"))
    assert correction["old_value"] == {"field_name": "quantity", "value": "2"}
    assert correction["new_value"] == {"field_name": "quantity", "value": "002"}
    assert result(client, run) == original
    for item in candidate_rows:
        product = next(row for row in original["extraction"]["rows"] if row["row_id"] == item["row_id"])
        accepted(review(client, run, action="approve", row=product, candidate=item["candidates"][0]["candidate_id"]))
    accepted(review(client, run, action="resolve"))
    assert accepted(client.get(f"/runs/{run['id']}"))["review_state"] == "resolved"
    events = accepted(client.get(f"/runs/{run['id']}/reviews"))["events"]
    assert len(events) == 4
    assert all(event["reviewer"] and event["reason"] and event["created_at"] for event in events)
    assert result(client, run)["extraction"] == original["extraction"]
    tenant_b, vendor_b, _ = scope(client, "review-B")
    assert client.get(f"/runs/{run['id']}").status_code == 404
    assert client.get(f"/runs/{run['id']}/reviews").status_code == 404
    assert review(client, run, action="resolve").status_code == 404


@pytest.mark.parametrize("kind", ["unsupported", "unknown"])
def test_unsupported_unknown_sources_never_enter_catalog_matching(api_client, kind):
    client = api_client
    _, vendor, _ = scope(client, kind)
    source = accepted(upload(client, vendor, kind=kind))
    run = process(client, accepted(create_run(client, source, fixture=kind)))
    assert result(client, run)["extraction"]["document_type"] == kind
    assert run["outcome_code"] in {"unsupported_document_type", "needs_classification"}
    assert suggestions(client, run) == []


def test_partial_uncertainty_is_preserved_and_review_stays_unresolved(api_client):
    client = api_client
    _, vendor, _ = scope(client, "partial")
    source = accepted(upload(client, vendor, kind="partial"))
    run = process(client, accepted(create_run(client, source, fixture="partial")))
    assert run["state"] == "partial" and run["review_state"] != "resolved"
    value = result(client, run)["extraction"]
    identifier = value["rows"][0]["identifiers"][0]
    assert identifier["raw_value"] == "SYN-00I" and identifier["state"] == "uncertain"
    assert identifier["alternative_readings"] == ["SYN-001"]
    assert review(client, run, action="resolve").status_code == 409
    assert {item["row_id"] for item in suggestions(client, run)} == {"line-1", "line-2"}


def test_explicit_exclusion_and_sequential_corrections_are_append_only(api_client):
    client = api_client
    _, vendor, _ = scope(client, "no-match", products=False)
    source = accepted(upload(client, vendor))
    run = process(client, accepted(create_run(client, source)))
    original = result(client, run)
    assert all(item["outcome"] == "no_match" and item["candidates"] == [] for item in suggestions(client, run))
    row = original["extraction"]["rows"][0]
    first_correction = accepted(review(client, run, action="correct", row=row, field="quantity", value="002"))
    second_correction = accepted(review(client, run, action="correct", row=row, field="quantity", value="003"))
    assert second_correction["old_value"] == first_correction["new_value"]
    assert second_correction["new_value"] == {"field_name": "quantity", "value": "003"}
    assert review(client, run, action="resolve").status_code == 409
    for row in original["extraction"]["rows"]:
        if row["row_kind"] == "product":
            assert review(client, run, action="no_match", row=row).status_code == 422
            accepted(review(client, run, action="not_a_product", row=row))
    accepted(review(client, run, action="resolve"))
    assert result(client, run) == original
    events = accepted(client.get(f"/runs/{run['id']}/reviews"))["events"]
    assert len(events) == 5
    assert sum(event["action"] == "correct" for event in events) == 2
    assert review(client, run, action="correct", row=original["extraction"]["rows"][0], field="quantity", value="4").status_code == 409


def test_cancellation_and_disabled_provider_do_not_substitute_extraction(api_client):
    client = api_client
    _, vendor, _ = scope(client, "cancel")
    source = accepted(upload(client, vendor))
    cancelled = accepted(create_run(client, source))
    cancelled = accepted(client.post(f"/runs/{cancelled['id']}/cancel"))
    assert cancelled["state"] == "cancelled"
    assert process(client, cancelled)["state"] == "cancelled"
    assert result(client, cancelled)["attempts"] == []
    assert result(client, cancelled)["extraction"] is None
    disabled = process(client, accepted(create_run(client, source, provider="openai", fixture=None)))
    assert disabled["state"] == "failed"
    assert disabled["outcome_code"] == "provider_not_configured"
    assert result(client, disabled)["extraction"] is None
    assert suggestions(client, disabled) == []
    # Valid source bytes are necessary but not sufficient for a fixture claim.
    ordinary = accepted(upload(client, vendor, content=generate_fixture() + b"\n%valid-nonfixture-tail"))
    mismatched = process(client, accepted(create_run(client, ordinary)))
    assert mismatched["state"] == "failed"
    assert mismatched["outcome_code"] == "synthetic_fixture_mismatch"
    assert result(client, mismatched)["extraction"] is None


def test_mock_provider_still_requires_affirmative_source_specific_authorization(api_engine, api_settings):
    calls = []

    def forbidden(request):
        calls.append(request)
        raise AssertionError("an unauthorized source must not reach the provider")

    provider = OpenAIProvider(api_key="fake-offline-test-key", enabled=True, transport=httpx.MockTransport(forbidden))
    with TestClient(create_app(api_settings, engine=api_engine, provider=provider),
                    base_url="http://127.0.0.1:8012", headers={"X-Local-Token": TOKEN}) as client:
        _, vendor, _ = scope(client, "no-authorization")
        source = accepted(upload(client, vendor))
        run = process(client, accepted(create_run(client, source, provider="openai", fixture=None)))
        assert run["outcome_code"] == "external_processing_authorization_required"
        assert result(client, run)["attempts"] == []
        authorization = {"authorized": True, "source_sha256": "0" * 64,
                         "authorized_by": "Synthetic reviewer", "policy_reference": "Offline test only",
                         "reason": "Wrong source hash must not authorize transfer"}
        assert create_run(client, source, provider="openai", fixture=None, authorization=authorization).status_code == 422
        authorization.update(authorized=False, source_sha256=source["sha256"])
        assert create_run(client, source, provider="openai", fixture=None, authorization=authorization).status_code == 422
    assert calls == []


def test_authorized_openai_workflow_with_mocked_response_and_shared_human_summary(api_engine,api_settings):
    calls=[]
    payload=fixture_payload().model_dump(mode="json")
    payload["schema_version"] = "1.2"
    for row in payload["rows"]:
        row.update(item_group_id=row["row_id"] if row["row_kind"] == "product" else None,
                   row_role="product_item" if row["row_kind"] == "product" else "document_detail",
                   continuation_of=None)
    def transport(request):
        calls.append(request)
        assert request.url=="https://api.openai.com/v1/responses"
        return httpx.Response(200,headers={"x-request-id":"req_offline_demo"},json={
            "id":"resp_offline_demo","status":"completed","model":"offline-test-model",
            "usage":{"input_tokens":100,"output_tokens":200},
            "output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(payload)}]}]})
    provider=OpenAIProvider(api_key="fake-offline-only-key",enabled=True,transport=httpx.MockTransport(transport))
    settings=api_settings.model_copy(update={"live_processing_enabled":True,"openai_api_key":SecretStr("fake-offline-only-key")})
    with TestClient(create_app(settings,engine=api_engine,provider=provider),base_url="http://127.0.0.1:8014",
                    headers={"X-Local-Token":TOKEN}) as client:
        _,vendor,_=scope(client,"offline-authorized-demo")
        source=accepted(upload(client,vendor))
        authorization={"authorized":True,"source_sha256":source["sha256"],"authorized_by":"Fictional offline QA",
            "policy_reference":"Synthetic mocked provider only","reason":"Validate complete adapter wiring without an external request"}
        run=accepted(create_run(client,source,provider="openai",fixture=None,authorization=authorization))
        path=f"/runs/{run['id']}"
        readiness=accepted(client.get(path+"/readiness"))
        assert readiness["can_process"] is True and readiness["attempt_count"]==0
        completed=process(client,run)
        assert completed["state"]=="completed" and completed["review_state"]=="not_started"
        value=result(client,run)
        assert value["extraction"]==payload and len(value["attempts"])==1
        assert value["attempts"][0]["request_id"]=="req_offline_demo"
        summary=accepted(client.get(path+"/summary"))
        assert summary["approved_products"]==[] and len(summary["pending_row_ids"])==2
        assert not accepted(client.get(path+"/readiness"))["can_process"]
        assert process(client,run)["state"]=="completed" and len(calls)==1


def test_continuation_fixture_one_logical_product_blank_quantity_details_and_unknown_blocker(api_client):
    client = api_client
    tenant, vendor, products = scope(client, "continuation", products=True)
    content = generate_fixture("continuation")
    source = accepted(upload(client, vendor, kind="continuation"))
    run = process(client, accepted(create_run(client, source, fixture="continuation")))
    assert run["state"] == "partial" and run["outcome_code"] == "review_required"
    extraction = result(client, run)["extraction"]
    original_rows = deepcopy(extraction["rows"])
    assert extraction["schema_version"] == "1.2" and len(original_rows) == 7
    root, continuation, blank_quantity, *_ = original_rows
    assert root["item_group_id"] == continuation["item_group_id"] == "item-101"
    assert continuation["row_role"] == "continuation" and continuation["continuation_of"] == root["row_id"]
    assert root["description"]["raw_value"] == "Synthetic blue widget adjustable support arm"
    assert continuation["description"]["raw_value"] == "20 inch width; 16′ length; zinc-coated steel"
    assert root["quantity"]["raw_value"] == "4" and root["unit"]["raw_value"] == "EA"
    assert root["unit_price"]["raw_value"] == "432.2000" and root["line_total"]["raw_value"] == "1728.8000"
    assert blank_quantity["row_role"] == "product_item" and blank_quantity["quantity"]["raw_value"] is None
    suggestions_by_id = {item["row_id"]: item for item in suggestions(client, run)}
    assert set(suggestions_by_id) == {"item-101", "item-202", "ambiguous-item"}
    assert all(suggestions_by_id[row_id]["candidates"] for row_id in ("item-101", "item-202"))
    assert suggestions_by_id["ambiguous-item"]["tier"] == "uncertain"
    events = accepted(client.get(f"/runs/{run['id']}/reviews"))["events"]
    assert not events
    summary = accepted(client.get(f"/runs/{run['id']}/summary"))
    assert summary["summary_policy_version"] == "review-summary-v2"
    assert summary["pending_row_ids"] == ["item-101", "item-202", "ambiguous-item"]
    assert len(summary["document_details"]) == 4
    assert {item["row_kind"] for item in summary["document_details"]} == {"unknown", "charge", "total", "note"}
    url=f"/runs/{run['id']}/reviews"
    # A continuation is inspectable but cannot be separately approved or acknowledged.
    assert client.post(url,json={"action":"acknowledge","row_id":continuation["row_id"],
        "reviewer":"Synthetic QA","reason":"Fixture inspected","evidence_reference":continuation["evidence"]}).status_code == 422
    for index, item in ((0, root), (1, blank_quantity)):
        chosen = suggestions_by_id[item["row_id"]]["candidates"][0]["candidate_id"]
        accepted(review(client, run, action="approve", row=item, candidate=chosen))
    summary = accepted(client.get(f"/runs/{run['id']}/summary"))
    first = summary["approved_products"][0]
    assert first["continuation_descriptions"][0]["raw_description"] == continuation["description"]["raw_value"]
    assert first["quantity"] == "4" and first["unit"] == "EA"
    assert summary["pending_row_ids"] == ["ambiguous-item"] and not summary["can_finish_review"]
    assert accepted(client.get(f"/runs/{run['id']}/result"))["extraction"]["rows"] == original_rows


@pytest.mark.parametrize("behavior,attempt_state", [("refusal", "refused"), ("timeout", "unknown_outcome"), ("invalid", "invalid_output")])
def test_offline_mock_provider_failure_attempt_is_sanitized_and_never_retried(api_engine, api_settings, behavior, attempt_state):
    calls = []
    secret_marker = "PRIVATE-SOURCE-AND-FAKE-KEY-MUST-NOT-BE-LOGGED"

    def transport(request):
        calls.append(request)
        if behavior == "timeout":
            raise httpx.ReadTimeout(secret_marker, request=request)
        parts = ([{"type": "refusal", "refusal": secret_marker}] if behavior == "refusal" else
                 [{"type": "output_text", "text": json.dumps({"bad": secret_marker})}])
        return httpx.Response(200, headers={"x-request-id": "req_mock_123"}, json={
            "id": "resp_mock_123", "status": "completed", "usage": {"input_tokens": 12, "output_tokens": 3},
            "output": [{"type": "message", "content": parts}],
        })

    provider = OpenAIProvider(api_key=secret_marker, enabled=True, transport=httpx.MockTransport(transport))
    with TestClient(create_app(api_settings, engine=api_engine, provider=provider),
                    base_url="http://127.0.0.1:8012", headers={"X-Local-Token": TOKEN}) as client:
        _, vendor, _ = scope(client, behavior)
        source = accepted(upload(client, vendor))
        authorization = {"authorized": True, "source_sha256": source["sha256"],
                         "authorized_by": "Synthetic integration reviewer", "policy_reference": "Synthetic mock only",
                         "reason": "Offline injected transport; no external transfer"}
        run = accepted(create_run(client, source, provider="openai", fixture=None, authorization=authorization))
        run = process(client, run)
        assert run["state"] == "failed"
        failed_result = result(client, run)
        assert failed_result["extraction"] is None
        assert len(failed_result["attempts"]) == 1
        attempt = failed_result["attempts"][0]
        assert attempt["state"] == attempt_state
        assert secret_marker not in json.dumps(failed_result)
        process(client, run)
        assert len(calls) == 1
        assert result(client, run) == failed_result


def test_one_hundred_individual_fictional_sources_upload_without_processing(api_client, api_engine):
    tenant, vendor, _ = scope(api_client, "volume-100", products=False)
    hashes = set()
    for index in range(100):
        response = upload(api_client, vendor, content=batch_upload_pdf(index))
        assert response.status_code == 201, response.text
        source = response.json()
        assert source["page_count"] == 1 and source["media_type"] == "application/pdf"
        assert source["sha256"] not in hashes
        hashes.add(source["sha256"])
    with Session(api_engine) as session:
        assert session.query(SourceDocument).filter_by(tenant_id=tenant["id"]).count() == 100
        assert session.query(ProcessingRun).filter_by(tenant_id=tenant["id"]).count() == 0
        assert session.query(ProviderAttempt).filter_by(tenant_id=tenant["id"]).count() == 0


def test_r11_nul_in_client_strings_is_a_validation_error_not_a_database_outage(api_client):
    _, vendor, _ = scope(api_client, "NUL", products=False)
    nul = "fictional\u0000text"
    missing = str(uuid4())
    evidence = [{"page_number": 1, "region_reference": "r1"}]
    cases = [
        ("/tenants", {"name": nul}),
        ("/vendors", {"name": nul}),
        ("/catalog/import", {"vendor_id": vendor["id"], "products": [{"sku": nul, "description": "ok"}]}),
        ("/catalog/import", {"vendor_id": vendor["id"], "products": [{"sku": "NUL-1", "description": nul}]}),
        ("/catalog/import", {"vendor_id": vendor["id"], "products": [
            {"sku": "NUL-2", "description": "ok", "aliases": [{"value": nul, "source_role": "sku"}]}]}),
        ("/catalog/import", {"vendor_id": vendor["id"], "products": [
            {"sku": "NUL-3", "description": "ok", "aliases": [{"value": "alias", "source_role": nul}]}]}),
        (f"/runs/{missing}/reviews", {"action": "acknowledge", "row_id": "r1", "reviewer": nul,
                                      "reason": "why", "evidence_reference": evidence}),
        (f"/runs/{missing}/reviews", {"action": "correct", "row_id": "r1", "reviewer": "who", "reason": "why",
                                      "field_name": "description", "new_value": nul, "evidence_reference": evidence}),
        (f"/runs/{missing}/reviews", {"action": "acknowledge", "row_id": "r1", "reviewer": "who", "reason": "why",
                                      "evidence_reference": [{"page_number": 1, "region_reference": nul}]}),
        (f"/documents/{missing}/runs", {"provider": "synthetic", "fixture_name": nul}),
        (f"/documents/{missing}/runs", {"provider": "openai", "external_authorization": {
            "authorized": True, "source_sha256": "a" * 64, "authorized_by": nul,
            "policy_reference": "policy", "reason": "reason"}}),
    ]
    for path, body in cases:
        response = api_client.post(path, json=body, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 422, (path, response.status_code, response.text)
        assert response.json()["error"] == "invalid_request"
    search = api_client.get("/website/catalog", params={"vendor_id": vendor["id"], "q": nul})
    assert search.status_code == 422 and search.json()["error"] == "search_text_invalid"
