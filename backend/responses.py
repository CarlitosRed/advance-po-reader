"""Typed public responses for later website clients; no provider secret fields."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from backend.contracts import ExtractionPayload
from gate_a.contracts import EvidenceReference


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(ResponseModel):
    error: str
    issues: list[dict] | None = None


class TenantResponse(ResponseModel):
    id: UUID
    name: str
    created_at: datetime


class VendorResponse(TenantResponse):
    tenant_id: UUID


class SourceResponse(ResponseModel):
    id: UUID
    tenant_id: UUID
    vendor_id: UUID
    catalog_pool_id: UUID | None = None
    sha256: str
    byte_size: int
    media_type: Literal["application/pdf", "image/png", "image/jpeg"]
    page_count: int
    width: int | None
    height: int | None
    storage_reference: str
    created_at: datetime


class RunResponse(ResponseModel):
    id: UUID
    source_document_id: UUID | None = None
    vendor_id: UUID | None = None
    catalog_pool_id: UUID | None = None
    provider: Literal["openai", "synthetic"] | None = None
    state: Literal["created", "validating", "processing", "completed", "partial", "failed", "cancelled"]
    review_state: Literal["not_started", "in_progress", "resolved"]
    outcome_code: str | None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class RunsResponse(ResponseModel):
    runs: list[RunResponse]


class AttemptResponse(ResponseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    state: str
    model: str
    actual_model: str | None
    prompt_version: str
    schema_version: str
    request_id: str | None
    response_id: str | None
    usage: dict
    latency_ms: int
    error_code: str | None
    synthetic: bool
    created_at: datetime
    finished_at: datetime | None


class ResultResponse(ResponseModel):
    extraction: ExtractionPayload | None
    parses: dict | None
    attempts: list[AttemptResponse]


class CandidateResponse(ResponseModel):
    candidate_id: UUID
    sku: str
    description: str
    method: str
    score: str | None = None
    origin_vendor_id: UUID | None = None
    namespace_id: UUID | None = None
    origin: Literal["import", "review"] = "import"


class SuggestionResponse(ResponseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    row_id: str
    candidates: list[CandidateResponse]
    method: str
    retrieval_version: str
    evidence: list[dict]
    outcome: Literal["suggested", "ambiguous", "no_match"]
    reason: str
    suggested_candidate_id: UUID | None
    tier: Literal["certain", "probable", "uncertain"]
    tier_reason: str
    approval_status: Literal["needs_approval"]
    created_at: datetime


class SuggestionsResponse(ResponseModel):
    suggestions: list[SuggestionResponse]


class ReviewResponse(ResponseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    row_id: str | None
    action: str
    reviewer: str
    reason: str
    evidence_reference: list[EvidenceReference]
    old_value: Any | None
    new_value: Any | None
    selected_candidate_id: UUID | None
    created_at: datetime
    event_sequence: int | None


class ReviewsResponse(ResponseModel):
    events: list[ReviewResponse]


class AliasResponse(ResponseModel):
    value: str
    source_role: str


class ProductResponse(ResponseModel):
    id: UUID
    tenant_id: UUID
    vendor_id: UUID
    sku: str
    description: str
    normalized_sku: str
    active: bool
    origin: Literal["import", "review"]
    review_pool_id: UUID | None
    aliases: list[AliasResponse]
    created_at: datetime


class CatalogResponse(ResponseModel):
    products: list[ProductResponse]
    limit: int
    offset: int
    next_offset: int | None


class ImportedResponse(ResponseModel):
    products: list[CandidateResponse]


class RunReadinessResponse(ResponseModel):
    run_id: UUID
    vendor_id: UUID
    provider: Literal["openai", "synthetic"]
    source_sha256: str
    source_authorized: bool
    provider_configured: bool
    attempt_count: int
    can_process: bool
    blockers: list[str]


class ApprovedProductResponse(ResponseModel):
    row_id: str
    item_group_id: str
    description: str | None
    continuation_descriptions: list[dict[str, Any]]
    candidate: CandidateResponse
    quantity: str | None
    unit: str | None
    original_quantity: str | None
    original_unit: str | None
    reviewer: str
    reason: str
    evidence: list[EvidenceReference]


class ExcludedRowResponse(ResponseModel):
    row_id: str
    row_kind: str
    decision: str


class ReviewSummaryResponse(ResponseModel):
    run_id: UUID
    state: str
    review_state: str
    summary_policy_version: str
    approved_products: list[ApprovedProductResponse]
    pending_row_ids: list[str]
    excluded_rows: list[ExcludedRowResponse]
    document_details: list[dict[str, Any]]
    review_event_count: int
    blockers: list[str]
    can_finish_review: bool
    source_observations_unchanged: bool
