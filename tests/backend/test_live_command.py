from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

import backend.live_test as live_test
from backend.synthetic import generate_fixture


@pytest.fixture
def live_args(tmp_path, monkeypatch):
    # Tests use synthetic source bytes and a mock transport only. Override the
    # private report root to this test's own directory, never a customer corpus.
    monkeypatch.setattr(live_test, "ROOT", tmp_path)
    monkeypatch.setenv("PO_BACKEND_LOCAL_API_TOKEN", "test-local-token-not-a-provider-key")
    content = generate_fixture()
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(content)
    return {"base_url": "http://127.0.0.1:8012", "source_path": source,
            "tenant_id": str(uuid4()), "vendor_id": str(uuid4()),
            "authorized_by": "Synthetic test reviewer", "policy_reference": "Offline test only",
            "reason": "Validate command without an external provider call",
            "source_sha256": sha256(content).hexdigest(), "authorize_external_processing": True,
            "output": "output/test-live-command"}


def mock_server(*, configured=True, enabled=None, process_timeout=False):
    calls = []
    source_id, run_id = str(uuid4()), str(uuid4())

    def handler(request):
        calls.append(request)
        if request.url.path == "/configuration":
            return httpx.Response(200, json={"live_processing_enabled": configured if enabled is None else enabled,
                "provider_configured": configured, "limits": {"upload_bytes": 10485760}})
        if request.url.path == "/documents":
            content = generate_fixture()
            return httpx.Response(201, json={"id": source_id, "sha256": sha256(content).hexdigest()})
        if request.url.path == f"/documents/{source_id}/runs":
            assert json.loads(request.content)["external_authorization"]["authorized"] is True
            return httpx.Response(201, json={"id": run_id, "state": "created"})
        if request.url.path == f"/runs/{run_id}/process":
            if process_timeout:
                raise httpx.ReadTimeout("fake sensitive transport detail", request=request)
            return httpx.Response(200, json={"id": run_id, "state": "completed", "outcome_code": "ready_for_human_review"})
        if request.url.path == f"/runs/{run_id}/result":
            return httpx.Response(200, json={"extraction": {"document_type": "purchase_order"}, "attempts": []})
        if request.url.path == f"/runs/{run_id}/suggestions":
            return httpx.Response(200, json={"suggestions": []})
        raise AssertionError(f"Unexpected mock route: {request.method} {request.url.path}")

    return calls, httpx.MockTransport(handler)


def test_missing_affirmative_flag_stops_before_reading_source_or_contacting_server(live_args):
    calls, transport = mock_server()
    live_args.update(authorize_external_processing=False, source_path="does-not-exist")
    with pytest.raises(ValueError, match="authorize-external-processing"):
        live_test.run_live_test(**live_args, transport=transport)
    assert calls == []


@pytest.mark.parametrize("field", ["authorized_by", "policy_reference", "reason"])
def test_missing_named_authorization_stops_before_source_read(live_args, field):
    calls, transport = mock_server()
    live_args.update(source_path="does-not-exist", **{field: " "})
    with pytest.raises(ValueError, match="nonblank"):
        live_test.run_live_test(**live_args, transport=transport)
    assert calls == []


def test_hash_mismatch_and_external_url_stop_before_any_request(live_args):
    calls, transport = mock_server()
    live_args["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        live_test.run_live_test(**live_args, transport=transport)
    assert calls == []
    live_args["base_url"] = "https://api.openai.com"
    with pytest.raises(ValueError, match="loopback"):
        live_test.run_live_test(**live_args, transport=transport)
    assert calls == []


@pytest.mark.parametrize("configured,enabled", [(False, False), (True, False), (False, True)])
def test_server_disabled_or_missing_provider_stops_before_upload(live_args, configured, enabled):
    calls, transport = mock_server(configured=configured, enabled=enabled)
    with pytest.raises(ValueError, match="no upload"):
        live_test.run_live_test(**live_args, transport=transport)
    assert [(request.method, request.url.path) for request in calls] == [("GET", "/configuration")]


def test_token_must_be_explicit_env_and_never_imports_provider_key(live_args, monkeypatch):
    calls, transport = mock_server()
    monkeypatch.delenv("PO_BACKEND_LOCAL_API_TOKEN")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-does-not-authorize-command")
    with pytest.raises(ValueError, match="PO_BACKEND_LOCAL_API_TOKEN"):
        live_test.run_live_test(**live_args, transport=transport)
    assert calls == []


def test_success_uses_hash_bound_authorization_one_process_and_unreviewed_report(live_args):
    calls, transport = mock_server()
    returned = live_test.run_live_test(**live_args, transport=transport)
    assert returned["automatic_retries"] == 0
    assert returned["evidence_kind"] == "unreviewed_provider_observations"
    assert returned["state"] == "completed"
    assert len(calls) == 6
    assert sum(request.url.path.endswith("/process") for request in calls) == 1
    assert all(request.headers["X-Local-Token"] == "test-local-token-not-a-provider-key" for request in calls)
    assert all("authorization" not in request.headers for request in calls)
    run_request = next(request for request in calls if request.url.path.endswith("/runs"))
    body = json.loads(run_request.content)
    assert body["provider"] == "openai" and body["fixture_name"] is None
    assert body["external_authorization"]["source_sha256"] == live_args["source_sha256"]
    report = json.loads(Path(returned["report_path"]).read_text(encoding="utf-8"))
    assert report["performance_metrics"] is None
    assert report["evidence_kind"] == "unreviewed_provider_observations"
    assert "not ground truth" in report["interpretation"]


def test_timeout_preserves_unknown_outcome_without_retry_or_secret_echo(live_args):
    calls, transport = mock_server(process_timeout=True)
    with pytest.raises(RuntimeError, match="unknown.*no retry") as error:
        live_test.run_live_test(**live_args, transport=transport)
    assert "sensitive transport detail" not in str(error.value)
    assert sum(request.url.path.endswith("/process") for request in calls) == 1
    assert len(calls) == 4


def test_cli_requires_material_specific_arguments_and_affirmative_flag(live_args, monkeypatch):
    with pytest.raises(SystemExit):
        live_test.main([])
    arguments = ["--source-path", str(live_args["source_path"]), "--tenant-id", live_args["tenant_id"],
        "--vendor-id", live_args["vendor_id"], "--authorized-by", live_args["authorized_by"],
        "--policy-reference", live_args["policy_reference"], "--reason", live_args["reason"],
        "--source-sha256", live_args["source_sha256"]]
    with pytest.raises(SystemExit, match="authorize-external-processing"):
        live_test.main(arguments)
