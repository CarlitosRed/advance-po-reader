"""Conservative candidate retrieval, always scoped and always awaiting human review.

Exact source strings come first. Normalized strings are search variants only;
they are never written back to extraction evidence. No function resolves a row.
"""

import re
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select, text, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import CatalogAlias, CatalogProduct, CatalogPoolMember, CatalogSourceProduct, Vendor

CANONICAL_SKU_ROLES = frozenset({"sku", "vendor_sku", "vendor_product_code"})
MAX_CANDIDATES = 20


class CatalogScopeError(ValueError):
    pass


class CatalogConflictError(ValueError):
    pass


class AliasInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: str = Field(min_length=1, max_length=200)
    source_role: str = Field(min_length=1, max_length=80)

    @field_validator("value", "source_role")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Catalog strings cannot be blank")
        return value


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sku: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    aliases: tuple[AliasInput, ...] = Field(default=(), max_length=50)

    @field_validator("sku", "description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Catalog strings cannot be blank")
        return value


def normalize_identifier(value: str) -> str:
    """A cautious ASCII-only search key; non-ASCII needs explicit aliases/review."""
    if not value.isascii():
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _require_vendor(session: Session, tenant_id: UUID, vendor_id: UUID) -> None:
    if session.scalar(select(Vendor.id).where(Vendor.tenant_id == tenant_id, Vendor.id == vendor_id)) is None:
        raise CatalogScopeError("Vendor does not exist in this tenant")


def _candidate(product: CatalogProduct, method: str, score=None) -> dict:
    result = {"candidate_id": str(product.id), "sku": product.sku,
              "description": product.description, "method": method}
    if score is not None:
        result["score"] = str(Decimal(str(score)).quantize(Decimal("0.000001")))
    return result


def import_products(session: Session, tenant_id: UUID, vendor_id: UUID,
                    products: list[ProductInput]) -> list[dict]:
    """Append supplied catalog/alias records atomically; never invent or overwrite.

    Identical reimports are safe. A SKU with changed descriptive evidence or an
    alias already assigned to another product is a conflict needing an explicit
    future catalog versioning workflow. The caller owns the transaction commit.
    """
    _require_vendor(session, tenant_id, vendor_id)
    if not 1 <= len(products) <= 1000:
        raise ValueError("Catalog import requires 1 to 1000 products")
    result = []
    try:
        with session.begin_nested():
            for entry in products:
                entry = ProductInput.model_validate(entry)
                product = session.scalar(select(CatalogProduct).where(
                    CatalogProduct.tenant_id == tenant_id,
                    CatalogProduct.vendor_id == vendor_id,
                    CatalogProduct.sku == entry.sku,
                ))
                if product is None:
                    product = CatalogProduct(tenant_id=tenant_id, vendor_id=vendor_id,
                        sku=entry.sku, description=entry.description,
                        normalized_sku=normalize_identifier(entry.sku), active=True)
                    session.add(product)
                    session.flush()
                elif product.description != entry.description or not product.active:
                    raise CatalogConflictError("Existing SKU conflicts with supplied catalog record")
                for alias in entry.aliases:
                    existing = session.scalar(select(CatalogAlias).where(
                        CatalogAlias.tenant_id == tenant_id, CatalogAlias.vendor_id == vendor_id,
                        CatalogAlias.source_role == alias.source_role, CatalogAlias.value == alias.value,
                    ))
                    if existing is not None:
                        if existing.product_id != product.id:
                            raise CatalogConflictError("Alias is assigned to a different catalog product")
                    else:
                        session.add(CatalogAlias(tenant_id=tenant_id, vendor_id=vendor_id,
                            product_id=product.id, value=alias.value,
                            normalized_value=normalize_identifier(alias.value), source_role=alias.source_role))
                        session.flush()
                result.append(_candidate(product, "catalog_import"))
    except IntegrityError:
        raise CatalogConflictError("Catalog import conflicts with existing scoped records") from None
    return result


def _result(method: str, rows: list, limit: int) -> dict:
    truncated = len(rows) > limit
    candidates = rows[:limit]
    outcome = "no_match" if not rows else ("ambiguous" if len(rows) > 1 else "suggested")
    reason = ("No candidate found in the supplied tenant/vendor catalog" if not rows else
              "Candidate requires explicit human approval" if len(rows) == 1 else
              "Multiple candidates require human review; no candidate was selected")
    if truncated:
        reason += "; additional hits omitted by candidate bound"
    return {"method": method, "outcome": outcome, "reason": reason, "candidates": candidates}


def pg_trgm_available(session: Session) -> bool:
    """Extension absence is an expected exact/normalized-only capability state."""
    return bool(session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
        "WHERE e.extname='pg_trgm' AND n.nspname='public')"
    )))


def retrieve_candidates(session: Session, tenant_id: UUID, vendor_id: UUID | None,
                        identifiers: list[dict], description: str | None,
                        limit: int = 5, *, vendor_ids: list[UUID] | None = None,
                        pool_id: UUID | None = None) -> dict:
    """Return a bounded candidate snapshot; exact hits do not auto-resolve.

    Unknown identifier roles can use explicitly supplied same-role aliases but
    never silently act as vendor SKUs. pg_trgm queries use indexed operators;
    when absent there is no unbounded Python scan or embedding fallback.
    """
    vendors = sorted(set(vendor_ids or ([vendor_id] if vendor_id else [])), key=str)
    if not vendors:
        raise CatalogScopeError("Catalog retrieval requires an explicit vendor or pool")
    for scoped_vendor in vendors:
        _require_vendor(session, tenant_id, scoped_vendor)
    if pool_id is not None:
        membership = set(session.scalars(select(CatalogPoolMember.vendor_id).where(
            CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id)).all())
        if not membership or not set(vendors).issubset(membership):
            raise CatalogScopeError("Pool vendor scope does not match its persisted membership")
    if not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("Candidate limit must be between 1 and 20")
    if len(identifiers) > 20:
        raise ValueError("At most 20 source identifiers may be queried")
    evidence = []
    for item in identifiers:
        raw, role = item.get("raw_value"), item.get("source_role")
        if raw is None:
            continue
        if not isinstance(raw, str) or len(raw) > 200:
            raise ValueError("Source identifier must be a string of at most 200 characters")
        if role is not None and (not isinstance(role, str) or len(role) > 80):
            raise ValueError("Source identifier role must be a string of at most 80 characters")
        if raw.strip():
            evidence.append((raw, role))
    if description is not None and (not isinstance(description, str) or len(description) > 4000):
        raise ValueError("Description must be a string of at most 4000 characters")
    scope = [CatalogProduct.tenant_id == tenant_id, CatalogProduct.vendor_id.in_(vendors),
             CatalogProduct.active.is_(True)]
    if pool_id is not None:
        scope.append(CatalogProduct.id.in_(select(CatalogSourceProduct.product_id).join(CatalogPoolMember,
            (CatalogPoolMember.tenant_id == CatalogSourceProduct.tenant_id) &
            (CatalogPoolMember.vendor_id == CatalogSourceProduct.vendor_id) &
            (CatalogPoolMember.namespace_id == CatalogSourceProduct.namespace_id)).where(
                CatalogPoolMember.tenant_id == tenant_id, CatalogPoolMember.pool_id == pool_id,
                CatalogSourceProduct.tenant_id == tenant_id)))
    alias_scope = [CatalogAlias.tenant_id == tenant_id, CatalogAlias.vendor_id.in_(vendors)]

    def scoped_candidate(product, method, score=None):
        result = _candidate(product, method, score)
        if pool_id is not None:
            source = session.scalar(select(CatalogSourceProduct).join(CatalogPoolMember,
                (CatalogPoolMember.tenant_id == CatalogSourceProduct.tenant_id) &
                (CatalogPoolMember.vendor_id == CatalogSourceProduct.vendor_id) &
                (CatalogPoolMember.namespace_id == CatalogSourceProduct.namespace_id)).where(
                    CatalogSourceProduct.tenant_id == tenant_id, CatalogSourceProduct.vendor_id == product.vendor_id,
                    CatalogSourceProduct.product_id == product.id, CatalogPoolMember.pool_id == pool_id))
            if source is None:
                raise CatalogScopeError("Pool candidate has no matching source namespace provenance")
            result.update({"origin_vendor_id": str(product.vendor_id), "namespace_id": str(source.namespace_id)})
        return result
    for normalized in (False, True):
        clauses, alias_clauses = [], []
        for raw, role in evidence:
            key = normalize_identifier(raw) if normalized else raw
            if not key:
                continue
            if role in CANONICAL_SKU_ROLES:
                column = CatalogProduct.normalized_sku if normalized else CatalogProduct.sku
                clauses.append(column == key)
            if role is not None:
                column = CatalogAlias.normalized_value if normalized else CatalogAlias.value
                alias_clauses.append(and_(CatalogAlias.source_role == role, column == key))
        if alias_clauses:
            clauses.append(CatalogProduct.id.in_(select(CatalogAlias.product_id).where(
                *alias_scope, or_(*alias_clauses))))
        if clauses:
            rows = list(session.scalars(select(CatalogProduct).where(*scope, or_(*clauses))
                                       .order_by(CatalogProduct.sku, CatalogProduct.id).limit(limit + 1)))
            if rows:
                method = "normalized" if normalized else "exact"
                return _result(method, [scoped_candidate(row, method) for row in rows], limit)
    # A code-like description token is a retrieval hint only. It is never
    # added to identifier observations or aliases, and it must exactly match
    # a SKU within the already selected tenant/vendor namespace.
    description_hints = _description_code_hints(description)
    hint_evidence = []
    hinted_rows = {}
    for token in description_hints:
        key = normalize_identifier(token)
        rows = list(session.scalars(select(CatalogProduct).where(
            *scope, CatalogProduct.normalized_sku == key
        ).order_by(CatalogProduct.sku, CatalogProduct.id).limit(limit + 1)))
        if rows:
            hint_evidence.append({"kind": "description_code_hint", "source": "product_description",
                                  "raw_token": token, "search_key": key,
                                  "match_method": "exact_normalized_sku"})
            for row in rows:
                hinted_rows[row.id] = row
    if hinted_rows:
        ordered = [scoped_candidate(row, "description_code_hint") for row in sorted(
            hinted_rows.values(), key=lambda item: (item.sku, str(item.id)))]
        return _result("description_code_hint", ordered, limit, hint_evidence)

    # Standalone numeric catalog codes are common, but short numeric values
    # also resemble quantities, money, dates and row references. Require a
    # clean token and literal SKU equality; never apply numeric typo search.
    numeric_hints = _numeric_description_code_hints(description)
    numeric_rows = {}
    numeric_evidence = []
    for token in numeric_hints:
        rows = list(session.scalars(select(CatalogProduct).where(
            *scope, CatalogProduct.sku == token
        ).order_by(CatalogProduct.sku, CatalogProduct.id).limit(limit + 1)))
        if rows:
            numeric_evidence.append({"kind": "description_numeric_code_hint",
                                     "source": "product_description", "raw_token": token,
                                     "match_method": "exact_sku"})
            for row in rows:
                numeric_rows[row.id] = row
    if numeric_rows:
        ordered = [scoped_candidate(row, "description_numeric_code_hint") for row in sorted(
            numeric_rows.values(), key=lambda item: (item.sku, str(item.id)))]
        return _result("description_numeric_code_hint", ordered, limit, numeric_evidence)

    # Typo recovery is limited to code-shaped description tokens and a stricter
    # SKU similarity bar than broad text retrieval. Keep it distinct from
    # identifier trigram and full-description trigram methods.
    if description_hints and pg_trgm_available(session):
        session.execute(text("SELECT set_config('pg_trgm.similarity_threshold', '0.35', true)"))
        fuzzy_rows = {}
        fuzzy_evidence = []
        for token in description_hints:
            key = normalize_identifier(token)
            # Very short codes have unstable trigram similarity and are not
            # expanded; exact description-code lookup above still supports them.
            if len(key) < 8:
                continue
            score = func.public.similarity(CatalogProduct.normalized_sku, key)
            rows = session.execute(select(CatalogProduct, score).where(
                *scope, CatalogProduct.normalized_sku.op("%") (key),
                score >= DESCRIPTION_HINT_TRGM_THRESHOLD
            ).order_by(score.desc(), CatalogProduct.sku, CatalogProduct.id).limit(limit + 1)).all()
            if rows:
                fuzzy_evidence.append({"kind": "description_code_hint", "source": "product_description",
                                       "raw_token": token, "search_key": key, "match_method": "pg_trgm_sku",
                                       "similarity_threshold": str(DESCRIPTION_HINT_TRGM_THRESHOLD)})
                for row, row_score in rows:
                    current = fuzzy_rows.get(row.id)
                    if current is None or row_score > current[1]:
                        fuzzy_rows[row.id] = (row, row_score)
        if fuzzy_rows:
            ordered = sorted(fuzzy_rows.values(), key=lambda value: (-value[1], value[0].sku, str(value[0].id)))
            candidates = [scoped_candidate(row, "description_code_hint_trigram", score)
                          for row, score in ordered]
            return _result("description_code_hint_trigram", candidates, limit, fuzzy_evidence)
    if not pg_trgm_available(session):
        result = _result("none", [], limit)
        result["reason"] += "; pg_trgm unavailable, fuzzy retrieval disabled"
        return result
    # Local transaction setting is bounded and never changes the server default.
    session.execute(text("SELECT set_config('pg_trgm.similarity_threshold', '0.35', true)"))
    searches = []
    for raw, role in evidence:
        key = normalize_identifier(raw)
        if len(key) < 3:
            continue
        if role in CANONICAL_SKU_ROLES:
            score = func.public.similarity(CatalogProduct.normalized_sku, key)
            searches.append(select(CatalogProduct.id.label("product_id"), score.label("score"))
                .where(*scope, CatalogProduct.normalized_sku.op("%") (key), score >= 0.45))
        if role is not None:
            score = func.public.similarity(CatalogAlias.normalized_value, key)
            searches.append(select(CatalogAlias.product_id.label("product_id"), score.label("score"))
                .where(*alias_scope, CatalogAlias.source_role == role,
                       CatalogAlias.normalized_value.op("%") (key), score >= 0.45))
    if description and len(description.strip()) >= 3:
        score = func.public.similarity(CatalogProduct.description, description)
        searches.append(select(CatalogProduct.id.label("product_id"), score.label("score"))
            .where(*scope, CatalogProduct.description.op("%") (description), score >= 0.35))
    if not searches:
        return _result("none", [], limit)
    matches = union_all(*searches).subquery()
    best = select(matches.c.product_id, func.max(matches.c.score).label("score")).group_by(matches.c.product_id).subquery()
    rows = session.execute(select(CatalogProduct, best.c.score).join(best, best.c.product_id == CatalogProduct.id)
        .where(*scope).order_by(best.c.score.desc(), CatalogProduct.sku, CatalogProduct.id).limit(limit + 1)).all()
    return _result("trigram" if rows else "none", [scoped_candidate(row, "trigram", score) for row, score in rows], limit)
