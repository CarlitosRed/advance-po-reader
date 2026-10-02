"""Explicit local synthetic end-to-end demo, with inspectable private reports.

Run ``python -m backend.demo --help``. This command never enables OpenAI, reads a
provider key, or sends a fixture to any external host. Server live activation is
an independent, later authorization flow.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from backend.evaluation import EvaluationCase, ExpectedDocument, evaluate_cases
from backend.synthetic import generate_fixture

ROOT = Path(__file__).resolve().parents[1]


def fixture_expectation(case_id: str) -> ExpectedDocument:
    """Declared literal fixture labels; never generated from extractor output."""
    fields = {
        "contract_name": "ProductDocument", "schema_version": "1.1",
        "document_type": "purchase_order",
        "rows.0.identifiers.0.raw_value": "SYN-001",
        "rows.0.identifiers.0.source_label": "Vendor SKU",
        "rows.0.identifiers.0.source_role": "vendor_sku",
        "rows.0.quantity.raw_value": "2", "rows.0.quantity.state": "observed",
        "rows.0.unit.raw_value": "EA", "rows.0.unit_price.raw_value": "12.50",
        "rows.0.line_total.raw_value": "25.00",
        "rows.1.identifiers.0.raw_value": "SYN-002",
        "rows.1.quantity.raw_value": "3", "rows.1.unit.raw_value": "EA",
        "rows.1.unit_price.raw_value": "5.00", "rows.1.line_total.raw_value": "15.00",
        "rows.2.row_kind": "charge", "rows.3.row_kind": "total",
    }
    return ExpectedDocument(case_id, fields, ("line-1", "line-2"),
                            {"line-1": "SYN-001", "line-2": "SYN-002"})


def local_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("demo base URL must be an HTTP loopback origin without credentials or a path")
    return value.rstrip("/")


def output_directory(value: str) -> Path:
    path = (ROOT / value).resolve()
    if not path.is_relative_to((ROOT / "output").resolve()):
        raise ValueError("demo reports must stay in this worktree's ignored output directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request(client: httpx.Client, method: str, path: str, expected=(200, 201), **kwargs) -> dict:
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        # Do not echo server/provider body, file contents, headers, or secrets.
        raise RuntimeError(f"{method} {path} returned HTTP {response.status_code}")
    return response.json()


def run_demo(base_url: str, report_directory: Path) -> dict:
    """Exercise real local HTTP/database paths using explicitly synthetic sources."""
    base_url = local_base_url(base_url)
    demo_id = uuid4().hex
    source_directory = ROOT / "data" / "demo-agent" / demo_id
    source_directory.mkdir(parents=True, exist_ok=False)
    token = os.environ.get("PO_BACKEND_LOCAL_API_TOKEN", "local-backend-dev-only")
    cases: list[EvaluationCase] = []
    artifacts = {"demo_id": demo_id, "base_url": base_url, "kind": "synthetic_workflow",
                 "checks": [], "sources": [], "runs": []}
    with httpx.Client(base_url=base_url, headers={"X-Local-Token": token}, timeout=60) as client:
        _request(client, "GET", "/health/ready")
        tenant = _request(client, "POST", "/tenants", json={"name": f"Synthetic demo {demo_id}"})
        client.headers["X-Tenant-ID"] = tenant["id"]
        vendor = _request(client, "POST", "/vendors", json={"name": "Synthetic Example Vendor"})
        artifacts["tenant"] = tenant
        artifacts["vendor"] = vendor
        catalog = _request(client, "POST", "/catalog/import", json={
            "vendor_id": vendor["id"], "products": [
                {"sku": "SYN-001", "description": "Synthetic blue widget", "aliases": [
                    {"value": "BLUE-LEGACY", "source_role": "customer_item"}]},
                {"sku": "SYN-002", "description": "Synthetic red widget", "aliases": []},
            ],
        })
        artifacts["catalog"] = catalog
        for media_type, suffix in (("application/pdf", "pdf"), ("image/png", "png")):
            content = generate_fixture(kind="purchase_order", media_type=media_type)
            fixture_path = source_directory / f"synthetic-po.{suffix}"
            fixture_path.write_bytes(content)
            upload_key = f"{demo_id}-upload-{suffix}"
            upload_args = {"data": {"vendor_id": vendor["id"]},
                           "files": {"file": (fixture_path.name, content, media_type)},
                           "headers": {"Idempotency-Key": upload_key}}
            source = _request(client, "POST", "/documents", **upload_args)
            duplicate = _request(client, "POST", "/documents", **upload_args)
            if duplicate["id"] != source["id"]:
                raise RuntimeError("retry created a second source")
            artifacts["checks"].append({"name": f"{suffix}_upload_retry", "passed": True})
            conflict = client.post("/documents", data={"vendor_id": vendor["id"]},
                files={"file": ("different-payload.pdf", generate_fixture(kind="unsupported"), "application/pdf")},
                headers={"Idempotency-Key": upload_key})
            if conflict.status_code != 409:
                raise RuntimeError("same-key/different-payload upload did not report conflict")
            artifacts["checks"].append({"name": f"{suffix}_upload_payload_conflict", "passed": True})
            artifacts["sources"].append(source)
            run_args = {"json": {
                "provider": "synthetic", "fixture_name": "purchase_order", "external_authorization": None,
            }, "headers": {"Idempotency-Key": f"{demo_id}-run-{suffix}"}}
            run = _request(client, "POST", f"/documents/{source['id']}/runs", **run_args)
            run_duplicate = _request(client, "POST", f"/documents/{source['id']}/runs", **run_args)
            if run_duplicate["id"] != run["id"]:
                raise RuntimeError("retry created a second processing run")
            artifacts["checks"].append({"name": f"{suffix}_run_retry", "passed": True})
            if run["state"] != "created":
                raise RuntimeError("run creation processed without explicit request")
            run = _request(client, "POST", f"/runs/{run['id']}/process")
            if run["state"] != "completed":
                raise RuntimeError("synthetic PO processing did not complete")
            result = _request(client, "GET", f"/runs/{run['id']}/result")
            suggestions = _request(client, "GET", f"/runs/{run['id']}/suggestions")["suggestions"]
            products = {row["row_id"]: row for row in result["extraction"]["rows"] if row["row_kind"] == "product"}
            if {item["row_id"] for item in suggestions} != set(products):
                raise RuntimeError("non-product rows entered matching or product rows disappeared")
            for suggestion in suggestions:
                if suggestion["outcome"] != "suggested" or len(suggestion["candidates"]) != 1:
                    raise RuntimeError("declared fixture exact match is not a single review-only suggestion")
                row = products[suggestion["row_id"]]
                _request(client, "POST", f"/runs/{run['id']}/reviews", json={
                    "action": "approve", "row_id": row["row_id"], "reviewer": "Synthetic demo reviewer",
                    "reason": "Explicit approval of declared synthetic fixture candidate",
                    "evidence_reference": row["evidence"],
                    "selected_candidate_id": suggestion["candidates"][0]["candidate_id"],
                    "field_name": None, "new_value": None,
                })
            for row in result["extraction"]["rows"]:
                if row["row_kind"] == "product":
                    continue
                _request(client, "POST", f"/runs/{run['id']}/reviews", json={
                    "action": "acknowledge", "row_id": row["row_id"], "reviewer": "Synthetic demo reviewer",
                    "reason": "Inspected non-product synthetic row; excluded from catalog matching",
                    "evidence_reference": row["evidence"], "selected_candidate_id": None,
                    "field_name": None, "new_value": None,
                })
            _request(client, "POST", f"/runs/{run['id']}/reviews", json={
                "action": "resolve", "row_id": None, "reviewer": "Synthetic demo reviewer",
                "reason": "All synthetic product lines explicitly reviewed",
                "evidence_reference": [], "selected_candidate_id": None,
                "field_name": None, "new_value": None,
            })
            run = _request(client, "GET", f"/runs/{run['id']}")
            reviews = _request(client, "GET", f"/runs/{run['id']}/reviews")["events"]
            if run["review_state"] != "resolved":
                raise RuntimeError("explicit review did not resolve fixture run")
            after_review = _request(client, "GET", f"/runs/{run['id']}/result")
            if result["extraction"] != after_review["extraction"]:
                raise RuntimeError("review changed immutable observations")
            artifacts["runs"].append({"run": run, "result": result, "suggestions": suggestions, "reviews": reviews})
            cases.append(EvaluationCase(fixture_expectation(f"purchase-order-{suffix}"), run,
                                        result["extraction"], suggestions, reviews, result["attempts"]))

        # Run-level retry history and an ordinary disabled OpenAI outcome.
        first_source = artifacts["sources"][0]
        disabled = _request(client, "POST", f"/documents/{first_source['id']}/runs", json={
            "provider": "openai", "fixture_name": None, "external_authorization": None,
        }, headers={"Idempotency-Key": f"{demo_id}-disabled-openai"})
        disabled = _request(client, "POST", f"/runs/{disabled['id']}/process")
        if disabled.get("outcome_code") != "provider_not_configured":
            raise RuntimeError("disabled OpenAI path did not report provider_not_configured")
        disabled_result = _request(client, "GET", f"/runs/{disabled['id']}/result")
        if disabled_result["extraction"] is not None:
            raise RuntimeError("disabled live processing silently substituted extraction")
        artifacts["runs"].append({"run": disabled, "result": disabled_result})
        cases.append(EvaluationCase(fixture_expectation("disabled-openai"), disabled,
                                    disabled_result["extraction"], attempts=disabled_result["attempts"]))

        unsupported_content = generate_fixture(kind="unsupported", media_type="application/pdf")
        (source_directory / "synthetic-unsupported.pdf").write_bytes(unsupported_content)
        unsupported_source = _request(client, "POST", "/documents", data={"vendor_id": vendor["id"]},
            files={"file": ("synthetic-unsupported.pdf", unsupported_content, "application/pdf")},
            headers={"Idempotency-Key": f"{demo_id}-unsupported-upload"})
        unsupported = _request(client, "POST", f"/documents/{unsupported_source['id']}/runs", json={
            "provider": "synthetic", "fixture_name": "unsupported", "external_authorization": None,
        }, headers={"Idempotency-Key": f"{demo_id}-unsupported-run"})
        unsupported = _request(client, "POST", f"/runs/{unsupported['id']}/process")
        unsupported_result = _request(client, "GET", f"/runs/{unsupported['id']}/result")
        unsupported_suggestions = _request(client, "GET", f"/runs/{unsupported['id']}/suggestions")["suggestions"]
        if unsupported_suggestions:
            raise RuntimeError("unsupported source entered catalog matching")
        artifacts["runs"].append({"run": unsupported, "result": unsupported_result})
        cases.append(EvaluationCase(ExpectedDocument("unsupported", {"document_type": "unsupported"}, ()),
                                    unsupported, unsupported_result["extraction"],
                                    unsupported_suggestions, attempts=unsupported_result["attempts"]))
        artifacts["checks"].append({"name": "unsupported_matching_stopped", "passed": True})

    report = evaluate_cases(cases, dataset_name="declared-local-synthetic-fixtures", dataset_version="1")
    report_directory.mkdir(parents=True, exist_ok=True)
    (report_directory / "workflow-evidence.json").write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    (report_directory / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"demo_id": demo_id, "report_directory": str(report_directory),
            "synthetic_case_count": len(cases), "external_provider_requests": 0,
            "interpretation": report["interpretation"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--output", default="output/backend-demo")
    args = parser.parse_args()
    try:
        result = run_demo(local_base_url(args.base_url), output_directory(args.output))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise SystemExit(f"Synthetic demo failed: {exc}") from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
