"""Synthetic API/history failure checks in this agent's isolated PostgreSQL DB."""
from contextlib import ExitStack
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
import pytest

from backend.app import create_app
from backend.catalog import ProductInput, import_products
from backend.config import Settings
from backend.contracts import ExtractionPayload
from backend.models import SourceDocument, Vendor
from backend.providers import ProviderResult, PROMPT_VERSION
from backend.synthetic import fixture_payload, generate_fixture
from backend.uploads import digest, write_source
from gate_a.database import create_db_engine
from gate_a.models import Tenant


@pytest.fixture(scope="module")
def engine():
    value = os.environ.get("PO_BACKEND_CONTRACT_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set PO_BACKEND_CONTRACT_TEST_DATABASE_URL to isolated gate_a_test_backend_website_contract")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith(("gate_a_test_backend_", "orderlens_product_rows")) or url.query):
        pytest.fail("Failure tests require an isolated loopback synthetic test database")
    result = create_db_engine(url, connect_timeout_seconds=10)
    config = Config("backend.alembic.ini")
    with result.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield result
    result.dispose()


class OfflineProvider:
    model = "offline-test-adapter"
    prompt_version = PROMPT_VERSION
    schema_version = "1.1"

    def __init__(self, outcome=None, callback=None):
        self.outcome = outcome
        self.callback = callback
        self.calls = 0

    def extract(self, source_bytes, media_type, page_count, fixture_name=None):
        self.calls += 1
        if self.callback is not None:
            return self.callback()
        return self.outcome


def outcome(state="succeeded", payload=None, error_code=None):
    return ProviderResult(payload if payload is not None else (fixture_payload() if state == "succeeded" else None),
                          state, request_id="req_offline", response_id="resp_offline",
                          usage={"input_tokens": 11, "output_tokens": 22, "total_tokens": 33},
                          latency_ms=7, error_code=error_code, model=OfflineProvider.model,
                          actual_model="offline-response-model")


@dataclass
class Resource:
    client: TestClient
    headers: dict
    source: dict
    settings: Settings

    def run(self, provider="openai", key=None, authorization=True):
        body = {"provider": provider}
        if provider == "openai" and authorization:
            body["external_authorization"] = {
                "authorized": True, "source_sha256": self.source["sha256"],
                "authorized_by": "Synthetic API tester", "policy_reference": "offline-injected-transport-only",
                "reason": "Synthetic fixture only; this test has no external transport.",
            }
        response = self.client.post(f"/documents/{self.source['id']}/runs", json=body,
                                    headers={**self.headers, "Idempotency-Key": key or uuid4().hex})
        assert response.status_code == 201, response.text
        return response.json()

    def process(self, run):
        return self.client.post(f"/runs/{run['id']}/process", headers=self.headers)

    def result(self, run):
        response = self.client.get(f"/runs/{run['id']}/result", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def suggestions(self, run):
        response = self.client.get(f"/runs/{run['id']}/suggestions", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()["suggestions"]

    def review(self, run, action, row_id=None, **kwargs):
        body = {"action": action, "reviewer": "Synthetic named reviewer",
                "reason": "Inspected this synthetic evidence.", **kwargs}
        if row_id:
            body.update(row_id=row_id, evidence_reference=[{"page_number": 1, "region_reference": row_id}])
        return self.client.post(f"/runs/{run['id']}/reviews", json=body, headers=self.headers)

    def acknowledge_rows(self, run):
        for suggestion in self.suggestions(run):
            row_id = suggestion["row_id"]
            if suggestion["candidates"]:
                chosen = suggestion["candidates"][0]["candidate_id"]
                if suggestion["tier"] == "uncertain":
                    assert self.review(run, "this_is_product", row_id, catalog_id=chosen).status_code == 201
                assert self.review(run, "approve", row_id, selected_candidate_id=chosen).status_code == 201
            else:
                assert self.review(run, "not_a_product", row_id).status_code == 201
        for row_id in ("line-3", "line-4"):
            assert self.review(run, "acknowledge", row_id).status_code == 201
        assert self.client.post(f"/runs/{run['id']}/page-counts", headers=self.headers, json={
            "page_number": 1, "source_sha256": self.source["sha256"], "product_count": 2,
            "source_discrepancy": False, "reviewer": "Synthetic named reviewer",
            "reason": "Counted the two printed products in the generated source"}).status_code == 201


@pytest.fixture
def resource_factory(engine):
    with ExitStack() as stack:
        def factory(provider=None, kind="purchase_order", page_count=1):
            storage = Path(__file__).parents[2] / "data" / "contract-agent" / "tests" / uuid4().hex
            settings = Settings(_env_file=None, database_url=os.environ["PO_BACKEND_CONTRACT_TEST_DATABASE_URL"],
                                storage_directory=storage, live_processing_enabled=False, openai_api_key=None)
            source_bytes = generate_fixture(kind)
            if page_count > 1:
                buffer = BytesIO()
                canvas = Canvas(buffer, invariant=1)
                for page in range(page_count):
                    canvas.drawString(72, 700, f"SYNTHETIC DEMO PAGE {page + 1}")
                    canvas.showPage()
                canvas.save()
                source_bytes = buffer.getvalue()
            with Session(engine, expire_on_commit=False) as session:
                tenant = Tenant(name=f"Synthetic failure tenant {uuid4()}")
                session.add(tenant)
                session.flush()
                vendor = Vendor(tenant_id=tenant.id, name="Synthetic Supplies")
                session.add(vendor)
                session.flush()
                import_products(session, tenant.id, vendor.id, [
                    ProductInput(sku="SYN-001", description="Synthetic blue widget"),
                    ProductInput(sku="SYN-002", description="Synthetic red widget"),
                ])
                source = SourceDocument(tenant_id=tenant.id, vendor_id=vendor.id, sha256=digest(source_bytes),
                                        byte_size=len(source_bytes), media_type="application/pdf", page_count=page_count,
                                        storage_reference=write_source(storage, source_bytes))
                session.add(source)
                session.commit()
                source_data = {"id": str(source.id), "sha256": source.sha256,
                               "storage_reference": source.storage_reference}
                headers = {"X-Tenant-ID": str(tenant.id),
                           "X-Local-Token": settings.local_api_token.get_secret_value()}
            client = stack.enter_context(TestClient(create_app(settings, engine, provider), base_url="http://127.0.0.1"))
            return Resource(client, headers, source_data, settings)
        yield factory


@pytest.mark.parametrize("state", ["refused", "invalid_output", "incomplete", "unknown_outcome", "failed"])
def test_attempt_failure_metadata_is_persistent_and_not_retried(resource_factory, state):
    provider = OfflineProvider(outcome(state, error_code=f"offline_{state}"))
    resource = resource_factory(provider)
    run = resource.run()
    response = resource.process(run)
    assert response.status_code == 200 and response.json()["state"] == "failed"
    result = resource.result(run)
    assert result["extraction"] is None and result["parses"] is None
    assert len(result["attempts"]) == 1
    attempt = result["attempts"][0]
    assert attempt["state"] == state and attempt["request_id"] == "req_offline"
    assert attempt["usage"]["total_tokens"] == 33 and attempt["latency_ms"] == 7
    assert attempt["model"] == OfflineProvider.model
    assert attempt["actual_model"] == "offline-response-model"
    assert attempt["finished_at"] is not None
    assert resource.process(run).json()["state"] == "failed"
    assert provider.calls == 1


def test_live_disabled_no_attempt_even_with_affirmative_authorization(resource_factory):
    resource = resource_factory()
    run = resource.run()
    response = resource.process(run)
    assert response.json()["outcome_code"] == "provider_not_configured"
    assert resource.result(run)["attempts"] == []


def test_injected_adapter_still_requires_source_specific_authorization(resource_factory):
    provider = OfflineProvider(outcome())
    resource = resource_factory(provider)
    run = resource.run(authorization=False)
    assert resource.process(run).json()["outcome_code"] == "external_processing_authorization_required"
    assert provider.calls == 0 and resource.result(run)["attempts"] == []


def test_source_integrity_failure_precedes_any_provider_attempt(resource_factory):
    provider = OfflineProvider(outcome())
    resource = resource_factory(provider)
    path = resource.settings.storage_directory / resource.source["storage_reference"]
    path.write_bytes(b"Synthetic intentional integrity failure")
    run = resource.run()
    assert resource.process(run).json()["outcome_code"] == "source_integrity_failed"
    assert provider.calls == 0 and resource.result(run)["attempts"] == []


@pytest.mark.parametrize("kind,code", [("unsupported", "unsupported_document_type"), ("unknown", "needs_classification")])
def test_document_classification_stops_before_catalog(resource_factory, kind, code):
    provider = OfflineProvider(outcome(payload=fixture_payload(kind)))
    resource = resource_factory(provider, kind)
    run = resource.run()
    processed = resource.process(run)
    assert processed.status_code == 200, processed.text
    response = processed.json()
    assert response["state"] == "failed" and response["outcome_code"] == code
    assert resource.result(run)["extraction"]["document_type"] == kind
    assert resource.suggestions(run) == []


def test_unknown_attempt_persisted_before_call_and_duplicate_request_does_not_call_twice(resource_factory):
    provider = OfflineProvider()
    resource = resource_factory(provider)
    run = resource.run()
    def callback():
        active = resource.result(run)["attempts"][0]
        assert active["state"] == "unknown_outcome" and active["finished_at"] is None
        assert active["error_code"] == "attempt_in_progress_or_interrupted"
        duplicate = resource.process(run)
        assert duplicate.status_code == 409
        assert duplicate.json()["error"] == "processing_in_progress_or_unknown_outcome"
        return outcome()
    provider.callback = callback
    assert resource.process(run).json()["state"] == "partial"
    assert provider.calls == 1


@pytest.mark.parametrize("raises", [False, True])
def test_concurrent_cancellation_stays_final_preserves_attempt_and_no_observation(resource_factory, raises):
    provider = OfflineProvider()
    resource = resource_factory(provider)
    run = resource.run()
    def callback():
        response = resource.client.post(f"/runs/{run['id']}/cancel", headers=resource.headers)
        assert response.status_code == 200 and response.json()["state"] == "cancelled"
        if raises:
            raise RuntimeError("Secret/private provider text must never escape.")
        return outcome()
    provider.callback = callback
    response = resource.process(run)
    assert response.status_code == 200 and response.json()["state"] == "cancelled"
    result = resource.result(run)
    assert result["extraction"] is None and result["parses"] is None
    assert result["attempts"][0]["finished_at"] is not None
    assert result["attempts"][0]["state"] == ("unknown_outcome" if raises else "succeeded")
    if not raises:
        assert result["attempts"][0]["usage"]["total_tokens"] == 33
    assert "Secret/private" not in str(result)
    assert resource.process(run).json()["state"] == "cancelled" and provider.calls == 1


def test_unexpected_provider_exception_is_sanitized_and_persistent_unknown_outcome(resource_factory):
    def callback():
        raise RuntimeError("Secret/private provider text must never escape.")
    provider = OfflineProvider(callback=callback)
    resource = resource_factory(provider)
    run = resource.run()
    assert resource.process(run).json()["outcome_code"] == "unknown_outcome"
    attempt = resource.result(run)["attempts"][0]
    assert attempt["state"] == "unknown_outcome" and attempt["error_code"] == "provider_outcome_unknown"
    assert "Secret/private" not in str(attempt)
    assert resource.process(run).status_code == 200 and provider.calls == 1


def test_provider_metadata_mismatch_rejected_without_losing_usage(resource_factory):
    supplied = outcome()
    provider = OfflineProvider(ProviderResult(supplied.payload, "succeeded", usage={"total_tokens": 33}, model="different"))
    resource = resource_factory(provider)
    run = resource.run()
    assert resource.process(run).json()["state"] == "failed"
    result = resource.result(run)
    assert result["extraction"] is None
    assert result["attempts"][0]["error_code"] == "provider_version_mismatch"
    assert result["attempts"][0]["usage"]["total_tokens"] == 33


def test_candidate_search_limits_route_to_review_without_losing_long_literal(resource_factory):
    payload = fixture_payload().model_dump(mode="json")
    long_literal = "LONG-SOURCE-ID-" * 30
    payload["rows"][0]["identifiers"][0]["raw_value"] = long_literal
    provider = OfflineProvider(outcome(payload=ExtractionPayload.model_validate(payload)))
    resource = resource_factory(provider)
    run = resource.run()
    assert resource.process(run).json()["state"] == "partial"
    result = resource.result(run)
    assert result["extraction"]["rows"][0]["identifiers"][0]["raw_value"] == long_literal
    assert result["attempts"][0]["state"] == "succeeded"
    suggestion = next(item for item in resource.suggestions(run) if item["row_id"] == "line-1")
    assert suggestion["outcome"] == "no_match" and suggestion["candidates"] == []


def test_correction_after_approval_invalidates_resolution_and_preserves_original(resource_factory):
    resource = resource_factory(OfflineProvider(outcome()))
    run = resource.run()
    assert resource.process(run).json()["state"] == "partial"
    resource.acknowledge_rows(run)
    correction = resource.review(run, "correct", "line-1", field_name="quantity", new_value="4")
    assert correction.status_code == 201
    assert correction.json()["old_value"] == {"field_name": "quantity", "value": "2"}
    assert resource.review(run, "resolve").status_code == 409
    assert resource.result(run)["extraction"]["rows"][0]["quantity"]["raw_value"] == "2"
    assert resource.review(run, "no_match", "line-1").status_code == 201
    assert resource.review(run, "resolve").status_code == 201
    assert resource.review(run, "correct", "line-1", field_name="quantity", new_value="5").status_code == 409


def test_approved_candidate_must_belong_to_same_row_snapshot(resource_factory):
    resource = resource_factory(OfflineProvider(outcome()))
    run = resource.run()
    resource.process(run)
    suggestions = {item["row_id"]: item for item in resource.suggestions(run)}
    wrong = suggestions["line-2"]["candidates"][0]["candidate_id"]
    response = resource.review(run, "approve", "line-1", selected_candidate_id=wrong)
    assert response.status_code == 422 and response.json()["error"] == "selected_candidate_outside_snapshot"
    right = suggestions["line-1"]["candidates"][0]["candidate_id"]
    assert resource.review(run, "approve", "line-1", selected_candidate_id=right).status_code == 201
    assert resource.result(run)["extraction"] == fixture_payload().model_dump(mode="json")


def test_reprocess_creates_independent_attempt_and_preserves_prior_history(resource_factory):
    provider = OfflineProvider(outcome())
    resource = resource_factory(provider)
    first = resource.run()
    resource.process(first)
    resource.review(first, "no_match", "line-1")
    original = resource.result(first)
    provider.outcome = outcome("refused", error_code="offline_refusal")
    second = resource.run()
    resource.process(second)
    assert first["id"] != second["id"]
    assert resource.result(first) == original
    assert resource.result(second)["extraction"] is None
    history = resource.client.get(f"/documents/{resource.source['id']}/runs", headers=resource.headers).json()["runs"]
    assert {item["state"] for item in history} == {"partial", "failed"}
    reviews = resource.client.get(f"/runs/{first['id']}/reviews", headers=resource.headers).json()["events"]
    assert len(reviews) == 1 and reviews[0]["action"] == "no_match"


@pytest.mark.parametrize("value", [1, "true", False, None])
def test_external_authorization_requires_affirmative_boolean_not_coercion(resource_factory, value):
    resource = resource_factory(OfflineProvider(outcome()))
    body = {"provider": "openai", "external_authorization": {
        "authorized": value, "source_sha256": resource.source["sha256"],
        "authorized_by": "Synthetic tester", "policy_reference": "offline only", "reason": "Synthetic only",
    }}
    response = resource.client.post(f"/documents/{resource.source['id']}/runs", json=body,
                                   headers={**resource.headers, "Idempotency-Key": uuid4().hex})
    assert response.status_code == 422


def test_partial_page_needs_evidence_bound_human_acknowledgement(resource_factory):
    resource = resource_factory(OfflineProvider(outcome(payload=fixture_payload("partial"))), "partial")
    run = resource.run()
    assert resource.process(run).json()["state"] == "partial"
    resource.acknowledge_rows(run)
    blocked = resource.review(run, "resolve")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "partial_pages_require_explicit_acknowledgement"
    assert resource.review(run, "acknowledge_page", evidence_reference=[
        {"page_number": 1, "region_reference": "invented"}]).status_code == 422
    acknowledgement = resource.review(run, "acknowledge_page", evidence_reference=[
        {"page_number": 1, "region_reference": "line-1"}])
    assert acknowledgement.status_code == 201
    assert acknowledgement.json()["old_value"]["page_state"] == "partial"
    assert resource.review(run, "resolve").status_code == 201
    assert resource.result(run)["extraction"]["pages"][0]["state"] == "partial"


def test_document_warnings_need_separate_named_evidence_bound_acknowledgement(resource_factory):
    payload = fixture_payload().model_dump(mode="json")
    payload["warnings"] = ["Synthetic table completeness needs human inspection."]
    resource = resource_factory(OfflineProvider(outcome(payload=ExtractionPayload.model_validate(payload))))
    run = resource.run()
    assert resource.process(run).json()["state"] == "partial"
    resource.acknowledge_rows(run)
    blocked = resource.review(run, "resolve")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "document_warnings_require_explicit_acknowledgement"
    acknowledgement = resource.review(run, "acknowledge_document", evidence_reference=[
        {"page_number": 1, "region_reference": "header"}])
    assert acknowledgement.status_code == 201
    assert resource.review(run, "resolve").status_code == 201
    assert resource.result(run)["extraction"]["warnings"] == payload["warnings"]


def test_failed_page_cannot_be_resolved_or_acknowledged_away(resource_factory):
    payload = fixture_payload().model_dump(mode="json")
    payload["pages"].append({"page_number": 2, "state": "failed", "regions": [],
                             "uncertainty": "Synthetic failed second page."})
    resource = resource_factory(OfflineProvider(outcome(payload=ExtractionPayload.model_validate(payload))), page_count=2)
    run = resource.run()
    assert resource.process(run).json()["state"] == "partial"
    resource.acknowledge_rows(run)
    blocked = resource.review(run, "resolve")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "failed_pages_require_new_processing_run"


def test_identifier_corrections_append_old_new_and_do_not_repair_source_or_aliases(resource_factory):
    resource = resource_factory(OfflineProvider(outcome()))
    run = resource.run()
    resource.process(run)
    resource.acknowledge_rows(run)
    correction = resource.review(run, "correct", "line-1", field_name="identifier.raw_value",
                                 identifier_index=0, new_value="SYN-002")
    assert correction.status_code == 201
    assert correction.json()["old_value"] == {"field_name": "identifier.raw_value", "identifier_index": 0, "value": "SYN-001"}
    assert correction.json()["new_value"] == {"field_name": "identifier.raw_value", "identifier_index": 0, "value": "SYN-002"}
    assert resource.result(run)["extraction"]["rows"][0]["identifiers"][0]["raw_value"] == "SYN-001"
    assert resource.review(run, "resolve").status_code == 409
    wrong_candidate = next(item for item in resource.suggestions(run) if item["row_id"] == "line-2")["candidates"][0]["candidate_id"]
    assert resource.review(run, "approve", "line-1", selected_candidate_id=wrong_candidate).status_code == 422
    assert resource.review(run, "correct", "line-1", field_name="identifier.source_role",
                           identifier_index=99, new_value="vendor_sku").status_code == 422


def test_request_validation_does_not_echo_arbitrary_unknown_property_names(resource_factory):
    resource = resource_factory()
    response = resource.client.post("/tenants", headers=resource.headers,
                                    json={"name": "Synthetic tenant", "sk-proj-SENTINEL-PRIVATE-TEXT": "secret-value"})
    assert response.status_code == 422
    assert "SENTINEL" not in response.text and "secret-value" not in response.text
