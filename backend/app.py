"""Loopback backend API for synthetic preparation and later authorized use."""
from contextlib import asynccontextmanager
from copy import deepcopy
import hmac
from urllib.parse import urlsplit
from uuid import UUID

from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.api_models import NameRequest, RequestModel, RunRequest, ReviewRequest
from backend.catalog import ProductInput, import_products, CatalogConflictError, CatalogScopeError
from backend.config import Settings
from backend.contracts import ExtractionPayload, strict_schema
from backend.errors import BackendError
from backend.models import Vendor, CatalogProduct, CatalogAlias, SourceDocument, UploadReceipt, ProcessingRun, ProviderAttempt, Suggestion, ReviewEvent
from backend.pools import default_pool, pool_members
from backend.service import (serialize, lock_key, fingerprint, source_for, run_for, create_run,
                             process_run, cancel_run, review_run)
from backend.uploads import digest, validate_file, write_source
from backend.responses import (ErrorResponse, TenantResponse, VendorResponse, SourceResponse,
                               RunResponse, RunsResponse, ResultResponse, SuggestionsResponse,
                               ReviewResponse, ReviewsResponse, CatalogResponse, ImportedResponse,
                               RunReadinessResponse, ReviewSummaryResponse)
from gate_a.contracts import ProductDocumentV1
from gate_a.database import create_db_engine
from gate_a.models import Tenant

EXPECTED_REVISION = "0009_review_answers"


class CatalogImport(RequestModel):
    vendor_id: UUID
    products: list[ProductInput] = Field(min_length=1, max_length=1000)


class LocalRequestBoundary:
    """Limit streaming bodies before multipart parsing, validate browser origins."""
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin1")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            return await JSONResponse({"error": "loopback_host_required"}, 403)(scope, receive, send)
        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = headers.get(b"origin")
            expected = f"{scope.get('scheme', 'http')}://{host}".encode("latin1")
            if (origin is not None and origin != expected) or headers.get(b"sec-fetch-site") == b"cross-site":
                return await JSONResponse({"error": "cross_origin_mutation_denied"}, 403)(scope, receive, send)
            token = headers.get(b"x-local-token", b"")
            if not hmac.compare_digest(token, self.settings.local_api_token.get_secret_value().encode()):
                return await JSONResponse({"error": "local_api_token_required"}, 401)(scope, receive, send)
            # Bound the whole body, including requests without Content-Length.
            limit = self.settings.max_upload_bytes + 64 * 1024
            parts, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > limit:
                    return await JSONResponse({"error": "request_body_too_large"}, 413)(scope, receive, send)
                parts.append(body)
                if not message.get("more_body", False):
                    break
            consumed = False

            async def bounded_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": b"".join(parts), "more_body": False}
                return await receive()
            return await self.app(scope, bounded_receive, send)
        return await self.app(scope, receive, send)


def create_app(settings: Settings | None = None, engine=None, provider=None):
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine or create_db_engine(configuration.database_url.get_secret_value(), 5)
        try:
            yield
        finally:
            if engine is None:
                app.state.engine.dispose()

    app = FastAPI(title="Advance PO Reader local backend", version="0.2.0", lifespan=lifespan,
                  responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 503)},
                  description="Local tenant scope via X-Tenant-ID; X-Local-Token protects all private routes. "
                              "All matches require human approval. Live extraction is disabled by default.")
    app.add_middleware(LocalRequestBoundary, settings=configuration)
    from backend.website import WebsiteSessionBoundary, register_website
    import secrets
    app.state.website_cookie = secrets.token_urlsafe(32)
    app.state.website_csrf = secrets.token_urlsafe(32)
    app.add_middleware(WebsiteSessionBoundary, settings=configuration,
        session_token=app.state.website_cookie, csrf_token=app.state.website_csrf)

    @app.exception_handler(BackendError)
    async def domain_error(request, error):
        return JSONResponse({"error": error.code}, error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Pydantic's normal errors include input values. Never return those values.
        issues = [{"location": [item["loc"][0] if item["loc"] and item["loc"][0] in
                                {"body", "query", "path", "header"} else "request"],
                   "type": item["type"]} for item in error.errors()]
        return JSONResponse({"error": "invalid_request", "issues": issues}, 422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse({"error": "database_conflict" if isinstance(error, IntegrityError) else "database_unavailable"},
                            409 if isinstance(error, IntegrityError) else 503)

    @app.exception_handler(CatalogConflictError)
    async def catalog_conflict(request, error):
        return JSONResponse({"error": "catalog_import_conflict"}, 409)

    @app.exception_handler(CatalogScopeError)
    async def catalog_scope(request, error):
        return JSONResponse({"error": "vendor_not_found"}, 404)

    def private(request):
        token = request.headers.get("X-Local-Token", "")
        if not hmac.compare_digest(token.encode(), configuration.local_api_token.get_secret_value().encode()):
            raise BackendError("local_api_token_required", 401)

    def tenant_for(request, session):
        private(request)
        try:
            tenant = UUID(request.headers.get("X-Tenant-ID", ""))
        except ValueError:
            raise BackendError("tenant_header_required", 422) from None
        if session.get(Tenant, tenant) is None:
            raise BackendError("tenant_not_found", 404)
        return tenant

    def vendor_for(session, tenant, vendor_id):
        vendor = session.scalar(select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant))
        if vendor is None:
            raise BackendError("vendor_not_found", 404)
        return vendor

    def idempotency(request):
        key = request.headers.get("Idempotency-Key", "")
        if not 1 <= len(key) <= 120 or not key.isascii() or not key.strip():
            raise BackendError("idempotency_key_required", 422)
        return key

    @app.get("/health/live")
    def live():
        return {"status": "alive", "scope": "local_backend"}

    @app.get("/health/ready")
    def ready(request: Request):
        try:
            with app.state.engine.connect() as connection:
                heads = MigrationContext.configure(connection).get_current_heads()
                status = "ready" if heads == (EXPECTED_REVISION,) else "migration_required"
        except SQLAlchemyError:
            status = "unavailable"
        return JSONResponse({"status": "ready" if status == "ready" else "not_ready", "database": status,
                             "expected_revision": EXPECTED_REVISION}, 200 if status == "ready" else 503)

    @app.get("/configuration")
    def public_configuration():
        return {"environment": "local", "extraction_schema_version": "1.2", "supported_extraction_schema_versions": ["1.1", "1.2"], "envelope_schema_version": "1.0",
                "supported_document_type": "purchase_order", "review_only": True,
                "live_processing_enabled": configuration.live_processing_enabled,
                "provider_configured": bool(configuration.live_processing_enabled and configuration.openai_api_key
                                             and configuration.openai_api_key.get_secret_value().strip()),
                "source_specific_authorization_required": True,
                "limits": {"upload_bytes": configuration.max_upload_bytes, "pages": configuration.max_pages,
                           "image_dimension": configuration.max_image_dimension, "image_pixels": configuration.max_image_pixels}}

    @app.get("/contracts/product-document/v1/schema")
    def legacy_envelope():
        return ProductDocumentV1.model_json_schema()

    @app.get("/contracts/product-document/v1.1/schema")
    def extraction_schema():
        # The frozen 1.1 contract, identical to contracts/product-document-extraction-1.1.json.
        return strict_schema("1.1")

    @app.get("/contracts/product-document/v1.1/provider-schema")
    def provider_schema():
        return strict_schema("1.1")

    @app.get("/contracts/product-document/v1.2/schema")
    def extraction_schema_v12():
        return ExtractionPayload.model_json_schema()

    @app.get("/contracts/product-document/v1.2/provider-schema")
    def provider_schema_v12():
        return strict_schema("1.2")

    @app.post("/tenants", status_code=201, response_model=TenantResponse)
    def add_tenant(body: NameRequest, request: Request):
        private(request)
        with Session(app.state.engine, expire_on_commit=False) as session:
            tenant = Tenant(name=body.name)
            session.add(tenant)
            session.commit()
            return serialize(tenant)

    @app.post("/vendors", status_code=201, response_model=VendorResponse)
    def add_vendor(body: NameRequest, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            tenant = tenant_for(request, session)
            vendor = Vendor(tenant_id=tenant, name=body.name)
            session.add(vendor)
            session.commit()
            return serialize(vendor)

    @app.post("/catalog/import", response_model=ImportedResponse)
    def catalog_import(body: CatalogImport, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            tenant = tenant_for(request, session)
            vendor_for(session, tenant, body.vendor_id)
            from backend.models import CatalogNamespace
            if session.scalar(select(CatalogNamespace.id).where(CatalogNamespace.tenant_id == tenant,
                    CatalogNamespace.vendor_id == body.vendor_id, CatalogNamespace.synthetic.is_(False))):
                raise BackendError("source_catalog_requires_versioned_adapter", 409)
            records = import_products(session, tenant, body.vendor_id, body.products)
            session.commit()
            return {"products": records}

    @app.get("/catalog", response_model=CatalogResponse)
    def catalog_read(vendor_id: UUID, request: Request, limit: int = Query(default=100, ge=1, le=1000),
                     offset: int = Query(default=0, ge=0)):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            vendor_for(session, tenant, vendor_id)
            records = session.scalars(select(CatalogProduct).where(CatalogProduct.tenant_id == tenant,
                                     CatalogProduct.vendor_id == vendor_id,
                                     CatalogProduct.review_pool_id.is_(None)).order_by(CatalogProduct.sku)
                                     .offset(offset).limit(limit + 1)).all()
            products = records[:limit]
            aliases = session.scalars(select(CatalogAlias).where(CatalogAlias.tenant_id == tenant,
                                      CatalogAlias.vendor_id == vendor_id,
                                      CatalogAlias.product_id.in_([item.id for item in products]))).all() if products else []
            return {"products": [{**serialize(record), "aliases": [serialize(alias, ["value", "source_role"])
                                      for alias in aliases if alias.product_id == record.id]} for record in products], "limit": limit,
                    "offset": offset, "next_offset": offset + limit if len(records) > limit else None}

    @app.post("/documents", status_code=201, response_model=SourceResponse)
    def upload(request: Request, file: UploadFile = File(...), vendor_id: UUID | None = Form(default=None)):
        key = idempotency(request)
        try:
            data = file.file.read(configuration.max_upload_bytes + 1)
        finally:
            file.file.close()
        metadata = validate_file(data, configuration)
        sha = digest(data)
        with Session(app.state.engine, expire_on_commit=False) as session:
            tenant = tenant_for(request, session)
            pool = None
            if vendor_id is None:
                pool = default_pool(session, tenant)
                if pool is None:
                    raise BackendError("default_catalog_pool_setup_required", 409)
                members = pool_members(session, tenant, pool.id)
                if not members:
                    raise BackendError("default_catalog_pool_empty", 409)
                vendor_id = sorted({member.vendor_id for member in members}, key=str)[0]
            else:
                vendor_for(session, tenant, vendor_id)
            payload_hash = fingerprint({"sha256": sha, "vendor_id": str(vendor_id),
                                        "catalog_pool_id": str(pool.id) if pool else None, **metadata})
            lock_key(session, tenant, "upload", key)
            receipt = session.scalar(select(UploadReceipt).where(UploadReceipt.tenant_id == tenant, UploadReceipt.idempotency_key == key))
            if receipt:
                if receipt.payload_hash != payload_hash:
                    raise BackendError("idempotency_payload_conflict", 409)
                return serialize(source_for(session, tenant, receipt.source_document_id))
            lock_key(session, tenant, "source", f"{vendor_id}:{pool.id if pool else 'legacy'}:{sha}")
            source = session.scalar(select(SourceDocument).where(SourceDocument.tenant_id == tenant,
                                    SourceDocument.vendor_id == vendor_id,
                                    SourceDocument.catalog_pool_id == (pool.id if pool else None),
                                    SourceDocument.sha256 == sha))
            if source is None:
                reference = write_source(configuration.storage_directory, data)
                source = SourceDocument(tenant_id=tenant, vendor_id=vendor_id, sha256=sha,
                                        catalog_pool_id=pool.id if pool else None,
                                        byte_size=len(data), storage_reference=reference, **metadata)
                session.add(source)
                session.flush()
            session.add(UploadReceipt(tenant_id=tenant, vendor_id=vendor_id, source_document_id=source.id,
                                      idempotency_key=key, payload_hash=payload_hash))
            session.commit()
            return serialize(source)

    @app.get("/documents/{source_id}", response_model=SourceResponse)
    def source_read(source_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            return serialize(source_for(session, tenant_for(request, session), source_id))

    @app.post("/documents/{source_id}/runs", status_code=201, response_model=RunResponse)
    def new_run(source_id: UUID, body: RunRequest, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            run = create_run(session, tenant_for(request, session), source_id, idempotency(request), body)
            session.commit()
            return serialize(run, ["id", "source_document_id", "vendor_id", "catalog_pool_id", "provider", "state", "review_state", "outcome_code", "created_at", "finished_at"])

    @app.get("/documents/{source_id}/runs", response_model=RunsResponse)
    def runs_for_source(source_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            source_for(session, tenant, source_id)
            runs = session.scalars(select(ProcessingRun).where(ProcessingRun.tenant_id == tenant,
                                   ProcessingRun.source_document_id == source_id).order_by(ProcessingRun.created_at)).all()
            return {"runs": [serialize(run, ["id", "state", "review_state", "provider", "outcome_code", "created_at", "finished_at"]) for run in runs]}

    @app.get("/runs/{run_id}", response_model=RunResponse)
    def run_read(run_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            return serialize(run_for(session, tenant_for(request, session), run_id),
                             ["id", "source_document_id", "vendor_id", "catalog_pool_id", "provider", "state", "review_state", "outcome_code", "created_at", "finished_at"])

    @app.post("/runs/{run_id}/process", response_model=RunResponse)
    def process(run_id: UUID, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            run = process_run(session, tenant_for(request, session), run_id, configuration, provider)
            return serialize(run, ["id", "source_document_id", "vendor_id", "catalog_pool_id", "provider", "state", "review_state", "outcome_code", "created_at", "finished_at"])

    @app.get("/runs/{run_id}/readiness", response_model=RunReadinessResponse)
    def run_readiness(run_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run = run_for(session, tenant, run_id)
            source = source_for(session, tenant, run.source_document_id)
            attempts = session.scalars(select(ProviderAttempt).where(
                ProviderAttempt.tenant_id == tenant, ProviderAttempt.run_id == run_id)).all()
            configured = bool(configuration.live_processing_enabled and configuration.openai_api_key
                              and configuration.openai_api_key.get_secret_value().strip())
            auth = (run.external_authorization or {}).get("external_processing", {})
            authorized = auth.get("authorized") is True and auth.get("source_sha256") == source.sha256
            blockers = []
            if run.state != "created": blockers.append("run_already_started_or_terminal")
            if attempts: blockers.append("provider_attempt_already_recorded")
            if any(a.state == "unknown_outcome" for a in attempts): blockers.append("unknown_outcome_no_retry")
            if run.provider == "openai" and not configured: blockers.append("provider_not_configured")
            if run.provider == "openai" and not authorized: blockers.append("source_authorization_required")
            return {"run_id": run.id, "vendor_id": run.vendor_id, "provider": run.provider,
                    "source_sha256": source.sha256, "source_authorized": authorized,
                    "provider_configured": configured, "attempt_count": len(attempts),
                    "can_process": not blockers, "blockers": blockers}

    @app.get("/runs/{run_id}/summary", response_model=ReviewSummaryResponse)
    def run_summary(run_id: UUID, request: Request):
        from backend.review_summary import reviewed_summary
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run = run_for(session, tenant, run_id)
            events = session.scalars(select(ReviewEvent).where(
                ReviewEvent.tenant_id == tenant, ReviewEvent.run_id == run_id)
                .order_by(*ReviewEvent.audit_order())).all()
            from backend.tiers import review_suggestions
            tiers = {value["row_id"]: value["tier"] for value in review_suggestions(session, tenant, run)}
            return reviewed_summary(run, [serialize(event) for event in events], tiers)

    @app.post("/runs/{run_id}/cancel", response_model=RunResponse)
    def cancel(run_id: UUID, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            run = cancel_run(session, tenant_for(request, session), run_id)
            session.commit()
            return serialize(run, ["id", "state", "review_state", "outcome_code"])

    @app.get("/runs/{run_id}/result", response_model=ResultResponse)
    def result(run_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run = run_for(session, tenant, run_id)
            attempts = session.scalars(select(ProviderAttempt).where(ProviderAttempt.tenant_id == tenant,
                                       ProviderAttempt.run_id == run_id).order_by(ProviderAttempt.created_at)).all()
            return {"extraction": run.result, "parses": run.parses, "attempts": [serialize(attempt) for attempt in attempts]}

    @app.get("/runs/{run_id}/suggestions", response_model=SuggestionsResponse)
    def suggestions(run_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run = run_for(session, tenant, run_id)
            from backend.tiers import review_suggestions
            return {"suggestions": review_suggestions(session, tenant, run)}

    @app.post("/runs/{run_id}/reviews", status_code=201, response_model=ReviewResponse)
    def review(run_id: UUID, body: ReviewRequest, request: Request):
        with Session(app.state.engine, expire_on_commit=False) as session:
            event = review_run(session, tenant_for(request, session), run_id, body)
            session.commit()
            return serialize(event)

    @app.get("/runs/{run_id}/reviews", response_model=ReviewsResponse)
    def reviews(run_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run_for(session, tenant, run_id)
            events = session.scalars(select(ReviewEvent).where(ReviewEvent.tenant_id == tenant,
                                    ReviewEvent.run_id == run_id).order_by(*ReviewEvent.audit_order())).all()
            return {"events": [serialize(event) for event in events]}

    register_website(app, configuration, private, tenant_for, vendor_for, idempotency)
    default_openapi = app.openapi
    documented = {}

    def documented_openapi():
        # FastAPI caches and returns its own schema object; annotate a private copy once so
        # repeated /openapi.json or /docs reads can never append the same header again.
        if "schema" in documented:
            return documented["schema"]
        schema = deepcopy(default_openapi())
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["LocalToken"] = {
            "type": "apiKey", "in": "header", "name": "X-Local-Token",
            "description": "Local development API token; not production tenant authentication."}
        schema["components"]["securitySchemes"]["LocalBrowserSession"] = {
            "type": "apiKey", "in": "cookie", "name": "po_local_session",
            "description": "HttpOnly, SameSite=Strict loopback session. Cookie mutations also require X-Website-CSRF."}
        public = {"/health/live", "/health/ready", "/configuration",
                  "/contracts/product-document/v1/schema", "/contracts/product-document/v1.1/schema",
                  "/contracts/product-document/v1.1/provider-schema",
                  "/contracts/product-document/v1.2/schema",
                  "/contracts/product-document/v1.2/provider-schema"}
        for path, operations in schema["paths"].items():
            if path in public:
                continue
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation["security"] = [{"LocalToken": []}, {"LocalBrowserSession": []}]
                parameters = operation.setdefault("parameters", [])
                unscoped = path in {"/tenants", "/website/workspaces", "/website/readiness"} or path.startswith("/website/corpus/")
                if not unscoped and not any(p.get("name") == "X-Tenant-ID" for p in parameters):
                    parameters.append({"name": "X-Tenant-ID", "in": "header", "required": True,
                                       "schema": {"type": "string", "format": "uuid"},
                                       "description": "Explicit local tenant scope, not an authenticated identity."})
                if method in {"post", "put", "patch", "delete"} and not any(
                        p.get("name") == "X-Website-CSRF" for p in parameters):
                    parameters.append({"name": "X-Website-CSRF", "in": "header", "required": False,
                        "schema": {"type": "string"},
                        "description": "Required for cookie-authenticated browser mutations; not needed with an explicit CLI token."})
                if method == "post" and path in {"/documents", "/documents/{source_id}/runs"} and not any(p.get("name") == "Idempotency-Key" for p in parameters):
                    parameters.append({"name": "Idempotency-Key", "in": "header", "required": True,
                                       "schema": {"type": "string", "minLength": 1, "maxLength": 120},
                                       "description": "Tenant-scoped request key; different payload with same key conflicts."})
        documented["schema"] = schema
        return schema

    app.openapi = documented_openapi
    return app
