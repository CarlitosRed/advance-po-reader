"""Default v1 compatibility and bypass-first checks at the real API boundary."""
from contextlib import contextmanager
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config import Settings
from tests.goal.conftest import PRODUCTS, ok, process, product_row, review_body, payload, source_bytes
from tests.goal.test_goal_coverage import approve, count, finish, summary
from tests.goal.test_goal_grounding import from_bytes
from tests.goal.test_goal_f7_f8 import ack, document_ref, page_ref

pytestmark = pytest.mark.goal


def rows():
    return [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2")]


@contextmanager
def enabled_client(desk, engine):
    settings = desk.settings.model_copy(update={"safety_net_finish_blocking": True})
    with TestClient(create_app(settings, engine=engine, provider=desk.provider),
                    base_url="http://127.0.0.1:8014", headers=dict(desk.client.headers)) as client:
        yield client


def test_goal_10_safety_net_setting_defaults_off_and_explicit_environment_enables(monkeypatch, desk):
    assert desk.settings.safety_net_finish_blocking is False
    monkeypatch.setenv("PO_BACKEND_SAFETY_NET_FINISH_BLOCKING", "true")
    assert Settings(_env_file=None, storage_directory=desk.settings.storage_directory).safety_net_finish_blocking is True
    monkeypatch.setenv("PO_BACKEND_SAFETY_NET_FINISH_BLOCKING", "false")
    assert Settings(_env_file=None, storage_directory=desk.settings.storage_directory).safety_net_finish_blocking is False


@pytest.mark.parametrize("safety_net_finish_blocking", [False, True], indirect=True)
@pytest.mark.parametrize("media_type", ["application/pdf", "image/png", "image/jpeg"])
def test_goal_9_clean_current_flow_and_enabled_finish_checks(desk, media_type):
    products = rows()
    result = process(desk, products, media_type=media_type)
    original = deepcopy(result.result["extraction"])
    assert result.run["state"] == ("partial" if desk.settings.safety_net_finish_blocking else "completed")
    approve(desk, result, products)
    value = summary(desk, result)
    if desk.settings.safety_net_finish_blocking:
        assert "independent_page_product_counts_required" in value["blockers"]
        assert finish(desk, result).status_code == 409
        ok(count(desk, result, 1))
        if media_type != "application/pdf":
            from tests.goal.test_goal_grounding import confirm
            assert "unavailable_page_text_requires_confirmation" in summary(desk, result)["blockers"]
            ok(confirm(desk, result))
    else:
        assert value["source_grounding"] == [] and value["blockers"] == []
    assert summary(desk, result)["can_finish_review"] is True
    ok(finish(desk, result))
    assert summary(desk, result)["review_state"] == "resolved"
    assert ok(desk.client.get(f"/runs/{result.run['id']}/result"))["extraction"] == original
    assert count(desk, result, 1).status_code == 409


def test_goal_9_off_keeps_legacy_tab_page_and_document_acknowledgments(desk):
    products = rows()
    raw = payload(products)
    raw["pages"][0].update(state="partial", uncertainty="Fictional partial page")
    raw["warnings"] = ["Fictional document warning"]
    result = from_bytes(desk, products, source_bytes(products), raw)
    result.suggestions = ok(desk.client.get(f"/runs/{result.run['id']}/suggestions"))["suggestions"]
    approve(desk, result, products)
    assert "partial_pages_require_explicit_acknowledgement" in summary(desk, result)["blockers"]
    ok(ack(desk, result, "acknowledge_page", products[0]["evidence"]))
    assert summary(desk, result)["blockers"] == ["document_warnings_require_explicit_acknowledgement"]
    ok(ack(desk, result, "acknowledge_document", products[0]["evidence"]))
    assert summary(desk, result)["can_finish_review"]
    ok(finish(desk, result))


def test_goal_10_switch_on_rejects_saved_legacy_acknowledgments_and_missing_grounding(desk, goal_engine):
    products = rows()
    raw = payload(products)
    raw["pages"][0].update(state="partial", uncertainty="Fictional partial page")
    raw["warnings"] = ["Fictional warning"]
    result = from_bytes(desk, products, source_bytes(products), raw)
    ok(ack(desk, result, "acknowledge_page", products[0]["evidence"]))
    ok(ack(desk, result, "acknowledge_document", products[0]["evidence"]))
    with enabled_client(desk, goal_engine) as client:
        value = ok(client.get(f"/runs/{result.run['id']}/summary"))
        assert {"partial_pages_require_explicit_acknowledgement", "document_warnings_require_explicit_acknowledgement",
                "independent_page_product_counts_required", "source_grounding_requires_new_processing_run"} <= set(value["blockers"])
        body = {"action": "acknowledge_page", "reviewer": "Fictional reviewer", "reason": "Legacy bypass probe",
                "evidence_reference": products[0]["evidence"]}
        assert client.post(f"/runs/{result.run['id']}/reviews", json=body).status_code == 422
        assert client.post(f"/runs/{result.run['id']}/reviews", json={"action": "resolve",
            "reviewer": "Fictional reviewer", "reason": "Cannot bypass enabled checks"}).status_code == 409


@pytest.mark.parametrize("safety_net_finish_blocking", [True], indirect=True)
@pytest.mark.parametrize("bad", ["missing_scope", "renamed_scope", "case_scope", "newline_hash", "unicode_hash", "float_page"])
def test_goal_10_typed_acknowledgment_near_valid_inputs_do_not_append(desk, bad):
    products = rows()
    raw = payload(products)
    raw["pages"][0].update(state="partial", uncertainty="Fictional partial page")
    result = from_bytes(desk, products, source_bytes(products), raw)
    ref = page_ref(result)
    if bad == "missing_scope": ref.pop("scope")
    elif bad == "renamed_scope": ref["kind"] = ref.pop("scope")
    elif bad == "case_scope": ref["scope"] = "Page"
    elif bad == "newline_hash": ref["source_sha256"] += "\n"
    elif bad == "unicode_hash": ref["source_sha256"] = "ａ" * 64
    elif bad == "float_page": ref["page_number"] = 1.0
    assert ack(desk, result, "acknowledge_page", [ref]).status_code == 422
    assert ok(desk.client.get(f"/runs/{result.run['id']}/reviews"))["events"] == []
    assert "partial_pages_require_explicit_acknowledgement" in summary(desk, result)["blockers"]


@pytest.mark.parametrize("safety_net_finish_blocking", [True], indirect=True)
def test_goal_10_changed_source_after_all_checks_cannot_finish(desk):
    products = rows()
    result = process(desk, products)
    approve(desk, result, products)
    ok(count(desk, result, 1))
    assert summary(desk, result)["can_finish_review"]
    path = desk.settings.storage_directory / result.source["storage_reference"]
    path.write_bytes(b"changed fictional bytes after confirmation")
    response = finish(desk, result)
    assert response.status_code == 409 and response.json()["error"] == "source_integrity_failed"
    assert summary(desk, result)["review_state"] != "resolved"
