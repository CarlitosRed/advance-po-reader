"""Explicit, scoped human classification answers; none approves a product."""
from sqlalchemy import select

from backend.catalog import _candidate, _require_vendor, normalize_identifier
from backend.errors import BackendError
from backend.models import CatalogProduct, CatalogAlias
from backend.pools import pool_vendor_ids, validate_pool_candidate

BINDING_ACTIONS = {"this_is_product", "new_product", "propose_candidate"}
EXCLUSION_ACTIONS = {"not_a_product", "not_product"}


def scoped_product(session, tenant, run, catalog_id):
    product = session.scalar(select(CatalogProduct).where(CatalogProduct.tenant_id == tenant,
        CatalogProduct.id == catalog_id, CatalogProduct.active.is_(True)))
    if product is None or (run.catalog_pool_id is not None and not validate_pool_candidate(
            session, tenant, run.catalog_pool_id, product.vendor_id, product.id)) or (
            run.catalog_pool_id is None and (product.vendor_id != run.vendor_id or product.review_pool_id is not None)):
        raise BackendError("proposed_candidate_outside_catalog", 422)
    return product


def explicit_answer(session, tenant, run, row, request):
    if row.row_kind not in {"product", "unknown"} or row.row_role in {"continuation", "document_detail"}:
        raise BackendError("document_detail_cannot_be_classified_as_product", 422)
    if request.action in EXCLUSION_ACTIONS:
        return {"resolution": "excluded", "decision": "not_a_product"}
    if request.action == "this_is_product":
        product = scoped_product(session, tenant, run, request.catalog_id)
    else:
        vendor = request.vendor_id or run.vendor_id
        if run.catalog_pool_id is not None:
            vendors = pool_vendor_ids(session, tenant, run.catalog_pool_id)
            if request.vendor_id is None and len(vendors) != 1:
                raise BackendError("new_product_requires_explicit_pool_vendor", 422)
            if vendor not in vendors:
                raise BackendError("new_product_vendor_outside_pool", 422)
        elif vendor != run.vendor_id:
            raise BackendError("new_product_vendor_outside_run", 422)
        if session.scalar(select(CatalogProduct.id).where(CatalogProduct.tenant_id == tenant,
                CatalogProduct.vendor_id == vendor, CatalogProduct.sku == request.product.sku)):
            raise BackendError("product_exists_use_this_is_product", 409)
        _require_vendor(session, tenant, vendor)
        product = CatalogProduct(tenant_id=tenant, vendor_id=vendor, sku=request.product.sku,
            description=request.product.description, normalized_sku=normalize_identifier(request.product.sku),
            origin="review", review_pool_id=run.catalog_pool_id)
        session.add(product)
        session.flush()
        for alias in request.product.aliases:
            session.add(CatalogAlias(tenant_id=tenant, vendor_id=vendor, product_id=product.id,
                value=alias.value, source_role=alias.source_role, normalized_value=normalize_identifier(alias.value)))
        session.flush()
    candidate = _candidate(product, "human_review")
    if run.catalog_pool_id is not None:
        candidate["origin_vendor_id"] = str(product.vendor_id)
    return {"decision": "this_is_product", "candidates": [candidate],
            "resolution": "needs_approval"}
