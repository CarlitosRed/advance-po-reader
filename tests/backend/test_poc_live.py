"""POC live mode: refusal paths, the one-page probe and the spend guard, all on fake transports.

No key, no dotenv file and no network: every OpenAI exchange is an httpx.MockTransport.
"""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import poc_live_support as live  # noqa: E402
from poc_demo_support import FIXTURES  # noqa: E402

TOKEN = "private-test-token-long-enough"
FAKE_KEY = "offline-placeholder-key-value"


def _case_payload():
    cases = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]
    from poc_demo_support import payload_for
    return payload_for(cases[0])


def _probe_module():
    spec = importlib.util.spec_from_file_location("poc_probe_live", ROOT / "scripts" / "poc-probe-live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_environment(monkeypatch):
    for name in list(os.environ):
        if name == "OPENAI_API_KEY" or name.startswith(("PO_BACKEND_", "PO_POC_")):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ---- refusal paths -------------------------------------------------------------------------

def test_live_refuses_without_a_key(clean_environment):
    clean_environment.setenv("PO_BACKEND_LOCAL_API_TOKEN", TOKEN)
    with pytest.raises(live.LiveRefusal) as refusal:
        live.check_live_settings(env_file=None)
    assert "OPENAI_API_KEY" in str(refusal.value) and TOKEN not in str(refusal.value)


def test_live_refuses_the_public_default_token(clean_environment):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    with pytest.raises(live.LiveRefusal) as refusal:
        live.check_live_settings(env_file=None)
    assert "private local API token" in str(refusal.value) and FAKE_KEY not in str(refusal.value)


def test_live_refuses_a_short_token_without_printing_it(clean_environment):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    clean_environment.setenv("PO_BACKEND_LOCAL_API_TOKEN", "short")
    with pytest.raises(live.LiveRefusal) as refusal:
        live.check_live_settings(env_file=None)
    assert "short" not in str(refusal.value) and FAKE_KEY not in str(refusal.value)


def test_live_accepts_a_key_and_a_private_token(clean_environment):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    clean_environment.setenv("PO_BACKEND_LOCAL_API_TOKEN", TOKEN)
    settings = live.check_live_settings(env_file=None)
    assert settings.live_processing_enabled and settings.extraction_model == "gpt-6-luna"


def test_launcher_switches_are_explicit_and_free_mode_is_the_default():
    script = (ROOT / "scripts" / "start-poc-demo.ps1").read_text(encoding="utf-8")
    assert "[switch]$Live" in script and "[switch]$LiveRehearsal" in script
    assert script.count("--live") == 2  # '--live' and '--live-rehearsal' only when asked
    assert "if ($Live) {" in script and "PO_BACKEND_PROVIDER_TIMEOUT_SECONDS = '180'" in script


# ---- the one-page probe ---------------------------------------------------------------------

def _success_transport():
    return live.rehearsal_transport(_case_payload())


def test_probe_refuses_without_confirm_and_sends_nothing(capsys):
    def never(request):
        pytest.fail("the probe must not reach any transport without --confirm")
    assert _probe_module().main([], transport=httpx.MockTransport(never)) == 2
    assert "--confirm" in capsys.readouterr().out


def test_probe_reports_only_sanitized_facts(clean_environment, capsys):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    clean_environment.setenv("PO_POC_INPUT_USD_PER_MTOK", "1")
    clean_environment.setenv("PO_POC_OUTPUT_USD_PER_MTOK", "2")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return _success_transport().handle_request(request)

    assert _probe_module().main(["--confirm"], transport=httpx.MockTransport(handler), env_file=None) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["model"] == "gpt-6-luna" and report["result"] == "succeeded"
    assert report["tokens"] == {"input": 1800, "output": 900, "total": 2700}
    assert report["estimated_cost_usd"] == 0.0036 and report["model_accepted_this_input"] == "yes"
    assert FAKE_KEY not in output
    content = requests[0]["input"][0]["content"][0]
    assert content["type"] == "input_file" and content["file_data"].startswith("data:application/pdf;base64,")


def test_probe_images_option_sends_a_page_image(clean_environment, capsys):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["input"][0]["content"][0]["type"])
        return _success_transport().handle_request(request)

    assert _probe_module().main(["--confirm", "--images"], transport=httpx.MockTransport(handler), env_file=None) == 0
    assert seen == ["input_image"] and json.loads(capsys.readouterr().out)["input_sent"] == "page image (PNG)"


def test_probe_reads_a_rejected_pdf_as_probably_not_supported(clean_environment, capsys):
    clean_environment.setenv("OPENAI_API_KEY", FAKE_KEY)
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": {"message": "secret detail"}}))
    assert _probe_module().main(["--confirm"], transport=transport, env_file=None) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["model_accepted_this_input"] == "probably_no" and report["failure"] == "provider_http_400"
    assert "secret detail" not in output and report["estimated_cost_usd"].startswith("not estimated")


def test_price_rates_need_both_values():
    assert live.price_rates({"PO_POC_INPUT_USD_PER_MTOK": "1"}) is None
    assert live.price_rates({"PO_POC_INPUT_USD_PER_MTOK": "1", "PO_POC_OUTPUT_USD_PER_MTOK": "x"}) is None
    assert live.estimate_cost({"input_tokens": 1_000_000, "output_tokens": 500_000}, (2.0, 4.0)) == 4.0


def test_images_mode_is_off_unless_asked():
    assert not live.images_mode_enabled({}) and live.images_mode_enabled({"PO_POC_PDF_AS_IMAGES": "1"})


# ---- authorization and the spend guard against a real (test-owned) database ---------------------

@pytest.fixture(scope="module")
def live_engine():
    value = os.environ.get("PO_BACKEND_API_TEST_DATABASE_URL")
    if not value:
        pytest.skip("isolated PostgreSQL API database is not configured")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith(("gate_a_test_backend_", "orderlens_product_rows")) or url.query):
        pytest.fail("live-mode tests require a loopback isolated test database")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    config = Config(str(ROOT / "backend.alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_authorization_is_bound_to_the_file_and_the_cap_stops_new_runs(live_engine):
    from backend.app import create_app
    from backend.config import Settings
    from backend.providers import OpenAIProvider
    settings = Settings(_env_file=None, database_url=SecretStr(live_engine.url.render_as_string(hide_password=False)),
                        storage_directory=ROOT / "data" / "demo-agent" / "tests" / uuid4().hex, local_api_token=SecretStr(TOKEN),
                        live_processing_enabled=True, openai_api_key=SecretStr(FAKE_KEY))
    provider = OpenAIProvider(api_key=FAKE_KEY, enabled=True, transport=_success_transport())
    app = create_app(settings, engine=live_engine, provider=provider)
    # The shared test database may hold other live-style attempts; allow exactly one more.
    before = live.SpendGuard(live_engine, {}).status()["runs"]
    guard = live.SpendGuard(live_engine, {"PO_POC_MAX_LIVE_RUNS": str(before + 1)})
    live.install_live_guard(app, guard)
    document, _ = live.probe_document()
    digest = sha256(document).hexdigest()
    products = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))["products"][:12]
    with TestClient(app, base_url="http://127.0.0.1:8014", headers={"X-Local-Token": TOKEN}) as client:
        tenant = client.post("/tenants", json={"name": "Live POC tenant " + uuid4().hex}).json()
        client.headers["X-Tenant-ID"] = tenant["id"]
        vendor = client.post("/vendors", json={"name": "Live POC vendor"}).json()
        assert client.post("/catalog/import", json={"vendor_id": vendor["id"], "products": products}).status_code in (200, 201)
        source = client.post("/documents", headers={"Idempotency-Key": uuid4().hex}, data={"vendor_id": vendor["id"]},
                             files={"file": ("sample.pdf", document, "application/pdf")}).json()
        assert source["sha256"] == digest

        def create(authorization):
            return client.post(f"/documents/{source['id']}/runs", headers={"Idempotency-Key": uuid4().hex},
                               json={"provider": "openai", **({"external_authorization": authorization} if authorization else {})})

        confirmed = {"authorized": True, "source_sha256": digest, "authorized_by": "Test owner",
                     "policy_reference": "Owner confirmation in the local live POC", "reason": "Confirmed in the test"}
        # Without the confirmation the backend refuses to send anything.
        refused = create(None)
        assert refused.status_code == 201
        assert client.post(f"/runs/{refused.json()['id']}/process").json()["outcome_code"] == "external_processing_authorization_required"
        assert guard.status()["runs"] == before
        # An authorization for another file's hash is rejected.
        assert create({**confirmed, "source_sha256": "0" * 64}).status_code == 422
        # The confirmed file is read once through the fake transport.
        run = create(confirmed)
        assert run.status_code == 201
        done = client.post(f"/runs/{run.json()['id']}/process").json()
        assert done["state"] in {"completed", "partial"}
        assert client.get(f"/runs/{run.json()['id']}/result").json()["attempts"][-1]["usage"]["input_tokens"] == 1800
        status = guard.status()
        assert status["runs"] == before + 1 and status["basis"] == "runs" and status["blocked"] is True
        assert "Cost is not recorded" in status["message"] and "limit" in status["message"]
        # At the cap, a new live run is refused before anything is created or sent.
        blocked = create(confirmed)
        assert blocked.status_code == 409 and blocked.json()["error"] == "poc_spend_cap_reached"
        # Live mode accepts only OpenAI runs.
        other = client.post(f"/documents/{source['id']}/runs", headers={"Idempotency-Key": uuid4().hex},
                            json={"provider": "synthetic"})
        assert other.status_code == 409
