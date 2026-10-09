"""Strict request boundaries, separate from immutable model observations."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator
from backend.catalog import ProductInput
from backend.text_guard import reject_nul


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def no_nul_text(self):
        # Every persisted client string (and nested JSON string) is checked once, here.
        for name in type(self).model_fields:
            reject_nul(getattr(self, name))
        return self


class NameRequest(RequestModel):
    name: StrictStr = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.name.strip():
            raise ValueError("name required")
        return self


class ExternalAuthorization(RequestModel):
    authorized: Literal[True]
    source_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    authorized_by: StrictStr = Field(min_length=1, max_length=120)
    policy_reference: StrictStr = Field(min_length=1, max_length=500)
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("authorized", mode="before")
    @classmethod
    def affirmative_boolean(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("affirmative JSON boolean true is required")
        return value

    @model_validator(mode="after")
    def nonblank(self):
        if not all(getattr(self, name).strip() for name in ("authorized_by", "policy_reference", "reason")):
            raise ValueError("named authorization, policy and reason required")
        return self


class RunRequest(RequestModel):
    provider: Literal["synthetic", "openai"] = "openai"
    fixture_name: StrictStr | None = Field(default=None, max_length=80)
    external_authorization: ExternalAuthorization | None = None

    @model_validator(mode="after")
    def fixture_only_synthetic(self):
        if self.provider != "synthetic" and self.fixture_name is not None:
            raise ValueError("fixture_name only applies to synthetic processing")
        return self


class ReviewRequest(RequestModel):
    action: Literal["approve", "no_match", "acknowledge", "correct", "resolve", "acknowledge_page", "acknowledge_document", "propose_candidate", "this_is_product", "new_product", "not_a_product"] | Annotated[Literal["not_product"], Field(json_schema_extra={"deprecated": True})] = Field(
        description="Use not_a_product for exclusion. not_product is a deprecated legacy alias retained for existing clients and audit events.")
    row_id: StrictStr | None = Field(default=None, max_length=120)
    reviewer: StrictStr = Field(min_length=1, max_length=120)
    reason: StrictStr = Field(min_length=1, max_length=500)
    evidence_reference: list[dict] = Field(default_factory=list, max_length=50)
    selected_candidate_id: UUID | None = None
    candidate_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=5)
    field_name: Literal["description", "quantity", "unit", "unit_price", "line_total",
                        "identifier.raw_value", "identifier.source_label", "identifier.source_role"] | None = None
    identifier_index: int | None = Field(default=None, ge=0, le=100)
    new_value: StrictStr | None = Field(default=None, max_length=2000)
    catalog_id: UUID | None = None
    product: ProductInput | None = None
    vendor_id: UUID | None = None
    decision_key: StrictStr | None = Field(default=None, min_length=16, max_length=200)

    @model_validator(mode="after")
    def named_event(self):
        if not self.reviewer.strip() or not self.reason.strip():
            raise ValueError("reviewer and reason required")
        if self.action == "resolve":
            if self.row_id or self.selected_candidate_id or self.field_name or self.evidence_reference:
                raise ValueError("resolve applies to the complete run")
        elif self.action in {"acknowledge_page", "acknowledge_document"}:
            if self.row_id is not None or not self.evidence_reference:
                raise ValueError("page/document acknowledgment requires source evidence and no row")
        elif not self.row_id or not self.evidence_reference:
            raise ValueError("row and source evidence required")
        if self.action == "approve":
            if self.selected_candidate_id is None:
                raise ValueError("approve requires an in-set candidate")
        elif self.selected_candidate_id is not None:
            raise ValueError("only approve can select a candidate")
        if self.action == "propose_candidate":
            if not self.candidate_ids or len(set(self.candidate_ids)) != len(self.candidate_ids):
                raise ValueError("proposal requires one to five distinct scoped candidates")
        elif self.candidate_ids is not None:
            raise ValueError("candidate ids only apply to a proposal")
        if self.action == "correct":
            if self.field_name is None:
                raise ValueError("correct requires a field name")
            if self.field_name.startswith("identifier.") != (self.identifier_index is not None):
                raise ValueError("identifier correction requires an index; other fields cannot use an index")
        elif self.field_name is not None or self.new_value is not None or self.identifier_index is not None:
            raise ValueError("correction values only apply to correct")
        if (self.action == "this_is_product") != (self.catalog_id is not None):
            raise ValueError("this_is_product requires a catalog id; other actions cannot supply it")
        if self.action == "new_product":
            if self.product is None or not self.decision_key or not self.decision_key.strip():
                raise ValueError("new_product requires reviewed catalog fields and a stable decision key")
        elif self.product is not None or self.vendor_id is not None or self.decision_key is not None:
            raise ValueError("new product fields only apply to new_product")
        return self
