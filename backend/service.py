"""Local processing and human review. Evidence is assigned once per run."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

from sqlalchemy import select, text

from backend.api_models import RunRequest, ReviewRequest, PageCountRequest
from backend.catalog import retrieve_candidates
from backend.contracts import ExtractionPayload, validate_payload, parsed_payload
from backend.errors import BackendError
from backend.models import SourceDocument, ProcessingRun, ProviderAttempt, Suggestion, ReviewEvent
from backend.models import CatalogProduct, CatalogSourceProduct, CatalogPoolMember
from backend.pools import pool_vendor_ids, validate_pool_candidate
from backend.providers import OpenAIProvider, SyntheticProvider
from backend.uploads import read_source
from backend.review_answers import explicit_answer, BINDING_ACTIONS, EXCLUSION_ACTIONS
from backend.tiers import review_suggestions
from gate_a.contracts import EvidenceReference, validate_run_transition


def now():
    return datetime.now(timezone.utc)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def serialize(record, fields=None):
    names = fields or [column.name for column in record.__table__.columns]
    return {name: getattr(record, name) for name in names}


def lock_key(session, tenant_id, namespace, key):
    # Transaction-scoped lock serializes same-tenant retries across requests.
    digest = hashlib.sha256(f"{tenant_id}:{namespace}:{key}".encode()).digest()
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(digest[:8], "big", signed=True)})


def source_for(session, tenant, source_id):
    source = session.scalar(select(SourceDocument).where(SourceDocument.tenant_id == tenant, SourceDocument.id == source_id))
    if source is None:
        raise BackendError("source_not_found", 404)
    return source


def run_for(session, tenant, run_id, lock=False):
    query = select(ProcessingRun).where(ProcessingRun.tenant_id == tenant, ProcessingRun.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = session.scalar(query)
    if run is None:
        raise BackendError("run_not_found", 404)
    return run


def create_run(session, tenant, source_id, key, request: RunRequest):
    source = source_for(session, tenant, source_id)
    body = {"source_id": str(source_id), **request.model_dump(mode="json")}
    payload_hash = fingerprint(body)
    lock_key(session, tenant, "run", key)
    existing = session.scalar(select(ProcessingRun).where(ProcessingRun.tenant_id == tenant, ProcessingRun.idempotency_key == key))
    if existing:
        if existing.payload_hash != payload_hash:
            raise BackendError("idempotency_payload_conflict", 409)
        return existing
    authorization = request.external_authorization
    if authorization and authorization.source_sha256 != source.sha256:
        raise BackendError("authorization_source_mismatch", 422)
    # fixture_name is request metadata, never an evidence value.
    metadata = {"fixture_name": request.fixture_name}
    if authorization:
        metadata["external_processing"] = {**authorization.model_dump(mode="json"), "recorded_at": now().isoformat()}
    run = ProcessingRun(tenant_id=tenant, source_document_id=source.id, vendor_id=source.vendor_id,
                        catalog_pool_id=source.catalog_pool_id,
                        provider=request.provider, state="created", review_state="not_started",
                        idempotency_key=key, payload_hash=payload_hash, external_authorization=metadata)
    session.add(run)
    session.flush()
    return run


def advance(run, target):
    validate_run_transition(run.state, target)
    run.state = target


def process_run(session, tenant, run_id, settings, provider_override=None):
    run = run_for(session, tenant, run_id, lock=True)
    if run.state in {"completed", "partial", "failed", "cancelled"}:
        return run
    if run.state != "created":
        raise BackendError("processing_in_progress_or_unknown_outcome", 409)
    source = source_for(session, tenant, run.source_document_id)
    advance(run, "validating")
    try:
        data = read_source(settings.storage_directory, source.storage_reference, source.sha256)
    except BackendError as error:
        advance(run, "failed")
        run.outcome_code = error.code
        run.finished_at = now()
        session.commit()
        return run
    configured = settings.live_processing_enabled and settings.openai_api_key is not None and bool(settings.openai_api_key.get_secret_value().strip())
    authorization = (run.external_authorization or {}).get("external_processing")
    if run.provider == "openai" and not configured and provider_override is None:
        advance(run, "failed")
        run.outcome_code = "provider_not_configured"
        run.finished_at = now()
        session.commit()
        return run
    if run.provider == "openai" and not (authorization and authorization.get("authorized") is True
                                        and authorization.get("source_sha256") == source.sha256):
        advance(run, "failed")
        run.outcome_code = "external_processing_authorization_required"
        run.finished_at = now()
        session.commit()
        return run
    provider = provider_override
    if provider is None:
        provider = (SyntheticProvider() if run.provider == "synthetic" else OpenAIProvider(
            api_key=settings.openai_api_key.get_secret_value(), enabled=True, model=settings.extraction_model,
            store=settings.provider_store, timeout_seconds=settings.provider_timeout_seconds))
    advance(run, "processing")
    attempt = ProviderAttempt(tenant_id=tenant, run_id=run.id, state="unknown_outcome",
                              model=getattr(provider, "model", "synthetic-fixture"),
                              prompt_version=getattr(provider, "prompt_version", "po-extraction-1.1"),
                              schema_version=getattr(provider, "schema_version", None) or
                                  ("1.2" if run.provider == "openai" or
                                   (run.external_authorization or {}).get("fixture_name") == "continuation" else "1.1"),
                              usage={}, latency_ms=0,
                              error_code="attempt_in_progress_or_interrupted", synthetic=run.provider == "synthetic")
    session.add(attempt)
    session.flush()
    attempt_id = attempt.id
    # Persist an unknown outcome BEFORE the provider boundary. No locks or DB transaction span the remote call.
    session.commit()
    try:
        outcome = provider.extract(data, source.media_type, source.page_count,
                                   fixture_name=(run.external_authorization or {}).get("fixture_name"))
    except Exception:
        # An unexpected interruption must not expose source/secret data or be retried automatically.
        run = run_for(session, tenant, run_id, lock=True)
        attempt = session.get(ProviderAttempt, attempt_id)
        attempt.error_code = "provider_outcome_unknown"
        attempt.finished_at = now()
        if run.state != "cancelled":
            advance(run, "failed")
            run.outcome_code = "unknown_outcome"
            run.finished_at = now()
        session.commit()
        return run
    run = run_for(session, tenant, run_id, lock=True)
    attempt = session.get(ProviderAttempt, attempt_id)
    attempt.state = outcome.state
    attempt.request_id = outcome.request_id
    attempt.response_id = outcome.response_id
    attempt.actual_model = getattr(outcome, "actual_model", None)
    attempt.usage = outcome.usage
    attempt.latency_ms = outcome.latency_ms
    attempt.error_code = outcome.error_code
    attempt.finished_at = now()
    # Model/prompt/schema were persisted before call, and must agree with its outcome.
    if (outcome.schema_version not in {"1.1", "1.2"} or outcome.model != attempt.model or outcome.prompt_version != attempt.prompt_version):
        attempt.state = "invalid_output"
        attempt.error_code = "provider_version_mismatch"
        outcome_payload = None
    else:
        outcome_payload = outcome.payload
    # Cancellation records the completed attempt metadata but discards its uncommitted observation.
    if run.state == "cancelled":
        session.commit()
        return run
    if outcome.state != "succeeded" or outcome_payload is None or attempt.state == "invalid_output":
        advance(run, "failed")
        run.outcome_code = attempt.error_code or attempt.state
    else:
        try:
            payload = validate_payload(outcome_payload, source.page_count)
        except Exception:
            advance(run, "failed")
            run.outcome_code = "invalid_extraction_payload"
            attempt.state = "invalid_output"
            attempt.error_code = "invalid_extraction_payload"
        else:
            run.result = payload.model_dump(mode="json")
            run.parses = parsed_payload(payload)
            if payload.document_type != "purchase_order":
                advance(run, "failed")
                run.outcome_code = "unsupported_document_type" if payload.document_type == "unsupported" else "needs_classification"
            else:
                from backend.source_checks import source_grounding
                run.parses = {**run.parses, "source_grounding": source_grounding(payload, data, source)}
                partial = payload.partial or not any(row.row_kind == "product" for row in payload.rows)
                for row in payload.rows:
                    if row.row_kind != "product":
                        continue
                    try:
                        scoped_vendors = pool_vendor_ids(session, tenant, run.catalog_pool_id) if run.catalog_pool_id else [source.vendor_id]
                        candidate_result = retrieve_candidates(
                            session, tenant, source.vendor_id,
                            [identifier.model_dump(mode="json") for identifier in row.identifiers],
                            row.description.raw_value, settings.candidate_limit,
                            vendor_ids=scoped_vendors, pool_id=run.catalog_pool_id)
                    except ValueError:
                        partial = True
                        candidate_result = {"method": "none", "outcome": "no_match", "candidates": [],
                                            "retrieval_version": "catalog-retrieval-v2", "evidence": [],
                                            "reason": "Retrieval input exceeds the bounded search contract; human review required"}
                    session.add(Suggestion(tenant_id=tenant, run_id=run.id, row_id=row.row_id, **candidate_result))
                # Independent page checks have not been supplied by a human yet.
                advance(run, "partial")
                run.outcome_code = "review_required" if partial else "independent_coverage_required"
    run.finished_at = now()
    session.commit()
    return run


def cancel_run(session, tenant, run_id):
    run = run_for(session, tenant, run_id, lock=True)
    if run.state == "cancelled":
        return run
    if run.state in {"completed", "partial", "failed"}:
        raise BackendError("terminal_run_cannot_cancel", 409)
    advance(run, "cancelled")
    run.finished_at = now()
    run.outcome_code = "cancelled_by_local_user"
    return run


def review_run(session, tenant, run_id, request: ReviewRequest, settings=None):
    run = run_for(session, tenant, run_id, lock=True)
    if run.state not in {"completed", "partial"} or run.result is None:
        raise BackendError("run_has_no_reviewable_purchase_order", 409)
    payload = ExtractionPayload.model_validate(run.result)
    events = session.scalars(select(ReviewEvent).where(ReviewEvent.tenant_id == tenant, ReviewEvent.run_id == run_id)
                             .order_by(*ReviewEvent.audit_order())).all()
    request_hash = fingerprint(request.model_dump(mode="json"))
    if request.action == "new_product":
        prior = next((event for event in events if event.action == "new_product" and
            event.new_value.get("decision_key") == request.decision_key), None)
        if prior:
            if prior.new_value.get("request_hash") != request_hash:
                raise BackendError("review_idempotency_payload_conflict", 409)
            return prior
    if run.review_state == "resolved":
        raise BackendError("resolved_review_is_immutable_create_new_run", 409)
    tier_by_row = {value["row_id"]: value["tier"] for value in review_suggestions(session, tenant, run)}
    old_value = None
    new_value = None
    if request.action == "resolve":
        from backend.review_summary import resolution_blockers
        from backend.coverage import page_coverage
        source = source_for(session, tenant, run.source_document_id)
        checks = page_coverage(payload, [serialize(event) for event in events], source)
        from backend.source_checks import grounding_projection
        grounding = grounding_projection(run, [serialize(event) for event in events], source)
        blockers = resolution_blockers(payload, [serialize(event) for event in events], tier_by_row, checks, grounding)
        if blockers:
            raise BackendError(blockers[0], 409)
        old_value, new_value = {"review_state": run.review_state}, {"review_state": "resolved"}
        run.review_state = "resolved"
    elif request.action == "confirm_unavailable_page_text":
        from backend.api_models import PageSourceEvidence
        from backend.source_checks import grounding_projection
        source = source_for(session, tenant, run.source_document_id)
        try:
            references = [PageSourceEvidence.model_validate(ref) for ref in request.evidence_reference]
        except Exception:
            raise BackendError("invalid_page_source_evidence", 422) from None
        if len(references) != 1:
            raise BackendError("confirm_one_page_per_event", 422)
        ref = references[0]
        if ref.source_sha256 != source.sha256:
            raise BackendError("review_source_hash_mismatch", 422)
        if ref.page_number > source.page_count:
            raise BackendError("page_outside_document", 422)
        read_source(settings.storage_directory, source.storage_reference, source.sha256)
        checks = grounding_projection(run, [serialize(e) for e in events], source)
        if not any(o["page_number"] == ref.page_number and o["status"] == "unavailable"
                   for c in checks for o in c["observations"]):
            raise BackendError("page_text_is_not_unavailable", 422)
        old_value = {"independent_text_status": "unavailable"}
        new_value = {**ref.model_dump(), "independent_text_status": "unavailable", "human_confirmed_source": True}
        run.review_state = "in_progress"
    elif request.action in {"acknowledge_page", "acknowledge_document"}:
        try:
            references = [EvidenceReference.model_validate(reference) for reference in request.evidence_reference]
        except Exception:
            raise BackendError("invalid_review_evidence_reference", 422) from None
        declared = {(page.page_number, region.region_reference) for page in payload.pages for region in page.regions}
        if not references or not all((ref.page_number, ref.region_reference) in declared for ref in references):
            raise BackendError("review_evidence_outside_document", 422)
        if request.action == "acknowledge_page":
            numbers = {ref.page_number for ref in references}
            if len(numbers) != 1:
                raise BackendError("acknowledge_one_page_per_event", 422)
            page = next(page for page in payload.pages if page.page_number in numbers)
            if page.state != "partial":
                raise BackendError("only_partial_pages_can_be_acknowledged", 422)
            old_value = {"page_state": page.state, "uncertainty": page.uncertainty}
            new_value = {"human_acknowledged_uncertainty": True}
        else:
            old_value = {"warnings": list(payload.warnings)}
            new_value = {"human_acknowledged_warnings": True}
        run.review_state = "in_progress"
    else:
        row = next((row for row in payload.rows if row.row_id == request.row_id), None)
        if row is None:
            raise BackendError("row_not_found", 404)
        try:
            references = [EvidenceReference.model_validate(reference) for reference in request.evidence_reference]
        except Exception:
            raise BackendError("invalid_review_evidence_reference", 422) from None
        row_references = {(ref.page_number, ref.region_reference) for ref in row.evidence}
        if request.action == "confirm_source_text":
            row_references.update((ref.page_number, ref.region_reference)
                                  for field in [row.description, *row.identifiers] for ref in field.evidence)
        if not references or not all((ref.page_number, ref.region_reference) in row_references for ref in references):
            raise BackendError("review_evidence_outside_row", 422)
        if row.row_role == "continuation" and request.action in {"approve", "no_match", "acknowledge", "propose_candidate"}:
            raise BackendError("continuation_is_grouped_source_evidence", 422)
        if payload.schema_version == "1.2" and row.row_role == "document_detail" and request.action in {"approve", "no_match", "acknowledge", "propose_candidate"}:
            raise BackendError("document_detail_does_not_require_product_review", 422)
        if request.action == "confirm_source_text":
            source = source_for(session, tenant, run.source_document_id)
            read_source(settings.storage_directory, source.storage_reference, source.sha256)
            check = next((c for c in (run.parses or {}).get("source_grounding", [])
                          if c["row_id"] == row.row_id and c["status"] == "unsupported"), None)
            if not check:
                raise BackendError("row_has_no_unsupported_source_text", 422)
            unsupported_refs = {(o["page_number"], o["region_reference"]) for o in check["observations"]
                                if o["status"] == "unsupported"}
            if not unsupported_refs.issubset({(r.page_number, r.region_reference) for r in references}):
                raise BackendError("source_review_requires_all_flagged_regions", 422)
            old_value = check
            new_value = {"source_sha256": source.sha256, "human_reviewed_unsupported_text": True,
                         "independent_text_status": "unsupported"}
        elif request.action in {"this_is_product", "new_product", *EXCLUSION_ACTIONS}:
            new_value = explicit_answer(session, tenant, run, row, request)
            if request.action == "new_product":
                new_value.update(decision_key=request.decision_key, request_hash=request_hash)
            old_value = {"original_row_kind": row.row_kind, "resolution": "unresolved"}
        elif request.action in {"approve", "no_match"}:
            if row.row_kind not in {"product", "unknown"} or row.row_role == "continuation":
                raise BackendError("non_product_row_cannot_match", 422)
            last_row_event = next((event for event in reversed(events) if event.row_id == row.row_id
                and event.action in BINDING_ACTIONS | EXCLUSION_ACTIONS), None)
            if tier_by_row.get(row.row_id) == "uncertain":
                if request.action == "no_match":
                    raise BackendError("uncertain_requires_three_way_decision", 422)
                if not last_row_event or last_row_event.action not in BINDING_ACTIONS or len(last_row_event.new_value.get("candidates", [])) != 1:
                    raise BackendError("uncertain_requires_explicit_product_binding", 422)
                if str(request.selected_candidate_id) != last_row_event.new_value["candidates"][0]["candidate_id"]:
                    raise BackendError("selected_candidate_outside_current_binding", 422)
            if request.action == "approve":
                suggestion = session.scalar(select(Suggestion).where(Suggestion.tenant_id == tenant, Suggestion.run_id == run_id,
                                                                      Suggestion.row_id == row.row_id))
                candidate = next((value for value in suggestion.candidates if value["candidate_id"] == str(request.selected_candidate_id)), None) if suggestion else None
                if candidate is None:
                    candidate = next((value for event in reversed(events)
                        if event.row_id == row.row_id and event.action in BINDING_ACTIONS
                        for value in event.new_value["candidates"]
                        if value["candidate_id"] == str(request.selected_candidate_id)), None)
                if candidate is None:
                    raise BackendError("selected_candidate_outside_snapshot", 422)
                product = session.scalar(select(CatalogProduct).where(
                    CatalogProduct.tenant_id == tenant, CatalogProduct.id == request.selected_candidate_id,
                    CatalogProduct.active.is_(True)))
                if product is None or (run.catalog_pool_id is not None and not validate_pool_candidate(
                        session, tenant, run.catalog_pool_id, product.vendor_id, product.id)) or (
                        run.catalog_pool_id is None and (product.vendor_id != run.vendor_id or product.review_pool_id is not None)):
                    raise BackendError("selected_candidate_outside_run_pool", 422)
                new_value = {"resolution": "approved", "candidate": candidate}
            else:
                new_value = {"resolution": "no_match"}
            previous = next((event for event in reversed(events) if event.row_id == row.row_id and event.action in {"approve", "no_match"}), None)
            old_value = previous.new_value if previous else {"resolution": "unresolved"}
        elif request.action == "propose_candidate":
            if row.row_kind not in {"product", "unknown"} or row.row_role == "continuation":
                raise BackendError("non_product_row_cannot_match", 422)
            products = session.scalars(select(CatalogProduct).where(
                CatalogProduct.tenant_id == tenant, CatalogProduct.id.in_(request.candidate_ids),
                CatalogProduct.active.is_(True))).all()
            if run.catalog_pool_id is not None:
                products = [product for product in products if validate_pool_candidate(
                    session, tenant, run.catalog_pool_id, product.vendor_id, product.id)]
            else:
                products = [product for product in products if product.vendor_id == run.vendor_id and product.review_pool_id is None]
            if len(products) != len(request.candidate_ids):
                raise BackendError("proposed_candidate_outside_catalog", 422)
            by_id = {product.id: product for product in products}
            proposed = []
            for id_ in request.candidate_ids:
                product = by_id[id_]
                candidate = {"candidate_id": str(product.id), "sku": product.sku,
                    "description": product.description, "method": "human_catalog_search", "origin": product.origin}
                if run.catalog_pool_id is not None:
                    source = session.scalar(select(CatalogSourceProduct).join(CatalogPoolMember,
                        (CatalogPoolMember.tenant_id == CatalogSourceProduct.tenant_id) &
                        (CatalogPoolMember.vendor_id == CatalogSourceProduct.vendor_id) &
                        (CatalogPoolMember.namespace_id == CatalogSourceProduct.namespace_id)).where(
                            CatalogSourceProduct.tenant_id == tenant, CatalogSourceProduct.vendor_id == product.vendor_id,
                            CatalogSourceProduct.product_id == product.id, CatalogPoolMember.pool_id == run.catalog_pool_id))
                    candidate.update({"origin_vendor_id": str(product.vendor_id), "namespace_id": str(source.namespace_id) if source else None})
                proposed.append(candidate)
            new_value = {"candidates": proposed, "decision": "this_is_product" if len(proposed) == 1 else "ambiguous", "resolution": "needs_approval"}
        elif request.action == "acknowledge":
            if row.row_kind == "product":
                raise BackendError("product_requires_approve_or_no_match", 422)
            if (payload.schema_version == "1.2" and row.row_role == "document_detail"):
                raise BackendError("document_detail_does_not_require_product_review", 422)
            new_value = {"acknowledged_row_kind": row.row_kind}
        elif request.action == "correct":
            if request.field_name.startswith("identifier."):
                if request.identifier_index >= len(row.identifiers):
                    raise BackendError("identifier_index_outside_row", 422)
                identifier = row.identifiers[request.identifier_index]
                original_value = getattr(identifier, request.field_name.split(".", 1)[1])
            else:
                original_value = getattr(row, request.field_name).raw_value
            prior = next((event for event in reversed(events) if event.action == "correct" and event.row_id == row.row_id
                          and event.new_value.get("field_name") == request.field_name
                          and event.new_value.get("identifier_index") == request.identifier_index), None)
            old_value = prior.new_value if prior else {"field_name": request.field_name, "value": original_value}
            new_value = {"field_name": request.field_name, "value": request.new_value}
            if request.identifier_index is not None:
                old_value = {**old_value, "identifier_index": request.identifier_index}
                new_value["identifier_index"] = request.identifier_index
        run.review_state = "in_progress"
    event = ReviewEvent(tenant_id=tenant, run_id=run_id, row_id=request.row_id, action=request.action,
                        reviewer=request.reviewer, reason=request.reason, evidence_reference=request.evidence_reference,
                        old_value=old_value, new_value=new_value, selected_candidate_id=request.selected_candidate_id,
                        created_at=now(), event_sequence=max((e.event_sequence or 0 for e in events), default=0) + 1)
    session.add(event)
    session.flush()
    return event


def record_page_count(session, tenant, run_id, request: PageCountRequest, settings):
    from backend.coverage import COUNT_ACTION, COUNT_METHOD, page_coverage, synchronize_coverage_state
    run = run_for(session, tenant, run_id, lock=True)
    if run.state not in {"completed", "partial"} or not run.result:
        raise BackendError("run_has_no_reviewable_purchase_order", 409)
    if run.review_state == "resolved":
        raise BackendError("resolved_review_is_immutable_create_new_run", 409)
    payload = ExtractionPayload.model_validate(run.result)
    if payload.document_type != "purchase_order":
        raise BackendError("run_has_no_reviewable_purchase_order", 409)
    source = source_for(session, tenant, run.source_document_id)
    if request.source_sha256 != source.sha256:
        raise BackendError("review_source_hash_mismatch", 422)
    if request.page_number > source.page_count:
        raise BackendError("page_outside_document", 422)
    # A saved hash is insufficient if the actual immutable file has been damaged.
    read_source(settings.storage_directory, source.storage_reference, source.sha256)
    events = session.scalars(select(ReviewEvent).where(ReviewEvent.tenant_id == tenant,
        ReviewEvent.run_id == run_id).order_by(*ReviewEvent.audit_order())).all()
    history = [event for event in events if event.action == COUNT_ACTION
               and event.new_value["page_number"] == request.page_number]
    prior = history[-1] if history else None
    if any(event.new_value["source_discrepancy"] for event in history):
        raise BackendError("source_discrepancy_requires_new_run", 409)
    if prior:
        if request.corrects_event_id != prior.id:
            raise BackendError("count_correction_must_reference_latest_event", 409)
    elif request.corrects_event_id:
        raise BackendError("count_correction_event_outside_page_or_run", 422)
    evidence = {"scope": "page", "page_number": request.page_number, "source_sha256": source.sha256}
    new_value = {**evidence, "method": COUNT_METHOD, "product_count": request.product_count,
                 "source_discrepancy": request.source_discrepancy,
                 "corrects_event_id": str(prior.id) if prior else None,
                 "correction_kind": request.correction_kind}
    provider_count = page_coverage(payload, [], source)[request.page_number - 1]["provider_product_count"]
    new_value.update(provider_product_count=provider_count,
                     status="mismatch" if request.source_discrepancy or provider_count != request.product_count else "matched")
    event = ReviewEvent(tenant_id=tenant, run_id=run_id, row_id=None, action=COUNT_ACTION,
        reviewer=request.reviewer, reason=request.reason, evidence_reference=[evidence],
        old_value=prior.new_value if prior else None, new_value=new_value, created_at=now(),
        event_sequence=max((event.event_sequence or 0 for event in events), default=0) + 1)
    session.add(event)
    session.flush()
    synchronize_coverage_state(run, page_coverage(payload, [serialize(e) for e in [*events, event]], source))
    run.review_state = "in_progress"
    return event
