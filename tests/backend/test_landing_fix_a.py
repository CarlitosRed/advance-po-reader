"""Offline regression checks for the PR #33 round-1 backend findings (no database needed)."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
import pymupdf
import pytest

from backend.api_models import ExternalAuthorization, NameRequest, ReviewRequest, RunRequest
from backend.app import create_app
from backend.catalog import AliasInput, ProductInput
from backend.config import ROOT, Settings
from backend.contracts import validate_payload
from backend.providers import SyntheticProvider
from backend.synthetic import KINDS, fixture_payload, generate_fixture

TOKEN = "landing-fix-a-token-long-enough"
CONTRACTS = ROOT / "contracts"


def offline_app():
    settings = Settings(_env_file=None, local_api_token=SecretStr(TOKEN),
                        storage_directory=ROOT / "data" / "landing-fix-a" / "offline")
    return create_app(settings)


def client_for(app):
    return TestClient(app, base_url="http://127.0.0.1:8012", headers={"X-Local-Token": TOKEN})


# R08 -----------------------------------------------------------------------

def test_r08_continuation_validates_when_pages_arrive_out_of_order():
    value = fixture_payload("continuation").model_dump(mode="json")
    page_one = value["pages"][0]
    page_two = {"page_number": 2, "state": "complete", "regions": [], "uncertainty": None}
    in_order = {**value, "pages": [page_one, page_two]}
    reversed_order = {**value, "pages": [page_two, page_one]}
    assert validate_payload(in_order, 2).rows == validate_payload(reversed_order, 2).rows


# R09 -----------------------------------------------------------------------

def parameter_counts(schema):
    counts = {}
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            names = [item["name"] for item in operation.get("parameters", [])]
            for name in set(names):
                counts[(path, method, name)] = names.count(name)
    return counts


def test_r09_repeated_openapi_reads_never_duplicate_parameters():
    app = offline_app()
    first = json.loads(json.dumps(app.openapi()))
    with client_for(app) as client:
        for _ in range(3):
            assert client.get("/openapi.json").status_code == 200
    again = app.openapi()
    assert again == first
    assert max(parameter_counts(again).values()) == 1
    csrf = [key for key in parameter_counts(again) if key[2] == "X-Website-CSRF"]
    assert len(csrf) >= 8  # every mutating operation documents it exactly once


# R10 + S01 -------------------------------------------------------------------

@pytest.mark.parametrize("version,artifact", [
    ("v1.1", "product-document-extraction-1.1.json"),
    ("v1.2", "product-document-extraction-1.2.json"),
])
def test_r10_versioned_schema_endpoint_serves_the_committed_contract(version, artifact):
    with client_for(offline_app()) as client:
        served = client.get(f"/contracts/product-document/{version}/schema").json()
        provider = client.get(f"/contracts/product-document/{version}/provider-schema").json()
    assert served == json.loads((CONTRACTS / artifact).read_text(encoding="utf-8"))
    if version == "v1.2":
        assert provider == json.loads((CONTRACTS / "product-document-extraction-1.2-provider.json").read_text(encoding="utf-8"))
    if version == "v1.1":
        assert served["properties"]["schema_version"]["enum"] == ["1.1"]


def test_s01_committed_openapi_matches_the_runtime_schema():
    committed = json.loads((CONTRACTS / "local-backend-openapi.json").read_text(encoding="utf-8"))
    assert offline_app().openapi() == committed


# R11 -----------------------------------------------------------------------

NUL = "bad\x00text"


@pytest.mark.parametrize("build", [
    lambda: NameRequest(name=NUL),
    lambda: ExternalAuthorization(authorized=True, source_sha256="a" * 64, authorized_by=NUL,
                                  policy_reference="policy", reason="reason"),
    lambda: ExternalAuthorization(authorized=True, source_sha256="a" * 64, authorized_by="who",
                                  policy_reference=NUL, reason="reason"),
    lambda: ExternalAuthorization(authorized=True, source_sha256="a" * 64, authorized_by="who",
                                  policy_reference="policy", reason=NUL),
    lambda: RunRequest(provider="synthetic", fixture_name=NUL),
    lambda: ReviewRequest(action="acknowledge", row_id="r", reviewer=NUL, reason="why",
                          evidence_reference=[{"page_number": 1, "region_reference": "r"}]),
    lambda: ReviewRequest(action="acknowledge", row_id="r", reviewer="who", reason=NUL,
                          evidence_reference=[{"page_number": 1, "region_reference": "r"}]),
    lambda: ReviewRequest(action="acknowledge", row_id=NUL, reviewer="who", reason="why",
                          evidence_reference=[{"page_number": 1, "region_reference": "r"}]),
    lambda: ReviewRequest(action="acknowledge", row_id="r", reviewer="who", reason="why",
                          evidence_reference=[{"page_number": 1, "region_reference": NUL}]),
    lambda: ReviewRequest(action="correct", row_id="r", reviewer="who", reason="why", field_name="description",
                          new_value=NUL, evidence_reference=[{"page_number": 1, "region_reference": "r"}]),
    lambda: ReviewRequest(action="new_product", row_id="r", reviewer="who", reason="why",
                          decision_key="k" * 16 + NUL, product=ProductInput(sku="S", description="D"),
                          evidence_reference=[{"page_number": 1, "region_reference": "r"}]),
    lambda: ProductInput(sku=NUL, description="D"),
    lambda: ProductInput(sku="S", description=NUL),
    lambda: AliasInput(value=NUL, source_role="sku"),
    lambda: AliasInput(value="v", source_role=NUL),
])
def test_r11_nul_is_a_validation_error_not_a_database_error(build):
    with pytest.raises(ValidationError, match="NUL characters are not supported"):
        build()


def test_r11_nul_free_requests_still_validate():
    assert NameRequest(name="Fictional supplier").name == "Fictional supplier"
    assert ProductInput(sku="SYN-1", description="Fictional item").sku == "SYN-1"


# R12 -----------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_r12_every_observed_row_text_is_printed_in_the_source_bytes(kind):
    with pymupdf.open(stream=generate_fixture(kind, "application/pdf"), filetype="pdf") as document:
        printed = " ".join(" ".join(page.get_text().split()) for page in document)
    payload = fixture_payload(kind)
    for row in payload.rows:
        for observation in (row.description, *row.identifiers):
            if observation.raw_value is not None:
                assert observation.raw_value in printed, (kind, row.row_id, observation.raw_value)


# S02 (receipt version) ---------------------------------------------------------

@pytest.mark.parametrize("kind", ["purchase_order", "partial", "continuation"])
def test_s02_synthetic_receipt_version_matches_the_payload(kind):
    result = SyntheticProvider().extract(generate_fixture(kind), "application/pdf", 1)
    assert result.state == "succeeded"
    assert result.schema_version == result.payload.schema_version
