"""Fixed loopback REST operations with explicit workspace/catalog boundaries."""
from hashlib import sha256
from uuid import UUID

import httpx

from reader_agent.connection import ConnectionSettings


class ReaderError(Exception):
    """Sanitized operation code. Never includes source data or credentials."""


class ReaderClient:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or ConnectionSettings()
        self.transport = transport

    async def request(self, method, path, tenant=None, binary=False, **kwargs):
        headers = {"X-Local-Token": self.settings.local_api_token.get_secret_value()}
        if tenant is not None:
            headers["X-Tenant-ID"] = str(UUID(str(tenant)))
        headers.update(kwargs.pop("headers", {}))
        try:
            async with httpx.AsyncClient(base_url=self.settings.base_url, headers=headers,
                    transport=self.transport, timeout=210, trust_env=False, follow_redirects=False) as client:
                if binary:
                    async with client.stream(method, path, **kwargs) as response:
                        if response.status_code != 200:
                            raise ReaderError(f"local_http_{response.status_code}")
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 20 * 1024 * 1024:
                                raise ReaderError("local_source_read_limit")
                        return bytes(data)
                response = await client.request(method, path, **kwargs)
                if response.status_code not in {200, 201}:
                    # Do not reflect arbitrary upstream text into tools or logs.
                    raise ReaderError(f"local_http_{response.status_code}")
                data = response.json()
                if not isinstance(data, dict):
                    raise ReaderError("invalid_local_response")
                return data
        except (httpx.HTTPError, ValueError):
            raise ReaderError("local_connection_interrupted_check_run_no_retry") from None

    async def catalogs(self, tenant):
        data = await self.request("GET", "/website/workspaces")
        workspace = next((w for w in data["workspaces"] if w["id"] == str(tenant)), None)
        if workspace is None:
            raise ReaderError("workspace_not_found")
        return workspace

    async def scope(self, tenant, vendor):
        workspace = await self.catalogs(tenant)
        catalog = next((c for c in workspace["catalogs"] if c["id"] == str(vendor)), None)
        if catalog is None:
            raise ReaderError("catalog_not_in_workspace")
        return catalog

    async def scoped_run(self, tenant, vendor, run):
        await self.scope(tenant, vendor)
        value = await self.request("GET", f"/runs/{run}", tenant)
        if value["vendor_id"] != str(vendor):
            raise ReaderError("run_not_in_selected_catalog")
        return value

    def review_url(self, source, run):
        return f"{self.settings.base_url}/#document={source}&run={run}"

    async def prepare(self, tenant, vendor, content, request_id, synthetic=False):
        key = str(request_id)
        source = await self.request("POST", "/documents", tenant,
            data={"vendor_id": str(vendor)}, files={"file": ("source.pdf", content, "application/pdf")},
            headers={"Idempotency-Key": f"agent-upload-{key}"})
        if source["sha256"] != sha256(content).hexdigest():
            raise ReaderError("source_hash_mismatch_processing_not_requested")
        run = await self.request("POST", f"/documents/{source['id']}/runs", tenant,
            json={"provider": "synthetic", "fixture_name": "purchase_order"} if synthetic else {"provider": "openai"},
            headers={"Idempotency-Key": f"agent-run-{key}"})
        return source, run

    async def prepare_test(self, tenant, vendor, document_id, request_id):
        catalog = await self.scope(tenant, vendor)
        if catalog["synthetic"]:
            raise ReaderError("choose_a_real_catalog_explicitly")
        library = await self.request("GET", "/website/corpus")
        item = next((d for d in library["documents"] if d["document_id"] == document_id), None)
        if item is None:
            raise ReaderError("test_document_not_found")
        content = await self.request("GET", f"/website/corpus/{item['sha256']}/content", binary=True)
        if sha256(content).hexdigest() != item["sha256"]:
            raise ReaderError("test_source_hash_mismatch")
        source, run = await self.prepare(tenant, vendor, content, request_id)
        return {"source_id": source["id"], "source_sha256": source["sha256"], "run": run,
                "review_url": self.review_url(source["id"], run["id"]),
                "next_step": "Human source authorization in the website; no extraction requested."}

    async def sample(self, tenant, vendor, request_id):
        catalog = await self.scope(tenant, vendor)
        if not catalog["synthetic"]:
            raise ReaderError("fictional_sample_requires_synthetic_catalog")
        content = await self.request("GET", "/website/demo-document", binary=True)
        source, run = await self.prepare(tenant, vendor, content, request_id, synthetic=True)
        # The same request UUID may retrieve an already processed sample. Never process it twice.
        if run["state"] == "created":
            await self.request("POST", f"/runs/{run['id']}/process", tenant)
        run = await self.scoped_run(tenant, vendor, run["id"])
        return {"run": run, "review_url": self.review_url(source["id"], run["id"]),
                "fictional": True, "human_review_required": True}

    async def process_authorized(self, tenant, vendor, run_id):
        run = await self.scoped_run(tenant, vendor, run_id)
        if run["provider"] != "openai":
            raise ReaderError("use_sample_workflow_for_synthetic_sources")
        readiness = await self.request("GET", f"/runs/{run_id}/readiness", tenant)
        if not readiness["can_process"]:
            return {"processing_requested": False, "readiness": readiness,
                    "review_url": self.review_url(run["source_document_id"], run_id)}
        # One explicit attempt only. Authorization was recorded by the human in the website.
        await self.request("POST", f"/runs/{run_id}/process", tenant)
        run = await self.scoped_run(tenant, vendor, run_id)
        return {"processing_requested": True, "run": run, "human_review_required": True,
                "review_url": self.review_url(run["source_document_id"], run_id)}
