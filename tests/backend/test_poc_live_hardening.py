"""Landing review round 1: R03 spend guard, R04 live startup, R05 run-admission middleware.

Offline: no database, no key, no network. The guard's database read is replaced by a list of
stored usages; the apps are small stand-ins or the real create_app without a database connection.
"""
import importlib
import math
import os
from pathlib import Path
import re
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import poc_live_support as live  # noqa: E402

PRIVATE_TOKEN = "private-test-token-long-enough"
RATES = {"PO_POC_INPUT_USD_PER_MTOK": "3", "PO_POC_OUTPUT_USD_PER_MTOK": "12"}
NORMAL = {"input_tokens": 1800, "output_tokens": 900}


def guard_with(monkeypatch, usages, environment=None):
    """A real SpendGuard whose stored attempts are `usages` (patched at the Session layer)."""
    import sqlalchemy.orm

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def scalars(self, statement):
            return type("Result", (), {"all": staticmethod(lambda: list(usages))})()

    monkeypatch.setattr(sqlalchemy.orm, "Session", FakeSession)
    return live.SpendGuard(object(), environment or {})


# ---- R03: the dollar cap cannot be disabled -----------------------------------------------------

@pytest.mark.parametrize("cap", ["nan", "NaN", "inf", "-inf", "Infinity", "0", "-1", "-0.01", "", "abc", "1,5"])
def test_unusable_cap_falls_back_to_three_dollars_and_still_blocks(monkeypatch, cap):
    huge = [{"input_tokens": 2_000_000_000, "output_tokens": 0}]
    guard = guard_with(monkeypatch, huge, {**RATES, "PO_POC_SPEND_CAP_USD": cap, "PO_POC_MAX_LIVE_RUNS": "100"})
    assert guard.cap_usd == 3.0 and math.isfinite(guard.cap_usd)
    assert guard.status()["blocked"] is True


@pytest.mark.parametrize("rate", ["0", "0.0", "-1", "nan", "inf", "-inf", "1e999", "", "x"])
@pytest.mark.parametrize("which", ["PO_POC_INPUT_USD_PER_MTOK", "PO_POC_OUTPUT_USD_PER_MTOK"])
def test_zero_negative_or_infinite_rates_are_not_prices(which, rate):
    assert live.price_rates({**RATES, which: rate}) is None


def test_bad_rates_fall_back_to_the_run_limit(monkeypatch):
    environment = {"PO_POC_INPUT_USD_PER_MTOK": "0", "PO_POC_OUTPUT_USD_PER_MTOK": "inf"}
    assert guard_with(monkeypatch, [NORMAL] * 4, environment).status()["blocked"] is False
    status = guard_with(monkeypatch, [NORMAL] * 50, environment).status()
    assert status["blocked"] is True and status["basis"] == "runs"


def test_infinite_rate_with_zero_tokens_cannot_produce_nan(monkeypatch):
    environment = {"PO_POC_INPUT_USD_PER_MTOK": "inf", "PO_POC_OUTPUT_USD_PER_MTOK": "1"}
    status = guard_with(monkeypatch, [{"input_tokens": 0, "output_tokens": 0}] * 5, environment).status()
    assert status["blocked"] is True and status["estimated_usd"] is None


@pytest.mark.parametrize("usage", [{}, None, "x", [], 7, {"input_tokens": None}, {"input_tokens": 5},
                                   {"output_tokens": 5}, {"input_tokens": "5", "output_tokens": "5"},
                                   {"input_tokens": float("nan"), "output_tokens": float("inf")},
                                   {"input_tokens": -5, "output_tokens": -5}, {"input_tokens": True, "output_tokens": True},
                                   {"input_tokens": 10 ** 400, "output_tokens": 10 ** 400}])
def test_missing_or_malformed_usage_is_charged_at_the_worst_case_not_zero(monkeypatch, usage):
    guard = guard_with(monkeypatch, [usage], {**RATES, "PO_POC_SPEND_CAP_USD": "0.10", "PO_POC_MAX_LIVE_RUNS": "100"})
    status = guard.status()
    assert status["estimated_usd"] > 0.10 and status["blocked"] is True


def test_default_run_ceiling_stays_on_when_prices_are_set(monkeypatch):
    # 100 attempts with no usage (timeouts / 5xx): the old code reported runs=100 blocked=False.
    status = guard_with(monkeypatch, [{}] * 100, RATES).status()
    assert status["runs"] == 100 and status["max_runs"] == 5 and status["blocked"] is True
    assert guard_with(monkeypatch, [NORMAL] * 5, RATES).status()["blocked"] is True


def test_near_valid_settings_still_allow_normal_use(monkeypatch):
    assert guard_with(monkeypatch, [NORMAL] * 4, RATES).status()["blocked"] is False
    status = guard_with(monkeypatch, [NORMAL] * 4, {**RATES, "PO_POC_MAX_LIVE_RUNS": "10", "PO_POC_SPEND_CAP_USD": "1e308"}).status()
    assert status["blocked"] is False and status["estimated_usd"] == round(4 * (1800 * 3 + 900 * 12) / 1e6, 4)


@pytest.mark.parametrize("runs", ["0", "-3", "1.5", "abc", ""])
def test_unusable_run_ceiling_never_unlocks_more_runs(monkeypatch, runs):
    guard = guard_with(monkeypatch, [NORMAL] * 5, {"PO_POC_MAX_LIVE_RUNS": runs})
    assert guard.status()["blocked"] is True  # 0 and -3 block everything; others fall back to 5


def test_huge_token_counts_block_without_overflow(monkeypatch):
    usage = {"input_tokens": 10 ** 30, "output_tokens": 10 ** 30}
    assert guard_with(monkeypatch, [usage], {**RATES, "PO_POC_MAX_LIVE_RUNS": "100"}).status()["blocked"] is True


# ---- R05: valid non-object JSON gets a sanitized 422, never a 500 ---------------------------------

BODIES = [b"[]", b"null", b'"text"', b"7", b"true", b"3.5", b"[{}]", b"{", b"", b"\xff\xfe"]


def stand_in_app():
    app = FastAPI()

    @app.post("/documents/{source}/runs")
    def create(source: str):
        return {"reached": "endpoint"}

    @app.post("/runs/{run}/process")
    def process(run: str):
        return {"reached": "endpoint"}

    return app


@pytest.mark.parametrize("body", BODIES)
def test_live_guard_answers_non_object_json_with_422(monkeypatch, body):
    app = stand_in_app()
    live.install_live_guard(app, guard_with(monkeypatch, [], {}))
    response = TestClient(app, raise_server_exceptions=False).post(
        "/documents/x/runs", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.json() == {"error": "invalid_request"}


def test_live_guard_still_admits_a_real_openai_run_and_refuses_others(monkeypatch):
    app = stand_in_app()
    live.install_live_guard(app, guard_with(monkeypatch, [], {}))
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/documents/x/runs", json={"provider": "openai"}).json() == {"reached": "endpoint"}
    assert client.post("/documents/x/runs", json={"provider": "synthetic"}).status_code == 409


@pytest.mark.parametrize("body", BODIES)
def test_free_demo_middleware_answers_non_object_json_with_422(body):
    support = importlib.import_module("poc_demo_support")
    app = stand_in_app()
    support.install_free_runs_only(app)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/documents/x/runs", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.json() == {"error": "invalid_request"}
    assert client.post("/documents/x/runs", json={"provider": "openai"}).status_code == 409
    assert client.post("/documents/x/runs", json={"provider": "synthetic"}).json() == {"reached": "endpoint"}


# ---- R04: every launch path that enables live processing refuses the default token and has the cap --

def live_settings(**values):
    from backend.config import Settings
    return Settings(_env_file=None, live_processing_enabled=True, openai_api_key=SecretStr("offline-placeholder-key-value"), **values)


def serve_module():
    return importlib.import_module("serve_backend")


def test_guarded_entry_refuses_live_with_the_published_default_token():
    with pytest.raises(live.LiveRefusal) as refusal:
        serve_module().build_app(live_settings())
    assert live.DEFAULT_TOKEN not in str(refusal.value) and "Nothing was started" in str(refusal.value)


def test_guarded_entry_applies_the_spend_cap_when_live_is_on(monkeypatch):
    monkeypatch.delenv("PO_POC_MAX_LIVE_RUNS", raising=False)
    guard_with(monkeypatch, [NORMAL] * 5, {})  # patches the Session layer for the guard that build_app creates
    app = serve_module().build_app(live_settings(local_api_token=SecretStr(PRIVATE_TOKEN)))
    response = TestClient(app, raise_server_exceptions=False).post("/runs/x/process")
    assert response.status_code == 409 and response.json() == {"error": "poc_spend_cap_reached"}
    response = TestClient(app, raise_server_exceptions=False).post("/documents/x/runs", content=b"[]",
                                                                     headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_guarded_entry_leaves_free_mode_unchanged(monkeypatch):
    from backend.config import Settings
    guard_with(monkeypatch, [NORMAL] * 99, {})
    app = serve_module().build_app(Settings(_env_file=None))
    response = TestClient(app, raise_server_exceptions=False).post("/runs/x/process")
    assert response.json().get("error") != "poc_spend_cap_reached"


@pytest.mark.parametrize("token,expect_exit", [(None, True), (PRIVATE_TOKEN, False)])
def test_main_exits_before_serving_with_the_default_token(monkeypatch, capsys, token, expect_exit):
    import backend.config
    import uvicorn
    served = []
    values = {"local_api_token": SecretStr(token)} if token else {}
    settings = live_settings(**values)  # built before Settings is replaced
    monkeypatch.setattr(backend.config, "Settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: served.append(args))
    guard_with(monkeypatch, [], {})
    if expect_exit:
        with pytest.raises(SystemExit) as stop:
            serve_module().main()
        assert stop.value.code == 2 and served == []
        assert "private local API token" in capsys.readouterr().out
    else:
        serve_module().main()
        assert len(served) == 1


def test_main_exits_cleanly_when_settings_cannot_load(monkeypatch, capsys):
    import backend.config
    import uvicorn

    def broken():
        raise ValueError("secret-value-should-not-print")

    monkeypatch.setattr(backend.config, "Settings", broken)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("must not serve"))
    with pytest.raises(SystemExit) as stop:
        serve_module().main()
    assert stop.value.code == 2 and "secret-value" not in capsys.readouterr().out


@pytest.mark.parametrize("name", ["start-backend.ps1", "start-local-website.ps1"])
def test_launchers_start_the_server_only_through_the_guarded_entry(name):
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert "scripts/serve_backend.py" in text
    assert not re.search(r"-m\s+backend\b(?!\.)", text), "a launcher must not start python -m backend directly"


def test_no_script_or_launcher_starts_the_unguarded_server():
    for path in (ROOT / "scripts").iterdir():
        if path.suffix in {".ps1", ".py", ".cjs", ".js"} and path.name != "test_poc_live_hardening.py":
            assert not re.search(r"-m\s+backend(?![\w.])", path.read_text(encoding="utf-8")), path.name


# ---- docs that name -LiveDemo must say what protects it; the runbook must not overpromise -----------

@pytest.mark.parametrize("name", ["local-agent-demo.md", "api-activation-handoff.md",
                                  "live-demo-continuation.md", "api-activation-verification.md"])
def test_docs_that_start_live_with_live_demo_state_the_cap_or_point_to_the_capped_launcher(name):
    text = (ROOT / "docs" / name).read_text(encoding="utf-8")
    assert "-LiveDemo" in text and "start-poc-demo.ps1 -Live" in text


def test_runbook_does_not_promise_that_a_file_is_never_sent_twice():
    text = (ROOT / "docs" / "poc-demo-runbook.md").read_text(encoding="utf-8")
    assert "never sent twice" not in text and "timed out" in text and "can cost again" in text
    assert "153 fictional products" in text and "three tabs" in text and "150" not in text
