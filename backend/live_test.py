"""Later, explicit source-authorized live test against the loopback server.

Nothing runs on import. Example (after the server is securely configured and
enabled): ``python -m backend.live_test --base-url http://127.0.0.1:8014
--source-path <local-source> --tenant-id <uuid> --vendor-id <uuid>
--authorized-by <name> --policy-reference <applicable-policy> --reason <reason>
--source-sha256 <exact-sha256> --authorize-external-processing``.

Only loopback connection fields are selected from the server's private .env.backend
or environment; no provider credential is accepted by this client. Hash-bound
authorization and server enablement are both required.
The command processes once, never retries an unknown remote outcome, and saves
private unreviewed evidence without claiming model performance or gold labels.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

import httpx

from backend.demo import local_base_url
from reader_agent.connection import ConnectionSettings

ROOT = Path(__file__).resolve().parents[1]
MAX_LOCAL_SOURCE_BYTES = 20 * 1024 * 1024


def _named(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} requires a nonblank value of at most {maximum} characters")
    return value


def _media_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("source must be an actual PDF, PNG, or JPEG; server decode validation remains required")


def _response(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"{method} {path} returned HTTP {response.status_code}; no retry was attempted")
    try:
        value = response.json()
    except ValueError:
        raise RuntimeError("local server returned invalid JSON; no retry was attempted") from None
    if not isinstance(value, dict):
        raise RuntimeError("local server returned an invalid response shape; no retry was attempted")
    return value


def run_live_test(
    *, base_url: str, source_path: str | Path, tenant_id: str, vendor_id: str,
    authorized_by: str, policy_reference: str, reason: str, source_sha256: str,
    authorize_external_processing: bool, output: str = "output/backend-live-test",
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Execute only after affirmative hash-bound authorization; transport is for tests."""
    if authorize_external_processing is not True:
        raise ValueError("--authorize-external-processing is required for this particular source")
    authorization = {
        "authorized": True,
        "source_sha256": source_sha256,
        "authorized_by": _named(authorized_by, field="authorized-by", maximum=120),
        "policy_reference": _named(policy_reference, field="policy-reference", maximum=500),
        "reason": _named(reason, field="reason", maximum=500),
    }
    if not isinstance(source_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", source_sha256) is None:
        raise ValueError("source-sha256 must be an exact lowercase SHA-256 value")
    try:
        tenant_id, vendor_id = str(UUID(tenant_id)), str(UUID(vendor_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("tenant-id and vendor-id must be UUIDs") from None
    base_url = local_base_url(base_url)
    destination = (ROOT / output).resolve()
    if not destination.is_relative_to((ROOT / "output").resolve()):
        raise ValueError("live test reports must stay inside this worktree's ignored output directory")
    connection = ConnectionSettings(_env_file=ROOT / ".env.backend")
    if "local_api_token" not in connection.model_fields_set:
        raise ValueError("configure PO_BACKEND_LOCAL_API_TOKEN in .env.backend or the environment for the local server")
    token = connection.local_api_token.get_secret_value()
    # Read only after all source-specific authorization arguments are validated.
    try:
        with Path(source_path).open("rb") as source:
            content = source.read(MAX_LOCAL_SOURCE_BYTES + 1)
    except OSError:
        raise ValueError("authorized local source could not be read") from None
    if not content or len(content) > MAX_LOCAL_SOURCE_BYTES:
        raise ValueError("source is empty or exceeds the local 20 MiB read bound")
    if sha256(content).hexdigest() != source_sha256:
        raise ValueError("source-sha256 does not match the authorized bytes; no upload was attempted")
    media_type = _media_type(content)
    run_key = uuid4().hex
    try:
        with httpx.Client(base_url=base_url, headers={"X-Local-Token": token, "X-Tenant-ID": tenant_id},
                          timeout=210, transport=transport, follow_redirects=False, trust_env=False) as client:
            configuration = _response(client, "GET", "/configuration")
            if configuration.get("live_processing_enabled") is not True or configuration.get("provider_configured") is not True:
                raise ValueError("server live processing is disabled or provider is not configured; no upload was attempted")
            configured_limit = configuration.get("limits", {}).get("upload_bytes")
            if type(configured_limit) is not int or len(content) > configured_limit:
                raise ValueError("source exceeds the configured server upload limit; no upload was attempted")
            suffix = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[media_type]
            source_record = _response(client, "POST", "/documents", data={"vendor_id": vendor_id},
                files={"file": (f"authorized-source.{suffix}", content, media_type)},
                headers={"Idempotency-Key": f"live-upload-{run_key}"})
            if source_record.get("sha256") != source_sha256:
                raise RuntimeError("server source hash disagrees with authorization; processing was not requested")
            run = _response(client, "POST", f"/documents/{source_record['id']}/runs", json={
                "provider": "openai", "fixture_name": None, "external_authorization": authorization,
            }, headers={"Idempotency-Key": f"live-run-{run_key}"})
            # Single explicit attempt. No polling loop or implicit reprocess.
            processed = _response(client, "POST", f"/runs/{run['id']}/process")
            result = _response(client, "GET", f"/runs/{run['id']}/result")
            suggestions = _response(client, "GET", f"/runs/{run['id']}/suggestions")
    except httpx.HTTPError:
        raise RuntimeError("local request was interrupted; outcome may be unknown, and no retry was attempted") from None
    except KeyError:
        raise RuntimeError("local response omitted an identifier; no retry was attempted") from None
    evidence = {
        "report_version": "local-live-test-unreviewed.v1",
        "evidence_kind": "unreviewed_provider_observations",
        "interpretation": "This report is not ground truth or a performance evaluation. Every product resolution requires human review.",
        "source": source_record, "authorization": authorization,
        "run": processed, "result": result, "suggestions": suggestions,
        "performance_metrics": None,
    }
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / f"unreviewed-{run_key}.json"
    report_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return {"run_id": run["id"], "state": processed.get("state"),
            "outcome_code": processed.get("outcome_code"), "report_path": str(report_path),
            "evidence_kind": evidence["evidence_kind"], "automatic_retries": 0}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=ConnectionSettings().base_url)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--vendor-id", required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--policy-reference", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--authorize-external-processing", action="store_true")
    parser.add_argument("--output", default="output/backend-live-test")
    args = parser.parse_args(argv)
    try:
        value = run_live_test(**vars(args))
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Live test stopped: {exc}") from None
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
