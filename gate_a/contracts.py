"""Gate A's versioned envelope and evidence-preserving contract primitives.

This is not a finalized extraction payload, an extractor, or a workflow engine.
The envelope links an existing source and run; it has no document content,
catalog decision, provider request, or human correction fields. Later gates must
specify the extraction payload and a versioned legacy adapter separately.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class _ImmutableContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ObservationState(str, Enum):
    OBSERVED = "observed"
    UNCERTAIN = "uncertain"
    UNREADABLE = "unreadable"
    NOT_PRESENT = "not_present"
    NOT_APPLICABLE = "not_applicable"


class RunState(str, Enum):
    CREATED = "created"
    VALIDATING = "validating"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewState(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class RowKind(str, Enum):
    """Vocabulary only; Gate A does not define or extract document rows."""

    PRODUCT = "product"
    CHARGE = "charge"
    TAX = "tax"
    SUBTOTAL = "subtotal"
    TOTAL = "total"
    NOTE = "note"
    UNKNOWN = "unknown"


class EvidenceReference(_ImmutableContract):
    """One-based source page and an opaque region reference, not source text.

    The region geometry/coordinate system belongs to the later extraction
    contract. No file path or content is resolved by this primitive.
    """

    page_number: StrictInt = Field(ge=1)
    region_reference: StrictStr

    @model_validator(mode="after")
    def require_region_reference(self) -> EvidenceReference:
        if not self.region_reference.strip():
            raise ValueError("region_reference must identify a source region")
        return self


class FieldObservation(_ImmutableContract):
    """Immutable literal reading, with explicit absence and uncertainty.

    Raw values and alternatives are strict strings and are never stripped,
    normalized, parsed, or rewritten. Each alternative refers to the same
    evidence as the best reading. A later correction is a separate audit event.
    """

    state: ObservationState
    raw_value: StrictStr | None
    evidence: tuple[EvidenceReference, ...] = ()
    alternative_readings: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def validate_observation_state(self) -> FieldObservation:
        readings = (() if self.raw_value is None else (self.raw_value,)) + self.alternative_readings
        if any(not reading.strip() for reading in readings):
            raise ValueError("literal readings must contain text; use an explicit absent/unreadable state")

        if self.state in (ObservationState.OBSERVED, ObservationState.UNCERTAIN, ObservationState.UNREADABLE):
            if not self.evidence:
                raise ValueError("present observations require page/region evidence")

        if self.state == ObservationState.OBSERVED:
            if self.raw_value is None:
                raise ValueError("observed requires a literal raw_value")
            if self.alternative_readings:
                raise ValueError("alternative readings require the uncertain state")
        elif self.state == ObservationState.UNCERTAIN:
            if not readings:
                raise ValueError("uncertain requires a best reading or an alternative reading")
        else:
            if self.raw_value is not None or self.alternative_readings:
                raise ValueError("unreadable/not_present/not_applicable cannot invent readings")
        return self


class IdentifierObservation(FieldObservation):
    """A source identifier; neither field denotes a canonical catalog ID.

    Explicit null means that a printed label or possible role is unavailable.
    Providing the fields explicitly prevents silently dropping this provenance.
    """

    source_label: StrictStr | None
    source_role: StrictStr | None

    @model_validator(mode="after")
    def validate_identifier_provenance(self) -> IdentifierObservation:
        for value in (self.source_label, self.source_role):
            if value is not None and not value.strip():
                raise ValueError("identifier source labels/roles must contain text or be null")
        return self


class ParseStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    PARSED = "parsed"
    UNRESOLVED = "unresolved"


_PLAIN_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")


class ParsedDecimal(_ImmutableContract):
    """A separate deterministic decimal result; this does not perform parsing.

    A plain finite decimal string avoids binary floats, NaN, locale punctuation,
    and exponent conventions. An ambiguous or unsupported parse remains null
    with status `unresolved` and the attempted method retained.
    """

    status: ParseStatus
    value: StrictStr | None
    method: StrictStr | None

    @model_validator(mode="after")
    def validate_parse_state(self) -> ParsedDecimal:
        if self.status == ParseStatus.NOT_ATTEMPTED:
            if self.value is not None or self.method is not None:
                raise ValueError("not_attempted must have null value and method")
        else:
            if self.method is None or not self.method.strip():
                raise ValueError("attempted parses require their method")
            if self.status == ParseStatus.PARSED:
                if self.value is None or _PLAIN_DECIMAL.fullmatch(self.value) is None:
                    raise ValueError("parsed requires a plain finite decimal string")
            elif self.value is not None:
                raise ValueError("unresolved must have a null parsed value")
        return self


class ProductDocumentV1(_ImmutableContract):
    """Gate A envelope only, with separate processing and human-review states.

    UUIDs are references, not a claim that a document has been uploaded or
    extracted. Tenant/source/run referential checks belong to persistence.
    No provider payload or catalog resolution is accepted in this envelope.
    """

    contract_name: Literal["ProductDocument"] = "ProductDocument"
    schema_version: Literal["1.0"]
    tenant_id: UUID
    source_document_id: UUID
    run_id: UUID
    document_type: Literal["purchase_order"]
    run_state: RunState = RunState.CREATED
    review_state: ReviewState = ReviewState.NOT_STARTED


_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset((RunState.VALIDATING, RunState.FAILED, RunState.CANCELLED)),
    RunState.VALIDATING: frozenset((RunState.PROCESSING, RunState.FAILED, RunState.CANCELLED)),
    RunState.PROCESSING: frozenset((RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED, RunState.CANCELLED)),
    RunState.COMPLETED: frozenset(),
    RunState.PARTIAL: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}

_REVIEW_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.NOT_STARTED: frozenset((ReviewState.IN_PROGRESS,)),
    ReviewState.IN_PROGRESS: frozenset((ReviewState.RESOLVED,)),
    ReviewState.RESOLVED: frozenset(),
}


def validate_run_transition(current: RunState | str, target: RunState | str) -> None:
    """Validate one forward edge without changing a run or starting work.

    Every terminal state has no outgoing edge, including a same-state edge.
    Reprocessing requires a distinct run reference, not a terminal escape.
    """

    current_state = RunState(current)
    target_state = RunState(target)
    if target_state not in _RUN_TRANSITIONS[current_state]:
        raise ValueError(f"invalid run transition: {current_state.value} -> {target_state.value}")


def validate_review_transition(current: ReviewState | str, target: ReviewState | str) -> None:
    """Validate the review vocabulary's forward edge; no review action occurs."""

    current_state = ReviewState(current)
    target_state = ReviewState(target)
    if target_state not in _REVIEW_TRANSITIONS[current_state]:
        raise ValueError(f"invalid review transition: {current_state.value} -> {target_state.value}")
