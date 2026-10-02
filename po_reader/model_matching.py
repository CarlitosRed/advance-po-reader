"""Model description comparison followed by catalog and source validation."""
import re
from decimal import Decimal, InvalidOperation

from .catalog import normalize_id
from .retrieval import ProductRetriever


AUTHORITATIVE_ROLES = {"vendor_product_code", "manufacturer_part_number"}
KNOWN_ROLES = AUTHORITATIVE_ROLES | {"customer_item_number", "unknown"}
RELATIONSHIPS = {"compatible", "conflict", "insufficient_information"}


def _valid_quantity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return False
    text = str(value).strip()
    if len(text) > 40 or not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return False
    try:
        number = Decimal(text)
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def _validate_comparison(result):
    if not isinstance(result, dict):
        return None
    selected = result.get("selected_product_id")
    if selected is not None and not isinstance(selected, str):
        return None
    if result.get("description_relationship") not in RELATIONSHIPS:
        return None
    conflicts = result.get("attribute_conflicts")
    if not isinstance(conflicts, list) or any(not isinstance(value, str) for value in conflicts):
        return None
    if not isinstance(result.get("reason"), str):
        return None
    return dict(selected_product_id=selected,
                description_relationship=result["description_relationship"],
                attribute_conflicts=list(conflicts), reason=result["reason"])


def _same_text(value):
    # Only whitespace and case are ignored. Punctuation, numbers, negatives and
    # variant suffixes retain their meaning; token overlap is never equivalence.
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _exact_description_comparison(line, retrieved, candidates):
    """Return a deterministic verdict only for a fully corroborated exact case."""
    exact = set(retrieved["exact_product_ids"])
    if (len(exact) != 1 or line.get("kind") != "product" or line.get("uncertainties")
            or line.get("source_validation", {}).get("status") != "corroborated"
            or not _valid_quantity(line.get("quantity"))
            or _same_text(line.get("uom")) not in {"ea", "each"}):
        return None
    selected = next(iter(exact))
    observations = retrieved["observed_identifiers"]
    if not observations or not any(item.get("role") in AUTHORITATIVE_ROLES for item in observations):
        return None
    for observation in observations:
        if (observation.get("role") not in AUTHORITATIVE_ROLES | {"customer_item_number"}
                or observation.get("status") != "observed"):
            return None
        bound = {binding["product_id"] for binding in retrieved["exact_bindings"]
                 if binding["role"] == observation["role"]
                 and normalize_id(binding["raw_value"]) == normalize_id(observation["raw_value"])}
        if bound != {selected}:
            return None
    candidate = next((item for item in candidates if item["product_id"] == selected), None)
    if candidate is None:
        return None
    description = _same_text(line.get("description"))
    variants = [candidate.get("name"), *candidate.get("variants", [])]
    if not description or not any(description == _same_text(variant) for variant in variants):
        return None
    attributes = line.get("attributes", [])
    catalog_attributes = candidate.get("attributes", {})
    if not isinstance(attributes, list) or not isinstance(catalog_attributes, dict):
        return None
    known_attributes = {_same_text(key): _same_text(value) for key, value in catalog_attributes.items()}
    for attribute in attributes:
        if (not isinstance(attribute, dict) or not _same_text(attribute.get("name"))
                or not _same_text(attribute.get("value"))
                or known_attributes.get(_same_text(attribute["name"])) != _same_text(attribute["value"])):
            return None
    return dict(selected_product_id=selected, description_relationship="compatible", attribute_conflicts=[],
                reason="Every observed identifier has one exact binding; the complete description equals a catalog name or variant and explicit attributes agree.")


class ModelMatcher:
    """Ask a provider to compare candidates; verify every automatic match."""

    def __init__(self, provider, catalog):
        self.provider = provider
        self.catalog = catalog
        self.retriever = ProductRetriever(catalog)
        self._closed = False

    def close(self):
        if not self._closed:
            self.retriever.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def match_line(self, line):
        if self._closed:
            raise RuntimeError("This model matcher is closed")
        stage_start = len(getattr(self.provider, "usage", []))
        if line.get("kind") == "charge":
            if hasattr(self.provider, "skip_adjudication"):
                self.provider.skip_adjudication("excluded_charge")
            line["retrieval"] = dict(hits=[], authority="sample_catalog",
                                     catalog_fingerprint=self.retriever.fingerprint)
            line["match"] = dict(status="excluded_charge", product_id=None,
                                 reason="Shipping charge, not a product.", suggestions=[],
                                 catalog_evidence=[], validation_errors=[])
            if getattr(self.provider, "selective_adjudication", False):
                line["cascade_stages"] = self.provider.usage[stage_start:]
            return line["match"]

        retrieved = self.retriever.retrieve_for_model(line)
        if hasattr(self.provider, "retrieve_candidates"):
            retrieved = self.provider.retrieve_candidates(line, self.catalog, retrieved)
        line["retrieval"] = retrieved
        candidates = retrieved["hits"]
        comparison_candidates = []
        for candidate in candidates:
            product = self.catalog[candidate["product_id"]]
            view = dict(product_id=candidate["product_id"], name=product["name"], variants=product["variants"])
            if "attributes" in product:
                view["attributes"] = product["attributes"]
            comparison_candidates.append(view)
        if hasattr(self.provider, "rank_candidates"):
            rank_usage_start = len(getattr(self.provider, "usage", []))
            comparison_candidates = self.provider.rank_candidates(line, comparison_candidates)
            ordering = {candidate["product_id"]: index for index, candidate in enumerate(comparison_candidates)}
            candidates.sort(key=lambda candidate: ordering[candidate["product_id"]])
            # Persist only ranking annotations. Catalog facts continue to come
            # from the catalog, not the ranker's returned model context.
            ranked_by_id = {candidate["product_id"]: candidate for candidate in comparison_candidates}
            for candidate in candidates:
                ranked_view = ranked_by_id[candidate["product_id"]]
                if "rank_score" in ranked_view:
                    candidate["rank_score"] = ranked_view["rank_score"]
            rank_record = next((record for record in reversed(getattr(self.provider, "usage", [])[rank_usage_start:])
                                if record.get("stage") == "reranking"), None)
            if rank_record is not None:
                retrieved["reranking"] = dict(
                    status="completed" if rank_record["status"] == "used" else rank_record["status"],
                    model=rank_record.get("model"), model_revision=rank_record.get("model_revision"),
                    score_type=rank_record.get("score_type"), reason=rank_record.get("reason"),
                    duration_seconds=rank_record.get("duration_seconds"),
                    score_note="Reranker scores are ranking signals, not calibrated match probabilities.")
        model_errors = []
        deterministic = (_exact_description_comparison(line, retrieved, comparison_candidates)
                         if getattr(self.provider, "selective_adjudication", False) else None)
        if deterministic is not None:
            comparison = deterministic
            self.provider.skip_adjudication("unambiguous_exact_id_and_identical_description")
            line["comparison_method"] = "deterministic_exact_description"
        elif candidates:
            line["comparison_method"] = "model_adjudication"
            try:
                comparison = _validate_comparison(self.provider.compare(line, comparison_candidates))
            except (ValueError, OSError, TimeoutError):
                comparison = None
                model_errors.append("model_comparison_failed")
            if comparison is None and not model_errors:
                model_errors.append("invalid_model_comparison")
        else:
            line["comparison_method"] = "no_candidates"
            if hasattr(self.provider, "skip_adjudication"):
                self.provider.skip_adjudication("no_catalog_candidates")
            comparison = dict(selected_product_id=None, description_relationship="insufficient_information",
                              attribute_conflicts=[], reason="No catalog candidates were retrieved.")

        comparison = comparison or dict(selected_product_id=None, description_relationship="insufficient_information",
                                        attribute_conflicts=[], reason="The model comparison could not be validated.")
        line["model_comparison"] = comparison
        errors = list(model_errors)
        if line.get("kind") != "product":
            errors.append("uncertain_row_kind")
        if not isinstance(line.get("description"), str) or not line["description"].strip():
            errors.append("missing_source_description")
        selected = comparison["selected_product_id"]
        candidate_ids = {candidate["product_id"] for candidate in candidates}
        if selected is not None and selected not in candidate_ids:
            errors.append("model_selected_outside_candidates")
            selected = None

        observations = retrieved["observed_identifiers"]
        bindings = retrieved["exact_bindings"]
        exact = set(retrieved["exact_product_ids"])
        if not observations:
            errors.append("missing_product_identifier")
        if any(observation.get("role") not in KNOWN_ROLES or observation.get("role") == "unknown"
               for observation in observations):
            errors.append("unknown_identifier_role")
        # Any visual uncertainty survives a semantically convincing comparison.
        if any(observation.get("status") != "observed"
               for observation in observations):
            errors.append("uncertain_product_identifier")

        unresolved_authoritative = []
        unresolved_customer = []
        for observation in observations:
            role = observation.get("role")
            identifier = normalize_id(observation["raw_value"])
            observation_bindings = {binding["product_id"] for binding in bindings
                                    if binding["role"] == role and normalize_id(binding["raw_value"]) == identifier}
            if role in AUTHORITATIVE_ROLES and not observation_bindings:
                unresolved_authoritative.append(identifier)
            if role == "customer_item_number" and not observation_bindings:
                unresolved_customer.append(identifier)
            if selected and role in AUTHORITATIVE_ROLES | {"customer_item_number"} and selected not in observation_bindings:
                errors.append("selected_product_identifier_mismatch")
        if unresolved_customer:
            errors.append("customer_identifier_without_approved_alias")
        if len(exact) > 1:
            errors.append("conflicting_authoritative_identifiers")
        authoritative_values = {normalize_id(observation["raw_value"]) for observation in observations
                                if observation.get("role") in AUTHORITATIVE_ROLES}
        if len(authoritative_values) > 1 and unresolved_authoritative:
            errors.append("conflicting_authoritative_identifiers")
        if unresolved_authoritative:
            errors.append("observed_identifier_not_in_catalog")
        if selected and selected not in exact:
            errors.append("selection_has_no_exact_identifier_binding")

        source_status = line.get("source_validation", {}).get("status", "missing_evidence")
        if source_status != "corroborated":
            errors.append({"vision_only": "vision_reading_needs_confirmation", "disagreement": "source_disagreement"}
                          .get(source_status, "missing_source_evidence"))
        if comparison["description_relationship"] != "compatible":
            errors.append("description_conflict" if comparison["description_relationship"] == "conflict"
                          else "insufficient_description_information")
        if comparison["attribute_conflicts"]:
            errors.append("product_attribute_conflict")
        if not _valid_quantity(line.get("quantity")):
            errors.append("invalid_or_missing_quantity")
        if not isinstance(line.get("uom"), str) or line["uom"].strip().upper() not in {"EA", "EACH"}:
            errors.append("invalid_or_unconfirmed_unit")
        if selected is None:
            errors.append("no_product_selected")
        errors = list(dict.fromkeys(errors))

        if not errors:
            status = "matched"
            reason = "Exact catalog identifier, corroborated source, compatible description, and valid each quantity."
        elif unresolved_authoritative and not exact and selected is None and not model_errors:
            status = "not_in_catalog"
            reason = "The observed product identifier was not found in the catalog."
        else:
            status = "review_needed"
            reason = "Confirm this row before adding: " + ", ".join(error.replace("_", " ") for error in errors) + "."
        hit = next((candidate for candidate in candidates if candidate["product_id"] == selected), None)
        line["match"] = dict(
            status=status, product_id=selected, reason=reason,
            suggestions=[] if status == "matched" else [dict(
                id=candidate["product_id"], name=candidate["name"],
                description_similarity=candidate["description_similarity"],
                catalog_evidence=candidate["source_observations"],
            ) for candidate in candidates],
            catalog_evidence=hit["source_observations"] if hit else [],
            validation_errors=errors, model_comparison=comparison,
        )
        if getattr(self.provider, "selective_adjudication", False):
            line["cascade_stages"] = self.provider.usage[stage_start:]
        return line["match"]
