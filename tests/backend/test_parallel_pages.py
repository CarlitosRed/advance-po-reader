"""Page-parallel reading: split, request at the same time, merge, validate. Fake transports only."""
from base64 import b64decode
from copy import deepcopy
import json
import re
from threading import Barrier, Lock
from time import sleep

import httpx
import pymupdf
import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.contracts import validate_payload
from backend.providers import MAX_SPLIT_PAGES, OpenAIProvider, PROMPT_VERSION, merge_page_payloads
from backend.synthetic import fixture_payload

USAGE = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
         "input_tokens_details": {"cached_tokens": 2}, "output_tokens_details": {"reasoning_tokens": 3}}


def _page_payload():
    return fixture_payload("continuation").model_dump(mode="json")


def _body(payload, status="completed", usage=USAGE):
    return {"id": "resp_page", "status": status, "usage": usage,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}]}


def _pdf(pages):
    with pymupdf.open() as document:
        for number in range(1, pages + 1):
            document.new_page().insert_text((72, 72), f"PAGEMARK{number}END")
        return document.tobytes()


def _request_page(request):
    body = json.loads(request.content)
    text = body["input"][0]["content"][1]["text"]
    match = re.search(r"page (\d+) of (\d+)", text)
    return body, text, (int(match.group(1)) if match else None)


def _provider(handler, **options):
    options.setdefault("split_pages", True)
    return OpenAIProvider(api_key="offline-placeholder", enabled=True,
                          transport=httpx.MockTransport(handler), **options)


def test_pages_are_split_sent_separately_and_merged_into_one_valid_document(capsys):
    seen = []

    def handler(request):
        body, text, number = _request_page(request)
        media = body["input"][0]["content"][0]
        assert media["type"] == "input_file" and body["model"] == "gpt-6-luna"
        with pymupdf.open(stream=b64decode(media["file_data"].split(",", 1)[1]), filetype="pdf") as one:
            assert one.page_count == 1
            assert f"PAGEMARK{number}END" in one[0].get_text()
        assert "Source page count: 1." in text and "of 3" in text and "reasoning" not in body
        seen.append(number)
        return httpx.Response(200, json=_body(_page_payload()), headers={"x-request-id": f"req_{number}"})

    result = _provider(handler).extract(_pdf(3), "application/pdf", 3)
    assert sorted(seen) == [1, 2, 3] and result.state == "succeeded" and result.error_code is None
    payload = result.payload
    assert [page.page_number for page in payload.pages] == [1, 2, 3]
    ids = [row.row_id for row in payload.rows]
    assert len(ids) == len(set(ids)) == 21 and ids[0] == "p1-item-101" and ids[7] == "p2-item-101"
    by_id = {row.row_id: row for row in payload.rows}
    for row in payload.rows:
        page = int(row.row_id[1])
        assert {ref.page_number for ref in row.evidence} == {page}
        assert row.item_group_id is None or row.item_group_id.startswith(f"p{page}-")
        if row.continuation_of:
            assert by_id[row.continuation_of].evidence[0].page_number == page
    assert result.usage["total_tokens"] == 90 and result.usage["input_tokens_details"] == {"cached_tokens": 6}
    assert result.prompt_version == PROMPT_VERSION + "-pages" == _provider(handler).prompt_version
    assert result.request_id is not None and result.model == "gpt-6-luna"
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    # the merged result is still accepted by the unchanged strict whole-document validation
    assert validate_payload(payload, 3).pages[2].page_number == 3


def test_requests_really_run_at_the_same_time():
    barrier = Barrier(3, timeout=5)

    def handler(request):
        barrier.wait()  # only passes when all three requests are in flight together
        return httpx.Response(200, json=_body(_page_payload()))

    assert _provider(handler).extract(_pdf(3), "application/pdf", 3).state == "succeeded"


def test_concurrency_is_bounded():
    lock, active, peak = Lock(), [0], [0]

    def handler(request):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        sleep(0.05)
        with lock:
            active[0] -= 1
        return httpx.Response(200, json=_body(_page_payload()))

    result = _provider(handler, page_concurrency=2).extract(_pdf(5), "application/pdf", 5)
    assert result.state == "succeeded" and peak[0] == 2


def test_one_failed_page_fails_the_run_skips_unstarted_pages_and_keeps_all_usage():
    calls = []

    def handler(request):
        _, _, number = _request_page(request)
        calls.append(number)
        if number == 1:
            return httpx.Response(200, json=_body(_page_payload(), status="incomplete"))
        return httpx.Response(200, json=_body(_page_payload()))

    result = _provider(handler, page_concurrency=1).extract(_pdf(3), "application/pdf", 3)
    assert calls == [1] and result.state == "incomplete" and result.error_code == "provider_incomplete"
    assert result.payload is None and result.usage["total_tokens"] == 30


def test_unknown_outcome_wins_and_in_flight_usage_is_still_counted():
    barrier = Barrier(2, timeout=5)

    def handler(request):
        _, _, number = _request_page(request)
        barrier.wait()
        if number == 1:
            return httpx.Response(200, json=_body(_page_payload()))
        return httpx.Response(503, json={"error": "sensitive source text"})

    result = _provider(handler, page_concurrency=2).extract(_pdf(2), "application/pdf", 2)
    assert result.state == "unknown_outcome" and result.error_code == "provider_server_outcome_unknown_no_retry"
    assert result.payload is None and result.usage["total_tokens"] == 30
    assert "sensitive" not in repr(result)


def test_a_page_that_fails_its_own_validation_fails_the_run_without_repair():
    broken = _page_payload()
    broken["rows"][0]["evidence"][0]["region_reference"] = "invented"

    def handler(request):
        _, _, number = _request_page(request)
        return httpx.Response(200, json=_body(broken if number == 2 else _page_payload()))

    result = _provider(handler, page_concurrency=3).extract(_pdf(3), "application/pdf", 3)
    assert result.state == "invalid_output" and result.error_code == "provider_payload_validation_failed"
    assert result.payload is None


def test_cross_page_line_stays_a_visible_unknown_row_with_a_warning_never_a_link():
    top = _page_payload()
    orphan = next(row for row in top["rows"] if row["row_id"] == "ambiguous-item")
    reference = orphan["evidence"][0]["region_reference"]
    for region in top["pages"][0]["regions"]:
        if region["region_reference"] == reference:
            region["bbox"] = {"x0": 0.1, "y0": 0.01, "x1": 0.9, "y1": 0.04}

    def handler(request):
        _, _, number = _request_page(request)
        return httpx.Response(200, json=_body(top if number == 2 else _page_payload()))

    result = _provider(handler).extract(_pdf(2), "application/pdf", 2)
    assert result.state == "succeeded"
    warnings = result.payload.warnings
    assert warnings == ("page_2_starts_with_an_unlinked_line_that_may_continue_the_previous_page",)
    kept = next(row for row in result.payload.rows if row.row_id == "p2-ambiguous-item")
    assert kept.row_kind == "unknown" and kept.continuation_of is None and kept.uncertainty
    assert result.payload.partial


def test_a_cross_page_continuation_link_cannot_validate_and_is_a_reported_failure():
    # A model answer that points a continuation at a row on another page must not slip through.
    first, second = _page_payload(), _page_payload()
    second["rows"][1]["continuation_of"] = "item-101"  # same text, but on page 1 once merged
    merged = merge_page_payloads([validate_payload(first, 1), validate_payload(second, 1)])
    for row in merged["rows"]:
        if row["row_id"] == "p2-description-cont-101":
            row["continuation_of"] = "p1-item-101"
    with pytest.raises(ValidationError):
        validate_payload(merged, 2)


def test_merged_validation_failure_is_reported_with_its_own_code_and_all_usage():
    long_id = "x" * 118  # valid alone (max 120), invalid once the page prefix is added
    page = json.loads(json.dumps(_page_payload()).replace("item-101", long_id))
    result = _provider(lambda request: httpx.Response(200, json=_body(page))).extract(_pdf(2), "application/pdf", 2)
    assert result.state == "invalid_output" and result.error_code == "merged_payload_validation_failed"
    assert result.payload is None and result.usage["total_tokens"] == 60


def test_document_fields_come_from_the_first_page_that_has_them_and_disagreement_is_flagged():
    header, plain = _page_payload(), _page_payload()
    absent = deepcopy(plain["rows"][1]["quantity"])
    assert absent["state"] in ("not_present", "not_applicable")
    plain["document_number"] = absent
    plain["document_number"]["state"] = "not_present"
    result = _provider(lambda request: httpx.Response(200, json=_body(
        plain if _request_page(request)[2] == 1 else header))).extract(_pdf(2), "application/pdf", 2)
    assert result.state == "succeeded"
    assert result.payload.document_number.state == "observed"
    assert {ref.page_number for ref in result.payload.document_number.evidence} == {2}
    assert result.payload.warnings == ()
    other = deepcopy(header)
    other["document_number"]["raw_value"] = "DIFFERENT-1"
    result = _provider(lambda request: httpx.Response(200, json=_body(
        other if _request_page(request)[2] == 2 else header))).extract(_pdf(2), "application/pdf", 2)
    assert result.payload.warnings == ("pages_disagree_on_document_number",)


def test_whole_document_mode_is_unchanged_and_one_page_or_image_sources_use_one_request():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_body(_page_payload()))

    whole = OpenAIProvider(api_key="offline-placeholder", enabled=True, transport=httpx.MockTransport(handler))
    assert whole.split_pages is False and whole.prompt_version == PROMPT_VERSION
    assert whole.extract(_pdf(1), "application/pdf", 1).state == "succeeded"
    assert "reasoning" not in calls[0] and calls[0]["input"][0]["content"][1]["text"] == "Source page count: 1."
    assert _provider(handler).extract(_pdf(1), "application/pdf", 1).state == "succeeded"
    assert len(calls) == 2
    pixmap = pymupdf.open(stream=_pdf(1), filetype="pdf")[0].get_pixmap(dpi=40).tobytes("png")
    assert _provider(handler).extract(pixmap, "image/png", 1).state == "succeeded" and len(calls) == 3
    assert _provider(handler, split_pages=False).extract(_pdf(3), "application/pdf", 3).state == "invalid_output"
    assert len(calls) == 4 and calls[3]["input"][0]["content"][1]["text"] == "Source page count: 3."


def test_unsplittable_or_oversized_pdfs_fail_before_any_request():
    def forbidden(request):
        raise AssertionError("no request may be sent")

    provider = _provider(forbidden)
    assert provider.extract(_pdf(3), "application/pdf", 4).error_code == "pdf_split_failed"
    assert provider.extract(b"%PDF-1.7 not a pdf", "application/pdf", 2).error_code == "pdf_split_failed"
    assert provider.extract(_pdf(MAX_SPLIT_PAGES + 1), "application/pdf",
                            MAX_SPLIT_PAGES + 1).error_code == "page_limit_exceeded"


@pytest.mark.parametrize("split", [False, True])
def test_reasoning_effort_is_sent_only_when_set(split):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_body(_page_payload()))

    pages = 2 if split else 1
    for effort in (None, "low"):
        bodies.clear()
        _provider(handler, split_pages=split, reasoning_effort=effort).extract(_pdf(pages), "application/pdf", pages)
        assert len(bodies) == (2 if split else 1)
        for body in bodies:
            assert ("reasoning" in body) is (effort is not None)
            assert body.get("reasoning", {"effort": "low"}) == {"effort": "low"}
    with pytest.raises(ValueError):
        OpenAIProvider(api_key="offline-placeholder", enabled=True, reasoning_effort="turbo")


def test_settings_defaults_and_validation(monkeypatch):
    settings = Settings(_env_file=None)
    assert (settings.provider_split_pages, settings.provider_page_concurrency,
            settings.provider_reasoning_effort) == (True, 6, None)
    monkeypatch.setenv("PO_BACKEND_PROVIDER_REASONING_EFFORT", "low")
    monkeypatch.setenv("PO_BACKEND_PROVIDER_SPLIT_PAGES", "false")
    monkeypatch.setenv("PO_BACKEND_PROVIDER_PAGE_CONCURRENCY", "3")
    tuned = Settings(_env_file=None)
    assert (tuned.provider_split_pages, tuned.provider_page_concurrency,
            tuned.provider_reasoning_effort) == (False, 3, "low")
    monkeypatch.setenv("PO_BACKEND_PROVIDER_REASONING_EFFORT", "turbo")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
