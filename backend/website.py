"""Same-origin local website. Browser sessions never receive provider/API keys."""
import hmac
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.config import ROOT
from backend.contracts import ExtractionPayload
from backend.errors import BackendError
from backend.models import CatalogNamespace, CatalogProduct, CatalogSourceProduct, SourceDocument, Vendor
from backend.service import run_for, serialize, source_for
from backend.synthetic import generate_fixture
from backend.uploads import digest, read_source
from gate_a.models import Tenant

COOKIE = "po_local_session"
CORPUS = ROOT / "data" / "website" / "corpus"
WEB = ROOT / "web" / "local-reader"


class WebsiteSessionBoundary:
    """Translate an HttpOnly local browser session into the existing API boundary.

    Cookie mutations also require an unpredictable, in-memory CSRF header.
    Explicit CLI tokens retain the previous API behavior. No production identity
    or customer account authentication is implied by a local browser session.
    """
    def __init__(self, app, settings, session_token, csrf_token):
        self.app, self.settings = app, settings
        self.session_token, self.csrf_token = session_token, csrf_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b"cookie", b"").decode("latin1"))
            supplied = cookies[COOKIE].value if COOKIE in cookies else ""
        except Exception:
            supplied = ""
        cookie_ok = hmac.compare_digest(supplied.encode(), self.session_token.encode())
        if cookie_ok and b"x-local-token" not in headers:
            host = headers.get(b"host", b"").decode("latin1")
            expected = f"{scope.get('scheme', 'http')}://{host}".encode()
            origin = headers.get(b"origin")
            if headers.get(b"sec-fetch-site") == b"cross-site" or (origin is not None and origin != expected):
                return await JSONResponse({"error": "cross_origin_session_denied"}, 403)(scope, receive, send)
            if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                csrf = headers.get(b"x-website-csrf", b"")
                if not hmac.compare_digest(csrf, self.csrf_token.encode()):
                    return await JSONResponse({"error": "website_csrf_required"}, 403)(scope, receive, send)
            scope = dict(scope)
            scope["headers"] = [*scope["headers"], (b"x-local-token",
                self.settings.local_api_token.get_secret_value().encode())]

        async def protected_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [*message.get("headers", []),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer")]
            await send(message)
        return await self.app(scope, receive, protected_send)


def corpus_index():
    try:
        index = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
        return index["documents"]
    except (OSError, ValueError, KeyError):
        return []


def corpus_source(source_hash):
    if not re.fullmatch("[a-f0-9]{64}", source_hash):
        raise BackendError("corpus_document_not_found", 404)
    record = next((item for item in corpus_index() if item["sha256"] == source_hash), None)
    if record is None:
        raise BackendError("corpus_document_not_found", 404)
    path = CORPUS / (source_hash + ".pdf")
    if path.is_symlink() or not path.resolve().is_relative_to(CORPUS.resolve()):
        raise BackendError("invalid_storage_reference", 503)
    try:
        data = path.read_bytes()
    except OSError:
        raise BackendError("source_storage_unavailable", 503) from None
    if digest(data) != source_hash:
        raise BackendError("source_integrity_failed", 409)
    return data, record


def preview(data, media_type, page, bbox=None):
    try:
        result = subprocess.run([sys.executable, "-m", "backend.preview_worker", media_type, str(page),
            json.dumps(bbox)], input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        raise BackendError("preview_unavailable", 422) from None
    if result.returncode or not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise BackendError("preview_unavailable", 422)
    return Response(result.stdout, media_type="image/png")


def register_website(app, settings, private, tenant_for, vendor_for, idempotency):
    @app.get("/", include_in_schema=False)
    def home(request: Request):
        host = urlsplit("http://" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise BackendError("loopback_host_required", 403)
        response = FileResponse(WEB / "index.html", media_type="text/html")
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") != "cross-site" and (not origin or origin == str(request.base_url).rstrip("/")):
            response.set_cookie(COOKIE, app.state.website_cookie, httponly=True,
                samesite="strict", max_age=28800, path="/")
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; "
            "frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
        return response

    app.mount("/web-assets", StaticFiles(directory=WEB), name="local-website-assets")

    @app.get("/website/session", include_in_schema=False)
    def session_info(request: Request):
        # Only browser cookie grants the CSRF value; a token-only CLI cannot
        # accidentally expose its token through frontend configuration.
        if not hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), app.state.website_cookie.encode()):
            raise BackendError("website_session_required", 401)
        private(request)
        return {"csrf": app.state.website_csrf, "review_only": True}

    @app.get("/website/workspaces")
    def workspaces(request: Request):
        private(request)
        with Session(app.state.engine) as session:
            rows = session.execute(select(Tenant, Vendor, CatalogNamespace).join(Vendor, Vendor.tenant_id == Tenant.id)
                .join(CatalogNamespace, (CatalogNamespace.tenant_id == Tenant.id) & (CatalogNamespace.vendor_id == Vendor.id))
                .order_by(Tenant.name, CatalogNamespace.synthetic, Vendor.name)).all()
            result = {}
            for tenant, vendor, namespace in rows:
                scope = result.setdefault(str(tenant.id), {"id": str(tenant.id), "name": tenant.name, "catalogs": []})
                count = session.scalar(select(func.count()).select_from(CatalogProduct).where(
                    CatalogProduct.tenant_id == tenant.id, CatalogProduct.vendor_id == vendor.id))
                scope["catalogs"].append({"id": str(vendor.id), "name": vendor.name, "product_count": count,
                    "synthetic": namespace.synthetic, "source_filename": namespace.source_filename,
                    "adapter_version": namespace.adapter_version, "assigned_by": namespace.assigned_by})
            return {"workspaces": list(result.values())}

    @app.get("/website/catalog")
    def browse(request: Request, vendor_id: UUID, q: str = Query(default="", max_length=120),
               offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=50)):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            vendor_for(session, tenant, vendor_id)
            conditions = [CatalogProduct.tenant_id == tenant, CatalogProduct.vendor_id == vendor_id, CatalogProduct.active.is_(True)]
            if q.strip():
                conditions.append(or_(CatalogProduct.sku.icontains(q.strip(), autoescape=True),
                    CatalogProduct.description.icontains(q.strip(), autoescape=True)))
            total = session.scalar(select(func.count()).select_from(CatalogProduct).where(*conditions))
            records = session.scalars(select(CatalogProduct).where(*conditions)
                .order_by(CatalogProduct.sku, CatalogProduct.id).offset(offset).limit(limit)).all()
            return {"products": [serialize(p, ["id", "sku", "description"]) for p in records],
                "total": total, "offset": offset, "next_offset": offset + limit if offset + limit < total else None}

    @app.get("/website/catalog/{product_id}")
    def detail(product_id: UUID, request: Request, vendor_id: UUID):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            vendor_for(session, tenant, vendor_id)
            product = session.scalar(select(CatalogProduct).where(CatalogProduct.tenant_id == tenant,
                CatalogProduct.vendor_id == vendor_id, CatalogProduct.id == product_id))
            if product is None:
                raise BackendError("catalog_product_not_found", 404)
            source = session.scalar(select(CatalogSourceProduct).where(CatalogSourceProduct.tenant_id == tenant,
                CatalogSourceProduct.vendor_id == vendor_id, CatalogSourceProduct.product_id == product_id))
            return {"product": serialize(product, ["id", "sku", "description"]),
                "source": serialize(source, ["source_row_number", "raw_fields", "attributes", "detail_sections"]) if source else None}

    @app.get("/website/corpus")
    def library(request: Request):
        private(request)
        return {"documents": corpus_index(), "extraction_status": "not_processed",
            "catalog_selection_required": True}

    @app.get("/website/corpus/{source_hash}/content")
    def corpus_content(source_hash: str, request: Request):
        private(request)
        data, record = corpus_source(source_hash)
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="purchase-order.pdf"'})

    @app.get("/website/corpus/{source_hash}/pages/{page_number}")
    def corpus_page(source_hash: str, page_number: int, request: Request):
        private(request)
        data, record = corpus_source(source_hash)
        if not 1 <= page_number <= record["page_count"]:
            raise BackendError("page_outside_document", 422)
        return preview(data, "application/pdf", page_number)

    @app.get("/website/demo-document", include_in_schema=False)
    def fictional_document(request: Request):
        private(request)
        return Response(generate_fixture(), media_type="application/pdf")

    @app.get("/documents")
    def document_list(request: Request, vendor_id: UUID, limit: int = Query(default=50, ge=1, le=100)):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            vendor_for(session, tenant, vendor_id)
            return {"documents": [serialize(s) for s in session.scalars(select(SourceDocument).where(
                SourceDocument.tenant_id == tenant, SourceDocument.vendor_id == vendor_id)
                .order_by(SourceDocument.created_at.desc(), SourceDocument.id).limit(limit))]}

    @app.get("/documents/{source_id}/content")
    def original(source_id: UUID, request: Request):
        with Session(app.state.engine) as session:
            source = source_for(session, tenant_for(request, session), source_id)
            data = read_source(settings.storage_directory, source.storage_reference, source.sha256)
            return Response(data, media_type=source.media_type, headers={"Content-Disposition": 'attachment; filename="source-document"'})

    @app.get("/documents/{source_id}/pages/{page_number}")
    def source_page(source_id: UUID, page_number: int, request: Request):
        with Session(app.state.engine) as session:
            source = source_for(session, tenant_for(request, session), source_id)
            if not 1 <= page_number <= source.page_count:
                raise BackendError("page_outside_document", 422)
            return preview(read_source(settings.storage_directory, source.storage_reference, source.sha256),
                source.media_type, page_number)

    @app.get("/runs/{run_id}/rows/{row_id:path}/preview")
    def row_preview(run_id: UUID, row_id: str, request: Request):
        with Session(app.state.engine) as session:
            tenant = tenant_for(request, session)
            run = run_for(session, tenant, run_id)
            if not run.result:
                raise BackendError("run_has_no_result", 409)
            payload = ExtractionPayload.model_validate(run.result)
            row = next((r for r in payload.rows if r.row_id == row_id), None)
            if not row or not row.evidence:
                raise BackendError("row_evidence_unavailable", 404)
            reference = row.evidence[0]
            page = next(p for p in payload.pages if p.page_number == reference.page_number)
            region = next((r for r in page.regions if r.region_reference == reference.region_reference), None)
            source = source_for(session, tenant, run.source_document_id)
            return preview(read_source(settings.storage_directory, source.storage_reference, source.sha256),
                source.media_type, reference.page_number, region.bbox.model_dump() if region else None)
