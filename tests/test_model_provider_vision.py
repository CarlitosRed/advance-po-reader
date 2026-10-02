import base64
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation

from po_reader import service
from po_reader.catalog import ROOT, load_catalog
from po_reader.engine import read_pages
from po_reader.model_provider import (
    COMPARISON_SCHEMA, PAGE_EXTRACTION_SCHEMA, CascadeProvider, OllamaProvider, OpenAIProvider,
    ProviderError, build_cascade_provider, validate_schema,
)
from po_reader.rendering import RegionRenderer
from po_reader.vision import _contains, _line, analyze_vision, parse_observed_quantity


def observation(value=None, label=None):
    return dict(value=value, printed_label=label, status="missing" if value is None else "observed",
                evidence_text=value)


def observed_line(**changes):
    line = dict(source_line_label="1", identifiers=[dict(
        raw_value="31334000", printed_label="MPN", role="manufacturer_part_number", status="observed")],
        description_raw="EASIWAY 3 SECTION LOFT LADDER", quantity_raw="15.00", uom_raw="EACH",
        unit_price_raw="63.99", amount_raw="959.85", kind="product", attributes=[],
        evidence_text="31334000 EASIWAY 3 SECTION LOFT LADDER 15.00 EACH 63.99 959.85", uncertainties=[])
    line.update(changes)
    return line


def extracted_page(lines=None):
    record = dict(document_type="purchase_order", po_number=observation("DEMO-1042", "Order No."),
                  po_date=observation("31 July 2026", "Document Date"), buyer=observation("Demo Buyer"),
                  supplier=observation("Werner UK Sales & Dist Ltd"), currency=observation("GBP"),
                  shipping={key: observation() for key in ("company", "address", "postcode", "country", "phone")},
                  billing={key: observation() for key in ("company", "address", "postcode", "country", "phone")},
                  totals=[], additional_fields=[], notes=[], lines=[observed_line()] if lines is None else lines)
    private_header = ROOT / 'data/private-tests/vision-header.json'
    if private_header.is_file():
        header = json.loads(private_header.read_text(encoding='utf-8'))
        record.update(header)
    validate_schema(record, PAGE_EXTRACTION_SCHEMA)
    return record


class MockVisionProvider:
    name = "mock"
    model = "mock-vision"

    def __init__(self, record=None, failures=None):
        self.record = record or extracted_page()
        self.failures = failures or set()
        self.usage = []
        self.page_calls = []

    def extract_page(self, image, page_number, native_text=""):
        self.page_calls.append((image, page_number, native_text))
        if page_number in self.failures:
            raise ProviderError("Incomplete model output")
        return copy.deepcopy(self.record)

    def compare(self, line, candidates):
        selected = next((candidate["product_id"] for candidate in candidates
                         if candidate["product_id"] == line["supplier_id"]), None)
        return dict(selected_product_id=selected, description_relationship="compatible",
                    attribute_conflicts=[], reason="Compatible product description.")


def completed_response(value):
    return dict(status="completed", output=[dict(type="message", content=[dict(type="output_text", text=json.dumps(value))])])


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.provider = OpenAIProvider("mock-vision", api_key="test-key")
        self.comparison = dict(selected_product_id="0076-76", description_relationship="compatible",
                               attribute_conflicts=[], reason="Observed identifier and compatible name.")

    def test_openai_without_api_key_fails_before_http(self):
        with patch.dict(os.environ, {}, clear=True), patch("po_reader.model_provider._request_json") as request:
            with self.assertRaisesRegex(ProviderError, "OPENAI_API_KEY"):
                OpenAIProvider("mock-vision")
            request.assert_not_called()

    def test_structured_request_preserves_codes_and_sends_page_image(self):
        record = extracted_page([observed_line(identifiers=[dict(
            raw_value="0076-76", printed_label="Product Code", role="vendor_product_code", status="observed")], uom_raw=None)])
        with patch("po_reader.model_provider._request_json", return_value=completed_response(record)) as request:
            result = self.provider.extract_page(b"page-png", 1, "native observation")
        self.assertEqual(result["lines"][0]["identifiers"][0]["raw_value"], "0076-76")
        self.assertIsNone(result["lines"][0]["uom_raw"])
        payload = request.call_args.args[1]
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        image = payload["input"][1]["content"][1]["image_url"]
        self.assertEqual(base64.b64decode(image.split(",", 1)[1]), b"page-png")

    def test_refusal_incomplete_and_missing_output_raise_provider_error(self):
        responses = [dict(status="incomplete", output=[]),
                     dict(status="completed", output=[dict(content=[dict(type="refusal", refusal="declined")])]),
                     dict(status="completed", output=[])]
        for response in responses:
            with self.subTest(response=response), patch("po_reader.model_provider._request_json", return_value=response):
                with self.assertRaises(ProviderError):
                    self.provider.compare({}, [])

    def test_invalid_json_schema_enum_and_extra_fields_fail_closed(self):
        values = [dict(self.comparison, attribute_conflicts="none"),
                  dict(self.comparison, description_relationship="probably"),
                  dict(self.comparison, confidence=0.99),
                  {key: value for key, value in self.comparison.items() if key != "selected_product_id"}]
        for value in values:
            with self.subTest(value=value), patch("po_reader.model_provider._request_json", return_value=completed_response(value)):
                with self.assertRaises(ProviderError):
                    self.provider.compare({}, [])
        response = completed_response(self.comparison)
        response["output"][0]["content"][0]["text"] = '{"selected_product_id":'
        with patch("po_reader.model_provider._request_json", return_value=response):
            with self.assertRaises(ProviderError):
                self.provider.compare({}, [])

    def test_malformed_response_envelopes_raise_provider_error(self):
        for output in (None, {}, [None], [dict(content=None)], [dict(content=[None])]):
            with self.subTest(output=output), patch("po_reader.model_provider._request_json", return_value=dict(status="completed", output=output)):
                with self.assertRaises(ProviderError):
                    self.provider.compare({}, [])

    def test_local_output_schema_and_completion_are_validated(self):
        provider = OllamaProvider("mock-local")
        responses = [dict(done=False, message=dict(content=json.dumps(self.comparison))),
                     dict(done=True, done_reason="length", message=dict(content=json.dumps(self.comparison))),
                     dict(done=True, done_reason="stop", message=None),
                     dict(done=True, done_reason="stop", message=dict(content="not JSON"))]
        for response in responses:
            with self.subTest(response=response), patch("po_reader.model_provider._request_json", return_value=response):
                with self.assertRaises(ProviderError):
                    provider.compare({}, [])
        with patch("po_reader.model_provider._request_json", return_value=dict(done=True, done_reason="stop", message=dict(content=json.dumps(self.comparison)))):
            self.assertEqual(provider.compare({}, []), self.comparison)

    def test_cascade_defaults_and_distinct_visual_text_requests(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = build_cascade_provider()
        self.assertEqual(provider.model, "qwen3-vl:8b-instruct")
        self.assertEqual(provider.adjudicator.model, "gpt-oss:20b")
        responses = [dict(done=True, done_reason="stop", message=dict(content=json.dumps(extracted_page()))),
                     dict(done=True, done_reason="stop", message=dict(content=json.dumps(self.comparison)))]
        with patch("po_reader.model_provider._request_json", side_effect=responses) as request:
            provider.extract_page(b"png-page", 1, "native text")
            provider.compare({}, [])
        visual, text = [call.args[1] for call in request.call_args_list]
        self.assertEqual(visual["model"], "qwen3-vl:8b-instruct")
        self.assertEqual(base64.b64decode(visual["messages"][1]["images"][0]), b"png-page")
        self.assertFalse(visual["think"])
        self.assertEqual(text["model"], "gpt-oss:20b")
        self.assertEqual(text["think"], "low")
        self.assertNotIn("images", text["messages"][1])
        self.assertEqual(provider.stage_counts()["extraction"]["used"], 1)
        self.assertEqual(provider.stage_counts()["adjudication"]["used"], 1)
        self.assertFalse(provider.metadata["training_enabled"])

    def test_model_digest_resolution_and_absent_stage_are_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = build_cascade_provider()
        installed = [dict(name="qwen3-vl:8b-instruct", digest="sha256:extractor")]
        with patch("po_reader.model_provider._local_model_inventory", return_value=installed) as inventory:
            provider.refresh_model_identities()
            provider.refresh_model_identities()
        inventory.assert_called_once()
        models = provider.metadata["models"]
        self.assertEqual(models["extractor"]["digest"], "sha256:extractor")
        self.assertEqual(models["adjudicator"]["digest_status"], "model_not_installed")
        self.assertIsNone(models["adjudicator"]["digest"])
        self.assertEqual(provider.metadata["stages"]["reranking"]["status"], "unavailable")

    def test_failed_adjudication_is_counted_without_claiming_success(self):
        provider = CascadeProvider(MockVisionProvider(), OllamaProvider("gpt-oss:20b"))
        with patch("po_reader.model_provider._request_json", side_effect=ProviderError("unavailable")):
            with self.assertRaises(ProviderError):
                provider.compare({}, [])
        counts = provider.stage_counts()["adjudication"]
        self.assertEqual(counts, dict(used=0, skipped=0, failed=1))
        self.assertEqual(provider.usage[0]["model"], "gpt-oss:20b")


class ObservedQuantityTests(unittest.TestCase):
    def test_exact_observed_unit_suffix_parses_without_changing_numeric_spelling(self):
        for raw, unit, expected in (("6ea", "EA", "6"), ("10 EA", " ea ", "10"),
                                    ("006.00ea", "EA", "006.00"), (" 06.50  e a ", "E A", "06.50"),
                                    ("0006.00", "EACH", "0006.00"), ("2PK", "PK", "2")):
            with self.subTest(raw=raw, unit=unit):
                self.assertEqual(parse_observed_quantity(raw, unit), expected)

    def test_absent_mismatched_and_nonquantity_strings_do_not_parse(self):
        for raw, unit in (("6ea", None), ("6", None), ("6ea", ""), ("6ea", "EACH"),
                          ("6pk", "EA"), ("6each", "EA"), ("1e3ea", "EA"),
                          ("-6ea", "EA"), ("+6ea", "EA"), ("0ea", "EA"),
                          ("6,000ea", "EA"), ("$6.00ea", "EA"), ("6ea @ $1.00", "EA"),
                          ("price 6.00", "EA"), ("6ea EA", "EA"), ("6.0.0ea", "EA"),
                          ("EA6", "EA"), (True, "EA")):
            with self.subTest(raw=raw, unit=unit):
                self.assertIsNone(parse_observed_quantity(raw, unit))


class VisionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'data/originals/Purchase Order SPS0072601105.pdf').is_file():
            raise unittest.SkipTest('Private PDF fixture unavailable')
        cls.raw = (ROOT / 'data/originals/Purchase Order SPS0072601105.pdf').read_bytes()
        cls.image = RegionRenderer(budget_bytes=0).render(cls.raw, 1, scale=0.5)
        cls.catalog = load_catalog()
        cls.native_page = read_pages(cls.raw)[0]

    def test_real_pdf_native_row_corroboration_and_model_match(self):
        provider = MockVisionProvider()
        document = analyze_vision(self.raw, "sample.pdf", self.catalog, provider)
        line = document["lines"][0]
        self.assertEqual(document["status"], "extracted")
        self.assertEqual(line["source_validation"]["status"], "corroborated")
        self.assertEqual(line["match"]["status"], "matched")
        self.assertEqual(line["match"]["product_id"], "31334000")
        self.assertEqual(line["quantity"], "15.00")
        self.assertEqual(line["uom"], "EACH")
        self.assertTrue(any(e["origin"] == "native_row" and e["bbox"] for e in line["evidence"]))
        self.assertTrue(provider.page_calls[0][0].startswith(b"\x89PNG"))

    def test_cascade_document_records_stages_and_rendering_without_adjudication(self):
        extractor = MockVisionProvider()
        adjudicator = OllamaProvider("gpt-oss:20b")
        provider = CascadeProvider(extractor, adjudicator)
        with patch("po_reader.model_provider._local_model_inventory", return_value=[]), \
                patch("po_reader.model_provider._request_json") as request:
            first = analyze_vision(self.raw, "sample.pdf", self.catalog, provider)
            second = analyze_vision(self.raw, "sample.pdf", self.catalog, provider)
        request.assert_not_called()
        for document in (first, second):
            extraction = document["extraction"]
            self.assertEqual(extraction["cascade"]["stage_counts"]["extraction"]["used"], 1)
            self.assertEqual(extraction["cascade"]["stage_counts"]["adjudication"]["skipped"], 1)
            self.assertEqual(extraction["cascade"]["stage_counts"]["reranking"]["skipped"], 1)
            self.assertEqual(document["lines"][0]["match"]["status"], "matched")
            self.assertEqual(document["lines"][0]["comparison_method"], "deterministic_exact_description")
            self.assertEqual(extraction["rendering"]["requested_pdf_dpi"], 216)
            self.assertLessEqual(extraction["rendering"]["page_settings"][0]["effective_dpi"], 216)
            self.assertEqual(extraction["pages"][0]["lines"][0]["identifiers"][0]["raw_value"], "31334000")
        self.assertEqual(provider.stage_counts()["extraction"]["used"], 2)

    def test_missing_unit_stays_missing_and_requires_review(self):
        provider = MockVisionProvider(extracted_page([observed_line(uom_raw=None)]))
        document = analyze_vision(self.raw, "sample.pdf", self.catalog, provider)
        line = document["lines"][0]
        self.assertIsNone(line["uom_raw"])
        self.assertIsNone(line["uom"])
        self.assertEqual(line["match"]["status"], "review_needed")
        self.assertIn("invalid_or_unconfirmed_unit", line["match"]["validation_errors"])

    def test_combined_quantity_literal_corroborates_one_quantity_unit_pair(self):
        page = copy.deepcopy(self.native_page)
        page["words"] = []
        texts = ["31334000", "EASIWAY", "LADDER", "006.00ea"]
        for index, text in enumerate(texts):
            page["words"].append(dict(text=text, x0=index * 80, x1=index * 80 + 60, top=100, bottom=110))
        page["independent_text"] = " ".join(texts)
        observed = observed_line(quantity_raw="006.00ea", uom_raw="EA", evidence_text=" ".join(texts))
        original = copy.deepcopy(observed)
        line = _line(observed, page, 1)
        self.assertEqual(line["quantity"], "006.00")
        self.assertEqual(line["quantity_raw"], "006.00ea")
        self.assertEqual(line["uom_raw"], "EA")
        self.assertEqual(line["source_validation"]["status"], "corroborated")
        self.assertEqual(line["quantity_parsing"]["method"], "explicit_number_with_observed_unit_suffix")
        self.assertFalse(line["quantity_parsing"]["unit_conversion"])
        self.assertEqual(observed, original)
        line["identifiers"][0]["role"] = "unknown"
        self.assertEqual(observed, original)

    def test_combined_quantity_preserves_source_disagreement_and_role_guards(self):
        for independent, role, expected in (("OTHER-ID EASIWAY LADDER 6ea", "manufacturer_part_number", "disagreement"),
                                           ("31334000 EASIWAY LADDER 6ea", "unknown", "vision_only")):
            with self.subTest(role=role):
                page = copy.deepcopy(self.native_page)
                texts = ["31334000", "EASIWAY", "LADDER", "6ea"]
                page["words"] = [dict(text=text, x0=index * 80, x1=index * 80 + 60, top=100, bottom=110)
                                 for index, text in enumerate(texts)]
                page["independent_text"] = independent
                line = _line(observed_line(quantity_raw="6ea", uom_raw="EA", evidence_text=" ".join(texts),
                                           identifiers=[dict(raw_value="31334000", printed_label="MPN", role=role, status="observed")]), page, 1)
                self.assertEqual(line["quantity"], "6")
                self.assertEqual(line["source_validation"]["status"], expected)

    def test_invented_po_with_absent_or_forged_quote_requires_document_review(self):
        for quote in (None, "Order No. INVENTED-PO-999"):
            with self.subTest(quote=quote):
                record = extracted_page()
                record["po_number"] = dict(value="INVENTED-PO-999", printed_label="Order No.",
                                             status="observed", evidence_text=quote)
                document = analyze_vision(self.raw, "sample.pdf", self.catalog, MockVisionProvider(record))
                self.assertEqual(document["order_number"]["status"], "review_needed")
                self.assertNotEqual(document["order_number"]["source_validation"]["status"], "corroborated")
                self.assertTrue(all(line["match"]["status"] == "review_needed" for line in document["lines"]))

    def test_correct_po_value_still_requires_its_number_in_quoted_evidence(self):
        record = extracted_page()
        record["po_number"]["evidence_text"] = "Order No. unrelated-reference"
        document = analyze_vision(self.raw, "sample.pdf", self.catalog, MockVisionProvider(record))
        self.assertEqual(document["order_number"]["value"], extracted_page()["po_number"]["value"])
        self.assertEqual(document["order_number"]["status"], "review_needed")
        self.assertEqual(document["lines"][0]["match"]["status"], "review_needed")

    def test_po_cover_does_not_approve_invoice_page_rows(self):
        writer = PdfWriter()
        writer.add_page(PdfReader(io.BytesIO(self.raw)).pages[0])
        second = writer.add_page(PdfReader(io.BytesIO(self.raw)).pages[0])
        # Shift the content so this is a different rendered page, avoiding the
        # duplicate-page guard as an accidental reason for this test to pass.
        second.add_transformation(Transformation().translate(tx=10, ty=0))
        buffer = io.BytesIO()
        writer.write(buffer)
        provider = MockVisionProvider()
        original_extract = provider.extract_page
        provider.extract_page = lambda image, number, native="": dict(
            original_extract(image, number, native), document_type="invoice" if number == 2 else "purchase_order")
        document = analyze_vision(buffer.getvalue(), "combined-order-invoice.pdf", self.catalog, provider)
        self.assertNotEqual(document["extraction"]["pages"][0]["image_sha256"], document["extraction"]["pages"][1]["image_sha256"])
        self.assertEqual(document["order_number"]["status"], "extracted")
        self.assertEqual(document["lines"][0]["match"]["status"], "matched")
        self.assertEqual(document["lines"][1]["document_type"], "invoice")
        self.assertEqual(document["lines"][1]["match"]["status"], "review_needed")

    def test_large_pdf_sheet_preview_saves_complete_review_session(self):
        writer = PdfWriter()
        writer.add_blank_page(width=1190, height=1684)
        buffer = io.BytesIO()
        writer.write(buffer)
        raw = buffer.getvalue()
        with tempfile.TemporaryDirectory() as folder, patch.object(service, "SESSIONS", Path(folder)):
            document = service.create(raw, "large-sheet.pdf", render=True, provider=MockVisionProvider())
            stored = service.read(document["session_id"])
            self.assertEqual(stored["source_file"], "source.pdf")
            session = service.session_folder(document["session_id"])
            self.assertEqual((session / "source.pdf").read_bytes(), raw)
            self.assertEqual(stored["filename"], "large-sheet.pdf")
            with Image.open(session / "page-1.png") as preview:
                self.assertLessEqual(preview.width * preview.height, 4_000_000)

    def test_native_corroboration_requires_exact_code_tokens(self):
        self.assertTrue(_contains("(0076-76) D1540-2", "0076-76"))
        self.assertFalse(_contains("0076-76", "76-76"))
        self.assertFalse(_contains("D1540-2", "1540"))
        self.assertFalse(_contains("31334000", "3133400"))
        line = _line(observed_line(identifiers=[dict(raw_value="3133400", printed_label="MPN",
                                                   role="manufacturer_part_number", status="observed")],
                                   evidence_text="3133400 EASIWAY 3 SECTION LOFT LADDER 15.00 EACH"), self.native_page, 1)
        self.assertEqual(line["source_validation"]["status"], "vision_only")

    def test_code_elsewhere_on_page_does_not_corroborate_product_row(self):
        page = copy.deepcopy(self.native_page)
        for word in page["words"]:
            if word["text"] == "31334000":
                word["top"] = 20
                word["bottom"] = 30
        line = _line(observed_line(), page, 1)
        self.assertNotEqual(line["source_validation"]["status"], "corroborated")

    def test_repeated_code_rows_cannot_assemble_a_false_row(self):
        # Code+description are on one native row, code+quantity/unit on another.
        # Combining these rows would confirm a product/quantity pairing never printed.
        page = copy.deepcopy(self.native_page)
        page["words"] = []
        for top, texts in ((100, ["31334000", "EASIWAY", "LADDER", "1", "EA"]),
                           (200, ["31334000", "OTHER", "ITEM", "15.00", "EACH"])):
            for index, text in enumerate(texts):
                page["words"].append(dict(text=text, x0=index * 80, x1=index * 80 + 60, top=top, bottom=top + 10))
        page["independent_text"] = "31334000 EASIWAY LADDER 1 EA\n31334000 OTHER ITEM 15.00 EACH"
        line = _line(observed_line(), page, 1)
        self.assertNotEqual(line["source_validation"]["status"], "corroborated")

    def test_line_number_is_not_treated_as_order_quantity(self):
        page = copy.deepcopy(self.native_page)
        page["words"] = []
        texts = ["1", "31334000", "EASIWAY", "LADDER", "15.00", "EACH"]
        for index, text in enumerate(texts):
            page["words"].append(dict(text=text, x0=index * 80, x1=index * 80 + 60, top=100, bottom=110))
        page["independent_text"] = " ".join(texts)
        line = _line(observed_line(quantity_raw="1", evidence_text="31334000 EASIWAY LADDER 1 EACH"), page, 1)
        self.assertEqual(line["source_validation"]["status"], "vision_only")

    def test_multiple_qualifying_native_rows_require_confirmation(self):
        page = copy.deepcopy(self.native_page)
        page["words"] = []
        texts = ["31334000", "EASIWAY", "LADDER", "15.00", "EACH"]
        for top in (100, 200):
            for index, text in enumerate(texts):
                page["words"].append(dict(text=text, x0=index * 80, x1=index * 80 + 60, top=top, bottom=top + 10))
        page["independent_text"] = " ".join(texts) + "\n" + " ".join(texts)
        line = _line(observed_line(), page, 1)
        self.assertEqual(line["source_validation"]["status"], "vision_only")

    def test_failed_page_makes_entire_document_partial_and_rows_review(self):
        writer = PdfWriter()
        writer.add_page(PdfReader(io.BytesIO(self.raw)).pages[0])
        writer.add_blank_page(width=595, height=842)
        buffer = io.BytesIO()
        writer.write(buffer)
        document = analyze_vision(buffer.getvalue(), "two-pages.pdf", self.catalog, MockVisionProvider(failures={2}))
        self.assertEqual(document["status"], "partial")
        self.assertEqual(document["extraction"]["failures"][0]["page"], 2)
        self.assertTrue(document["lines"])
        self.assertTrue(all(line["match"]["status"] == "review_needed" for line in document["lines"]))

    def test_duplicate_rendered_pages_and_duplicate_observed_rows_need_review(self):
        writer = PdfWriter()
        page = PdfReader(io.BytesIO(self.raw)).pages[0]
        writer.add_page(page)
        writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        document = analyze_vision(buffer.getvalue(), "duplicate-pages.pdf", self.catalog, MockVisionProvider())
        self.assertEqual(len(document["lines"]), 2)
        self.assertTrue(all(line["match"]["status"] == "review_needed" for line in document["lines"]))
        provider = MockVisionProvider(extracted_page([observed_line(), observed_line()]))
        document = analyze_vision(self.raw, "duplicate-rows.pdf", self.catalog, provider)
        self.assertEqual(len(document["lines"]), 2)
        self.assertTrue(all(line["match"]["status"] == "review_needed" for line in document["lines"]))

    def test_image_source_preservation_persistence_and_cart_confirmation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service, "SESSIONS", Path(folder)):
            document = service.create(self.image, "scan.png", render=True, provider=MockVisionProvider())
            stored = service.read(document["session_id"])
            self.assertEqual(stored["source_type"], "image")
            self.assertEqual(stored["source_file"], "source.png")
            self.assertEqual((service.session_folder(document["session_id"]) / "source.png").read_bytes(), self.image)
            self.assertTrue((service.session_folder(document["session_id"]) / "page-1.png").is_file())
            self.assertEqual(stored["lines"][0]["match"]["status"], "review_needed")
            request = dict(session_id=document["session_id"], line_id="line-1", product_id="31334000", quantity="15.00", uom="EACH")
            with self.assertRaises(ValueError):
                service.cart_change(request)
            updated = service.cart_change(dict(request, confirmed=True))
            self.assertEqual(updated["cart"][0]["resolution"], "user_confirmed")
            with self.assertRaises(ValueError):
                service.cart_change(dict(request, confirmed=True, product_id="99999999"))

    def test_verified_pdf_cart_entry_cannot_silently_change_quantity(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service, "SESSIONS", Path(folder)):
            document = service.create(self.raw, "sample.pdf", provider=MockVisionProvider())
            request = dict(session_id=document["session_id"], line_id="line-1", product_id="31334000", quantity="15.00", uom="EACH")
            updated = service.cart_change(request)
            self.assertEqual(updated["cart"][0]["resolution"], "vision_catalog_match")
            with self.assertRaises(ValueError):
                service.cart_change(dict(request, quantity="16"))
            self.assertEqual(service.read(document["session_id"])["cart"][0]["quantity"], "15.00")


if __name__ == "__main__":
    unittest.main()
