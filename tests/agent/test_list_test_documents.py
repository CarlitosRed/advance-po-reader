"""R07: the list-test-documents tool sends the explicit workspace the corpus endpoint requires."""
from uuid import uuid4

import anyio
import httpx
from mcp import Client
from pydantic import SecretStr
import pytest

from reader_agent.client import ReaderClient
from reader_agent.connection import ConnectionSettings
from reader_agent.server import create_server

TENANT, OTHER = str(uuid4()), str(uuid4())
TOKEN = "fictional-connection-token-only"


def server_requiring_tenant():
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/website/workspaces":
            return httpx.Response(200, json={"workspaces": [{"id": TENANT, "catalogs": [], "catalog_pools": []}]})
        assert path == "/website/corpus"
        if request.headers.get("X-Tenant-ID") != TENANT:  # the real endpoint: tenant_for is unconditional
            return httpx.Response(422, json={"error": "tenant_header_required"})
        return httpx.Response(200, json={"documents": [{"document_id": "D01"}], "default_catalog_pool": None})

    settings = ConnectionSettings(local_api_token=SecretStr(TOKEN))
    return calls, create_server(ReaderClient(settings, httpx.MockTransport(handler)))


def call(server, arguments):
    async def exercise():
        async with Client(server) as client:
            return await client.call_tool("reader_list_test_documents", arguments)
    return anyio.run(exercise)


def test_listing_sends_the_tenant_header_and_returns_the_documents():
    calls, server = server_requiring_tenant()
    result = call(server, {"tenant_id": TENANT})
    assert not result.is_error and result.structured_content["documents"][0]["document_id"] == "D01"
    assert calls[-1].headers["X-Tenant-ID"] == TENANT


@pytest.mark.parametrize("arguments", [{}, {"tenant_id": "not-a-uuid"}, {"tenant_id": None}])
def test_listing_without_a_valid_workspace_is_rejected_before_any_request(arguments):
    calls, server = server_requiring_tenant()
    assert call(server, arguments).is_error and calls == []


def test_listing_an_unknown_workspace_stops_before_the_corpus_request():
    calls, server = server_requiring_tenant()
    assert call(server, {"tenant_id": OTHER}).is_error
    assert all(request.url.path == "/website/workspaces" for request in calls)
