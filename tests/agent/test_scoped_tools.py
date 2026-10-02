"""MCP protocol and authorization boundaries with a fictional loopback server."""
import json
from hashlib import sha256
from uuid import UUID, uuid4

import anyio
import httpx
from mcp import Client
from pydantic import SecretStr, ValidationError
import pytest

from reader_agent.client import ReaderClient
from reader_agent.connection import ConnectionSettings
from reader_agent.server import create_server

TENANT, VENDOR, OTHER, RUN, SOURCE = (str(uuid4()) for _ in range(5))
TOKEN = "fictional-connection-token-only"
CONTENT = b"%PDF-fictional-rest-boundary-fixture"
HASH = sha256(CONTENT).hexdigest()


def protocol(operation):
    return anyio.run(operation)


def fake_server(*, synthetic=False, authorized=False, configured=False, state="created",
                unknown=False, wrong_vendor=False, corrupt_source=False):
    calls = []
    run = {"id": RUN, "source_document_id": SOURCE, "vendor_id": OTHER if wrong_vendor else VENDOR,
           "provider": "synthetic" if synthetic else "openai", "state": state, "review_state": "not_started"}
    def handler(request):
        calls.append(request)
        assert request.url.host == "127.0.0.1"
        assert request.headers["X-Local-Token"] == TOKEN
        path = request.url.path
        if path == "/website/workspaces":
            value = {"workspaces": [{"id": TENANT, "catalogs": [{"id": VENDOR, "synthetic": synthetic}]}]}
        elif path == "/website/readiness":
            value = {"database": "ready", "provider_configured": configured}
        elif path == "/website/corpus":
            value = {"documents": [{"document_id": "D01", "sha256": HASH}]}
        elif path.endswith("/content") or path == "/website/demo-document":
            return httpx.Response(200, content=b"bad" if corrupt_source else CONTENT)
        elif path == "/documents":
            assert request.headers["X-Tenant-ID"] == TENANT
            assert "Idempotency-Key" in request.headers
            value = {"id": SOURCE, "sha256": HASH}
        elif path == f"/documents/{SOURCE}/runs":
            body = json.loads(request.content)
            assert "external_authorization" not in body
            assert request.headers["X-Tenant-ID"] == TENANT
            value = run.copy()
        elif path == f"/runs/{RUN}/process":
            run["state"] = "completed"
            value = run.copy()
        elif path == f"/runs/{RUN}":
            assert request.headers["X-Tenant-ID"] == TENANT
            value = run.copy()
        elif path.endswith("/readiness"):
            blockers = []
            if not authorized: blockers.append("source_authorization_required")
            if not configured: blockers.append("provider_not_configured")
            if unknown: blockers.append("unknown_outcome_no_retry")
            if state != "created": blockers.append("run_already_started_or_terminal")
            value = {"can_process": not blockers, "blockers": blockers}
        elif path.endswith("/summary"):
            value = {"approved_products": [], "pending_row_ids": ["line-1"], "source_observations_unchanged": True}
        elif path == "/website/catalog":
            assert request.url.params["vendor_id"] == VENDOR
            assert request.headers["X-Tenant-ID"] == TENANT
            value = {"products": [{"sku": "FICTIONAL-001"}], "total": 1}
        else:
            return httpx.Response(404, json={"error": "fictional_not_found"})
        return httpx.Response(200, json=value)
    connection = ConnectionSettings(_env_file=None, local_api_token=SecretStr(TOKEN))
    return calls, create_server(ReaderClient(connection, transport=httpx.MockTransport(handler)))


def args(**extra):
    return {"tenant_id": TENANT, "vendor_id": VENDOR, **extra}


def test_protocol_tool_inventory_and_permissions():
    calls, server = fake_server()
    async def exercise():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            by_name = {tool.name: tool for tool in tools}
            assert len(tools) == 11
            assert not any(word in name for name in by_name for word in ("approve", "correct", "resolve", "cart", "order"))
            for name, tool in by_name.items():
                expected_read = name not in {"reader_prepare_test_document", "reader_start_sample_workflow", "reader_process_authorized_run"}
                assert tool.annotations.read_only_hint is expected_read
                assert tool.annotations.open_world_hint is (name == "reader_process_authorized_run")
            result = await client.call_tool("reader_status", {})
            assert not result.is_error and result.structured_content["database"] == "ready"
    protocol(exercise)
    assert len(calls) == 1


@pytest.mark.parametrize("updates", [{"tenant_id": OTHER}, {"vendor_id": OTHER}])
def test_wrong_workspace_or_catalog_stops_before_reading_products(updates):
    calls, server = fake_server()
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_search_catalog", args(query="FICTIONAL", **updates))
            assert result.is_error
    protocol(exercise)
    assert all(request.url.path == "/website/workspaces" for request in calls)


@pytest.mark.parametrize("bad", [{"query": "x" * 121}, {"limit": 51}, {"offset": -1}, {"tenant_id": "../private"}])
def test_argument_bounds_reject_before_network(bad):
    calls, server = fake_server()
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_search_catalog", args(**bad))
            assert result.is_error
    protocol(exercise)
    assert calls == []


def test_real_pdf_preparation_never_grants_authorization_or_processes():
    calls, server = fake_server()
    key = str(uuid4())
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_prepare_test_document", args(document_id="D01", request_id=key))
            assert not result.is_error
            assert result.structured_content["source_sha256"] == HASH
            assert result.structured_content["run"]["state"] == "created"
    protocol(exercise)
    assert not any(request.url.path.endswith("/process") for request in calls)
    assert [request.headers["Idempotency-Key"] for request in calls if request.method == "POST"] == [
        "agent-upload-" + key, "agent-run-" + key]


def test_corrupt_corpus_stops_before_upload():
    calls, server = fake_server(corrupt_source=True)
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_prepare_test_document", args(document_id="D01", request_id=str(uuid4())))
            assert result.is_error
    protocol(exercise)
    assert all(request.method == "GET" for request in calls)


@pytest.mark.parametrize("options", [{}, {"authorized": True}, {"configured": True},
    {"authorized": True, "configured": True, "unknown": True},
    {"authorized": True, "configured": True, "state": "completed"}])
def test_processing_requires_authorization_configuration_and_clean_new_run(options):
    calls, server = fake_server(**options)
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_process_authorized_run", args(run_id=RUN))
            assert not result.is_error and result.structured_content["processing_requested"] is False
    protocol(exercise)
    assert all(request.method == "GET" for request in calls)


def test_authorized_processing_is_one_explicit_attempt():
    calls, server = fake_server(authorized=True, configured=True)
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_process_authorized_run", args(run_id=RUN))
            assert not result.is_error and result.structured_content["processing_requested"] is True
            assert result.structured_content["human_review_required"] is True
    protocol(exercise)
    assert sum(request.method == "POST" for request in calls) == 1


def test_wrong_catalog_run_cannot_be_read_or_processed():
    calls, server = fake_server(authorized=True, configured=True, wrong_vendor=True)
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_process_authorized_run", args(run_id=RUN))
            assert result.is_error
    protocol(exercise)
    assert all(request.method == "GET" for request in calls)
    assert not any(request.url.path.endswith("/readiness") for request in calls)


@pytest.mark.parametrize("synthetic", [False, True])
def test_sample_needs_synthetic_catalog_and_never_approves(synthetic):
    calls, server = fake_server(synthetic=synthetic)
    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("reader_start_sample_workflow", args(request_id=str(uuid4())))
            assert result.is_error is not synthetic
            if synthetic:
                assert result.structured_content["fictional"] is True
                assert result.structured_content["run"]["review_state"] == "not_started"
    protocol(exercise)
    assert not any(request.url.path.endswith("/reviews") for request in calls)
    if not synthetic: assert all(request.method == "GET" for request in calls)


def test_connection_rejects_external_host_and_has_no_provider_key_field(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-provider-key-not-readable-as-a-field")
    connection = ConnectionSettings(_env_file=None)
    assert "openai_api_key" not in connection.model_dump()
    assert "fake-provider-key" not in str(connection)
    with pytest.raises(ValidationError): ConnectionSettings(_env_file=None, host="api.openai.com")


def test_interrupted_processing_never_retries_or_echoes_sensitive_errors():
    count = 0
    def interrupted(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("sensitive arbitrary error payload", request=request)
    bridge = ReaderClient(ConnectionSettings(_env_file=None), httpx.MockTransport(interrupted))
    async def exercise():
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool("reader_status", {})
            assert result.is_error
            assert "sensitive arbitrary" not in str(result)
    protocol(exercise)
    assert count == 1
