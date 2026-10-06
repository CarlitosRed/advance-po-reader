"""Review tiers are independent of retrieval outcome and human approval."""
import re
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from backend.catalog import CANONICAL_SKU_ROLES, _description_code_hints, _numeric_description_code_hints
from backend.catalog import normalize_identifier
from backend.contracts import ExtractionPayload
from backend.models import CatalogProduct, Suggestion
from backend.review_summary import effective_row_role

# Broader labeled readings veto Certain even when the conservative retrieval
# hint path cannot yet discover that SKU (F7 remains a separate PR B repair).
LABELED_CODE = re.compile(r"\b(?:code|sku|product\s+(?:code|id)|item\s+(?:code|id))\b\s*[:#=]?\s*"
                          r"([A-Z0-9][A-Z0-9._/-]{0,39})(?![A-Z0-9._/-])", re.IGNORECASE)


# Documented bounds on the tenant-SKU lookup. A row beyond the per-row bound is never Certain; a row whose keys
# would exceed the per-run budget is never checked, so it is never Certain either (a cap or skipped check must never
# make a row looser; catalog-unknown relaxations are never applied to it). The lookup itself is chunked so one statement never approaches the driver parameter limit.
MAX_READINGS_PER_ROW = 40
MAX_LOOKUP_KEYS_PER_RUN = 20000
LOOKUP_BATCH = 1000


def _same_code(value, sku, known_skus=None):
    """The same product: literally equal, equal after normalization (both keys nonempty), or the SKU preceded by a
    printed letters-only vendor prefix token ("WER D6210-1", "WER-D6210-1"); the SKU must be the whole trailing
    token and the prefix may not hold digits. A reading that is itself ANOTHER active catalog SKU is never the same
    product (checked before prefix equivalence), and non-ASCII originals are never normalized or prefix-matched."""
    if value == sku:
        return True
    if not (value.isascii() and sku.isascii()):
        return False
    value_key, sku_key = normalize_identifier(value), normalize_identifier(sku)
    if value_key and value_key == sku_key:
        return True
    if known_skus is not None and value_key and value_key in known_skus:
        return False
    text, key = " ".join(value.upper().split()), " ".join(sku.upper().split())
    if not key or len(text) <= len(key) + 1 or not text.endswith(key) or text[-len(key) - 1] not in " -/":
        return False
    prefix = [token for token in re.split(r"[\s/-]+", text[:-len(key)]) if token]
    return bool(prefix) and all(token.isalpha() and token.isascii() for token in prefix)


# Sizes, dimensions and specs ("10MM", "250ML", "12IN48IN10.5") look code-shaped to the description
# extractors but are not product codes. Only digit groups with a known unit count as a measurement.
_UNIT = (r"(?:mm|cm|m|in|ft|yd|oz|lbs?|kg|g|gr|mg|ml|l|lt|ltr|gal|qt|pt|pk|pc|pcs|ct|ea|mil|mic|um|"
         r"v|w|kw|hp|amp|psi|bar|hz|ga|sf|lf)")
_NUMBER = r"\d+(?:[.,]\d+)?"
MEASUREMENT = re.compile(rf"^{_NUMBER}(?:{_UNIT})?(?:[-./xX*]?{_NUMBER}(?:{_UNIT})?)*$", re.IGNORECASE)


def looks_like_measurement(token):
    return bool(MEASUREMENT.match(token)) and bool(re.search(rf"\d{_UNIT}(?![A-Za-z])", token, re.IGNORECASE))


def description_hints(row):
    """(extractor, token) pairs read from the description; the same three readings the tier always used."""
    description = row.description.raw_value
    return ([("code", token) for token in _description_code_hints(description)] +
            [("numeric", token) for token in _numeric_description_code_hints(description)] +
            [("labeled", token) for token in LABELED_CODE.findall(description or "")])


def canonical_codes(row):
    return [identifier for identifier in row.identifiers
            if identifier.source_role in CANONICAL_SKU_ROLES and identifier.raw_value]


def too_many_readings(row):
    """True when the row carries more code-like readings than can be checked; such a row is never Certain."""
    return len(description_hints(row)) + len(canonical_codes(row)) > MAX_READINGS_PER_ROW


def hint_keys(row):
    """Normalized description hints and canonical code readings: the keys to look up among the tenant's SKUs."""
    if too_many_readings(row):
        return set()
    return ({normalize_identifier(token) for _, token in description_hints(row)} |
            {normalize_identifier(identifier.raw_value) for identifier in canonical_codes(row)}) - {""}


def _split_hints(row, sku, known_skus):
    """Return (vetoing, ignored). A hint is ignored when it is the candidate SKU (prefix-tolerant), a measurement
    that is not a catalog SKU, or (catalog known) not any active catalog SKU of the tenant. A hint equal to a
    different catalog SKU, or an unmeasured code-shaped token when the catalog is unknown, still vetoes."""
    vetoing, ignored = [], []
    for extractor, token in description_hints(row):
        key = normalize_identifier(token)
        other_product = known_skus is not None and key in known_skus
        if _same_code(token, sku, known_skus):
            ignored.append((extractor, token, "candidate_sku"))
        elif other_product or not key:      # another product, or a reading that cannot be normalized or checked
            vetoing.append((extractor, token))
        elif looks_like_measurement(token):
            ignored.append((extractor, token, "measurement"))
        elif known_skus is not None and extractor != "labeled":
            ignored.append((extractor, token, "not_a_catalog_code"))
        else:
            vetoing.append((extractor, token))
    return vetoing, ignored


def _split_codes(row, sku, known_skus):
    """Return (conflicting, ignored) canonical code readings that are not the candidate SKU. The printed code
    column is proof of the candidate when one observed reading is literally the SKU; any OTHER reading (a
    customer or secondary item number, a substring of the SKU, ...) then conflicts only when it is another
    active catalog SKU. Without that literal proof, or without catalog info, every other reading conflicts."""
    others = [identifier.raw_value for identifier in canonical_codes(row) if not _same_code(identifier.raw_value, sku, known_skus)]
    proven = known_skus is not None and any(
        identifier.raw_value == sku and identifier.state == "observed" for identifier in canonical_codes(row))
    if not proven:
        return others, []
    conflicting = [value for value in others if not normalize_identifier(value) or normalize_identifier(value) in known_skus]
    return conflicting, [value for value in others if value not in conflicting]


def ignored_hint_evidence(row, suggestion, known_skus=None, check_skipped=False):
    """Value-free evidence for readings the tier ignored: extractor, shape class and reason only, never the text."""
    if too_many_readings(row):
        return [{"kind": "readings_not_checked", "reason": "too_many_readings"}]
    if check_skipped:
        return [{"kind": "readings_not_checked", "reason": "lookup_budget_exhausted"}]
    if len(suggestion["candidates"]) != 1:
        return []
    sku = suggestion["candidates"][0]["sku"]
    _, ignored = _split_hints(row, sku, known_skus)
    unverifiable = [{"kind": "reading_unverifiable", "extractor": extractor, "reason": "not_normalizable",
                     "length": len(value)} for extractor, value in
                    description_hints(row) + [("code_column", i.raw_value) for i in canonical_codes(row)]
                    if not normalize_identifier(value) and value != sku]
    found = [{"kind": "description_hint_ignored", "extractor": extractor, "reason": reason, "length": len(token)}
             for extractor, token, reason in ignored if reason != "candidate_sku"]
    return unverifiable + found + [{"kind": "code_reading_ignored", "extractor": "code_column", "reason": "not_a_catalog_code",
                     "length": len(value)} for value in _split_codes(row, sku, known_skus)[1]]


def confidence_tier(row, suggestion, known_skus=None, check_skipped=False):
    """known_skus: normalized active catalog SKUs of the tenant that appear as description hints or code readings,
    or None when the catalog is unknown (then every other reading conflicts). check_skipped: the catalog lookup for
    this row was skipped (run budget spent); that is not "catalog unknown" and is never Certain."""
    candidates = suggestion["candidates"]
    if too_many_readings(row):
        return "uncertain", "Too many code-like readings to verify against the catalog"
    if check_skipped:
        return "uncertain", "Catalog check skipped because the lookup budget for this run was spent"
    fields = [*row.identifiers, row.description, row.quantity, row.unit]
    if (row.row_kind != "product" or row.uncertainty or
            any(field.state in {"uncertain", "unreadable"} or field.alternative_readings for field in fields) or
            suggestion["outcome"] != "suggested" or len(candidates) != 1):
        return "uncertain", "Unresolved source evidence, classification or candidate ambiguity"
    candidate = candidates[0]
    codes = canonical_codes(row)
    vetoing, ignored = _split_hints(row, candidate["sku"], known_skus)
    conflicting, other_codes = _split_codes(row, candidate["sku"], known_skus)
    if conflicting or vetoing:
        return "uncertain", "Code-column and description readings conflict with the candidate"
    skipped = sum(reason != "candidate_sku" for _, _, reason in ignored) + len(other_codes)
    note = f"; {skipped} other reading(s) ignored (measurement or not a catalog code)" if skipped else ""
    if (suggestion["method"] == "exact" and codes and
            all(identifier.state == "observed" for identifier in codes) and
            any(identifier.raw_value == candidate["sku"] for identifier in codes)):
        return "certain", "Unique literal code-column match; explicit human approval still required" + note
    return "probable", "Description, embedded-code, alias or normalized match requires confirmation" + note


def _known_catalog_skus(session, tenant, keys):
    found, ordered = set(), sorted(keys)
    for start in range(0, len(ordered), LOOKUP_BATCH):
        found.update(session.scalars(select(CatalogProduct.normalized_sku).where(
            CatalogProduct.tenant_id == tenant, CatalogProduct.active.is_(True),
            CatalogProduct.normalized_sku.in_(ordered[start:start + LOOKUP_BATCH]))))
    return found


def review_suggestions(session, tenant, run):
    records = session.scalars(select(Suggestion).where(Suggestion.tenant_id == tenant,
        Suggestion.run_id == run.id).order_by(Suggestion.row_id)).all()
    by_row = {record.row_id: record for record in records}
    if not run.result:
        return []
    payload = ExtractionPayload.model_validate(run.result)
    values = []
    product_rows = [row for row in payload.rows
                    if effective_row_role(row, payload.schema_version) in {"product_item", "unknown"}]
    keys, unchecked = set(), set()
    for row in product_rows:
        wanted = hint_keys(row)
        if len(keys) + len(wanted - keys) > MAX_LOOKUP_KEYS_PER_RUN:
            unchecked.add(row.row_id)      # budget spent: never checked, never Certain
        else:
            keys |= wanted
    known_skus = _known_catalog_skus(session, tenant, keys)
    for row in payload.rows:
        if effective_row_role(row, payload.schema_version) not in {"product_item", "unknown"}:
            continue
        record = by_row.get(row.row_id)
        value = ({column.name: getattr(record, column.name) for column in record.__table__.columns}
                 if record else {"id": uuid5(NAMESPACE_URL, f"{run.id}:{row.row_id}"),
                     "tenant_id": tenant, "run_id": run.id, "row_id": row.row_id,
                     "candidates": [], "method": "none", "outcome": "no_match",
                     "retrieval_version": "review-tiers-v1", "evidence": [],
                     "reason": "Unknown source row requires an explicit three-way decision",
                     "created_at": run.created_at})
        skipped = row.row_id in unchecked
        value["tier"], value["tier_reason"] = confidence_tier(row, value, known_skus, skipped)
        value["evidence"] = [*value["evidence"], *ignored_hint_evidence(row, value, known_skus, skipped)]
        value["approval_status"] = "needs_approval"
        value["suggested_candidate_id"] = value["candidates"][0]["candidate_id"] if value["tier"] == "certain" else None
        values.append(value)
    return values
