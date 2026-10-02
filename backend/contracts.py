"""ProductDocument extraction payload 1.1; Gate A's 1.0 envelope is unchanged.

Provider observations are immutable. Deterministic parses, catalog suggestions
and human corrections are separate records and never mutate this payload.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from gate_a.contracts import (
    EvidenceReference, FieldObservation as GateAFieldObservation,
    IdentifierObservation as GateAIdentifierObservation, ObservationState, ParsedDecimal, ParseStatus, RowKind,
)

SCHEMA_VERSION = "1.1"


class Immutable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class FieldObservation(GateAFieldObservation):
    """The same five Gate A states, now preserving a printed field label."""
    source_label: StrictStr | None
    evidence: tuple[EvidenceReference, ...]
    alternative_readings: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def label_is_literal_or_null(self) -> FieldObservation:
        if self.source_label is not None and not self.source_label.strip():
            raise ValueError("source_label must contain text or be null")
        return self


class IdentifierObservation(GateAIdentifierObservation):
    """Gate A identifier provenance with explicit collection keys in v1.1."""
    evidence: tuple[EvidenceReference, ...]
    alternative_readings: tuple[StrictStr, ...]


class BoundingBox(Immutable):
    """Normalized top-left coordinates relative to the whole source page."""
    x0: float = Field(ge=0, le=1, allow_inf_nan=False)
    y0: float = Field(ge=0, le=1, allow_inf_nan=False)
    x1: float = Field(ge=0, le=1, allow_inf_nan=False)
    y1: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> BoundingBox:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("region must have positive area")
        return self


class Region(Immutable):
    region_reference: StrictStr
    bbox: BoundingBox

    @model_validator(mode="after")
    def nonblank(self) -> Region:
        if not self.region_reference.strip():
            raise ValueError("region_reference must contain text")
        return self


class PageObservation(Immutable):
    page_number: StrictInt = Field(ge=1)
    state: Literal["complete", "partial", "failed"]
    regions: tuple[Region, ...]
    uncertainty: StrictStr | None

    @model_validator(mode="after")
    def page_semantics(self) -> PageObservation:
        refs = [region.region_reference for region in self.regions]
        if len(refs) != len(set(refs)):
            raise ValueError("region references must be unique within a page")
        if self.uncertainty is not None and not self.uncertainty.strip():
            raise ValueError("uncertainty must contain text or be null")
        if self.state in ("partial", "failed") and self.uncertainty is None:
            raise ValueError("partial/failed pages require an uncertainty reason")
        if self.state == "complete" and self.uncertainty is not None:
            raise ValueError("a page with unresolved uncertainty must be partial")
        return self


class ExtractedRow(Immutable):
    row_id: StrictStr = Field(max_length=120)
    row_kind: RowKind
    evidence: tuple[EvidenceReference, ...]
    identifiers: tuple[IdentifierObservation, ...]
    description: FieldObservation
    quantity: FieldObservation
    unit: FieldObservation
    unit_price: FieldObservation
    line_total: FieldObservation
    uncertainty: StrictStr | None

    @model_validator(mode="after")
    def row_semantics(self) -> ExtractedRow:
        if not self.row_id.strip() or not self.evidence:
            raise ValueError("rows require a nonblank row_id and source evidence")
        if self.uncertainty is not None and not self.uncertainty.strip():
            raise ValueError("uncertainty must contain text or be null")
        if self.row_kind == RowKind.UNKNOWN and self.uncertainty is None:
            raise ValueError("unknown row kinds require an uncertainty reason")
        return self


class ExtractionPayload(Immutable):
    contract_name: Literal["ProductDocument"]
    schema_version: Literal["1.1"]
    document_type: Literal["purchase_order", "unsupported", "unknown"]
    document_type_reason: StrictStr | None
    document_number: FieldObservation
    vendor_name: FieldObservation
    currency: FieldObservation
    pages: tuple[PageObservation, ...]
    rows: tuple[ExtractedRow, ...]
    warnings: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def graph_semantics(self) -> ExtractionPayload:
        if not self.pages:
            raise ValueError("every source page must have an explicit page observation")
        if self.document_type_reason is not None and not self.document_type_reason.strip():
            raise ValueError("document_type_reason must contain text or be null")
        if self.document_type != "purchase_order" and self.document_type_reason is None:
            raise ValueError("unsupported/unknown types require a classification reason")
        if any(not warning.strip() for warning in self.warnings):
            raise ValueError("warnings must contain text")
        page_numbers = [page.page_number for page in self.pages]
        if sorted(page_numbers) != list(range(1, len(self.pages) + 1)):
            raise ValueError("pages must cover each one-based source page exactly once")
        row_ids = [row.row_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("row_id must be unique within the document")
        regions = {(page.page_number, region.region_reference): page.state
                   for page in self.pages for region in page.regions}
        observations = [self.document_number, self.vendor_name, self.currency]
        for row in self.rows:
            self._check_refs(row.evidence, regions)
            observations.extend((*row.identifiers, row.description, row.quantity,
                                 row.unit, row.unit_price, row.line_total))
        for observation in observations:
            self._check_refs(observation.evidence, regions)
            if observation.state in (ObservationState.OBSERVED, ObservationState.UNCERTAIN):
                if any(regions[(ref.page_number, ref.region_reference)] == "failed"
                       for ref in observation.evidence):
                    raise ValueError("failed pages cannot support readable observations")
        return self

    @staticmethod
    def _check_refs(refs: tuple[EvidenceReference, ...], regions: dict) -> None:
        for ref in refs:
            if (ref.page_number, ref.region_reference) not in regions:
                raise ValueError("evidence references must identify declared source regions")

    @property
    def partial(self) -> bool:
        """Uncertainty remains explicit even after a syntactically valid response."""
        if any(page.state != "complete" for page in self.pages) or self.warnings:
            return True
        fields = [self.document_number, self.vendor_name, self.currency]
        for row in self.rows:
            if row.row_kind == RowKind.UNKNOWN or row.uncertainty is not None:
                return True
            fields.extend((*row.identifiers, row.description, row.quantity, row.unit,
                           row.unit_price, row.line_total))
        return any(field.state in (ObservationState.UNCERTAIN, ObservationState.UNREADABLE)
                   for field in fields)


def validate_payload(payload: ExtractionPayload | dict, page_count: int) -> ExtractionPayload:
    """Validate shape, evidence graph, then source-bound page completeness."""
    if type(page_count) is not int or page_count < 1:
        raise ValueError("source page_count must be a positive integer")
    # A third-party provider may use model_construct/model_copy (which bypass
    # validators). Validate every boundary again, including nested observations.
    raw = payload.model_dump(mode="python", warnings=False) if isinstance(payload, ExtractionPayload) else payload
    value = ExtractionPayload.model_validate(raw)
    if len(value.pages) != page_count:
        raise ValueError("payload page coverage does not match the immutable source")
    return value


_UNAMBIGUOUS_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?\Z")
PARSE_METHOD = "plain-decimal-no-grouping-v1"


def parse_decimal(observation: GateAFieldObservation) -> ParsedDecimal:
    """Conservatively parse plain decimals; commas/grouping remain unresolved.

    Dot with three or more fractional digits can be a locale grouping separator,
    so this v1 parser abstains. Units/currency symbols are never guessed away.
    """
    if observation.state in (ObservationState.NOT_PRESENT, ObservationState.NOT_APPLICABLE):
        return ParsedDecimal(status=ParseStatus.NOT_ATTEMPTED, value=None, method=None)
    if (observation.state != ObservationState.OBSERVED or observation.raw_value is None
            or _UNAMBIGUOUS_DECIMAL.fullmatch(observation.raw_value.strip()) is None):
        return ParsedDecimal(status=ParseStatus.UNRESOLVED, value=None, method=PARSE_METHOD)
    value = format(Decimal(observation.raw_value.strip()), "f")
    return ParsedDecimal(status=ParseStatus.PARSED, value=value, method=PARSE_METHOD)


def parsed_payload(payload: ExtractionPayload) -> dict:
    """Separate deterministic derivations; raw evidence is retained unchanged."""
    return {"schema_version": SCHEMA_VERSION, "parse_version": PARSE_METHOD,
            "rows": [{"row_id": row.row_id,
                      **{name: parse_decimal(getattr(row, name)).model_dump(mode="json")
                         for name in ("quantity", "unit_price", "line_total")}}
                     for row in payload.rows]}


def strict_schema() -> dict:
    """Responses strict subset: required nullable keys, closed objects, no defaults."""
    schema = deepcopy(ExtractionPayload.model_json_schema())

    def clean(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for child in node.values():
                clean(child)
        elif isinstance(node, list):
            for child in node:
                clean(child)

    clean(schema)
    return schema
