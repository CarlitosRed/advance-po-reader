"""Annotation truth boundaries, source identity and irreversible raw evidence."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from pypdf import PdfWriter

from benchmark_vision import load_gold, score_document
from collect_review import main
from po_reader.review_collection import (PAGE_HASH_METHOD, approval_template, approve_record, build_queue,
                                         collect_queue, export_gold, read_json, sha256, source_page_hashes, write_json)


def pdf_bytes(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def source_line(page=1):
    return dict(page=page, identifiers=[dict(raw_value=" 00123-A ", printed_label=" VEND-PART# ", role="vendor_product_code")],
                quantity_raw=" 02.00 ", quantity="2", uom_raw=" ea ", uom="EA", kind="product",
                description="Raw  description  spacing", match=dict(status="matched", product_id="CANONICAL-123"))


def report(raw):
    return dict(schema_version=1, provider="ollama", model="example-vlm", model_digest="sha256:" + "c" * 64,
                inventory=[dict(sha256=sha256(raw), filename="source.pdf", archive_entry="source.pdf",
                                page_fingerprints=source_page_hashes(raw), pages=[dict(page=1), dict(page=2)])],
                results=[dict(sha256=sha256(raw), filename="source.pdf", archive_entry="source.pdf", prediction=dict(
                    sha256=sha256(raw), lines=[source_line()], order_number=dict(value=" 00042 "),
                    extraction=dict(provider="ollama", model="example-vlm", pages=[dict(page=1, image_sha256="d" * 64,
                    lines=[dict(quantity_raw=" 02.00 ", description_raw="Raw  description  spacing")])],
                    failures=[dict(page=2, error="Provider unavailable")])))] )


def approved_values(record):
    form = approval_template(record)
    form["pages_reviewed"] = [dict(page=p["page"], source_page_sha256=p["source_page_sha256"], source_page_hash_method=PAGE_HASH_METHOD)
                               for p in record["pages"]]
    form["expected"] = dict(po_number="00042", lines=[dict(page=1,
                            identifiers=[dict(raw_value=" 00123-A ", printed_label=" VEND-PART# ", role="vendor_product_code")],
                            quantity=" 02.00 ", uom=" ea ", expected_catalog_product_id=None)])
    return form


class ReviewCollectionTests(unittest.TestCase):
    def setUp(self):
        self.raw = pdf_bytes()
        self.payload = report(self.raw)
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, payload=None):
        paths = collect_queue(payload or self.payload, self.directory / "queue", run_id="run-one")
        return paths[0], read_json(paths[0])

    def approve(self, path, record, form=None):
        return approve_record(path, form or approved_values(record), reviewer="Human Reviewer", source_pdf=self.raw)

    def test_unreviewed_predictions_cannot_be_exported_as_gold(self):
        path, record = self.collect()
        self.assertEqual(record["review_status"], "pending")
        self.assertIsNone(record["corrected_expected"]["po_number"])
        self.assertIsNone(record["corrected_expected"]["lines"])
        self.assertIsNone(record["human_review"])
        with self.assertRaisesRegex(ValueError, "Unreviewed predictions"):
            export_gold([record])
        form = approval_template(record)
        self.assertEqual(form["pages_reviewed"], [])
        self.assertIsNone(form["expected"]["lines"])
        with self.assertRaises(ValueError):
            self.approve(path, record, form)

    def test_original_document_and_page_hash_mismatch_are_rejected(self):
        path, record = self.collect()
        form = approved_values(record)
        with self.assertRaisesRegex(ValueError, "Source PDF SHA-256"):
            approve_record(path, form, reviewer="Human Reviewer", source_pdf=self.raw + b"changed")
        form["document_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Approval document SHA-256"):
            self.approve(path, record, form)
        form = approved_values(record)
        form["pages_reviewed"][0]["source_page_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Reviewed source page SHA-256"):
            self.approve(path, record, form)
        record["pages"][0]["source_page_sha256"] = "f" * 64
        write_json(path, record)
        with self.assertRaisesRegex(ValueError, "Source page SHA-256"):
            self.approve(path, record)

    def test_exact_strings_and_raw_observations_are_preserved(self):
        path, record = self.collect()
        raw_prediction = deepcopy(record["raw_prediction"])
        updated = self.approve(path, record)
        self.assertEqual(updated["raw_prediction"], raw_prediction)
        self.assertEqual(updated["pages"][0]["raw_observations"][0]["lines"][0]["quantity_raw"], " 02.00 ")
        self.assertEqual(updated["corrected_expected"]["lines"][0]["identifiers"][0]["raw_value"], " 00123-A ")
        self.assertEqual(updated["corrected_expected"]["lines"][0]["quantity"], " 02.00 ")
        self.assertEqual(updated["corrected_expected"]["lines"][0]["uom"], " ea ")
        labels = export_gold([updated])
        target = self.directory / "approved.json"
        write_json(target, labels)
        loaded = load_gold(target)
        score = score_document(loaded[sha256(self.raw)], dict(order_number=dict(value="00042"), lines=[source_line()]))
        self.assertTrue(score["scored"])
        self.assertEqual(score["exact_id_quantity_uom_rows"], 1)
        self.assertTrue(score["complete_document_correct"])
        self.assertEqual(labels["documents"][0]["evidence"]["reviewer"], "Human Reviewer")

    def test_existing_approved_corrections_survive_collection_rerun(self):
        path, record = self.collect()
        updated = self.approve(path, record)
        before = path.read_bytes()
        paths = collect_queue(self.payload, self.directory / "queue", run_id="run-one")
        self.assertEqual(paths, [path])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(read_json(path)["corrected_expected"], updated["corrected_expected"])
        changed = deepcopy(self.payload)
        changed["results"][0]["prediction"]["lines"][0]["quantity_raw"] = "3"
        with self.assertRaisesRegex(ValueError, "different observations"):
            collect_queue(changed, self.directory / "queue", run_id="run-one")
        self.assertEqual(path.read_bytes(), before)
        form = approved_values(record)
        form["expected"]["lines"][0]["quantity"] = "3"
        with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
            self.approve(path, record, form)
        self.assertEqual(path.read_bytes(), before)

    def test_review_requires_all_pages_even_when_extraction_failed(self):
        path, record = self.collect()
        self.assertEqual(record["pages"][1]["failures"][0]["error"], "Provider unavailable")
        form = approved_values(record)
        form["pages_reviewed"].pop()
        with self.assertRaisesRegex(ValueError, "Every source page"):
            self.approve(path, record, form)
        form = approved_values(record)
        form["pages_reviewed"][1] = deepcopy(form["pages_reviewed"][0])
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.approve(path, record, form)

    def test_reviewer_roles_and_quantity_strings_are_validated(self):
        path, record = self.collect()
        with self.assertRaisesRegex(ValueError, "reviewer name"):
            approve_record(path, approved_values(record), reviewer=" ", source_pdf=self.raw)
        for value in (2, True, "NaN", "-1", "two"):
            with self.subTest(quantity=value):
                form = approved_values(record)
                form["expected"]["lines"][0]["quantity"] = value
                with self.assertRaises(ValueError):
                    self.approve(path, record, form)
        form = approved_values(record)
        form["expected"]["lines"][0]["identifiers"][0]["role"] = "catalog_product"
        with self.assertRaisesRegex(ValueError, "role is invalid"):
            self.approve(path, record, form)

    def test_reader_session_is_bound_to_original_pdf(self):
        session = deepcopy(self.payload["results"][0]["prediction"])
        session.update(session_id="session-one", filename="source.pdf", pages=[dict(page=1), dict(page=2)])
        pending = build_queue(session)[0]
        self.assertIsNone(pending["pages"][0]["source_page_sha256"])
        bound = build_queue(session, source_loader=lambda doc: self.raw)[0]
        self.assertEqual(pending["record_id"], bound["record_id"])
        self.assertEqual(bound["pages"][0]["source_page_sha256"], source_page_hashes(self.raw)[0])
        with self.assertRaisesRegex(ValueError, "Source PDF SHA-256"):
            build_queue(session, source_loader=lambda doc: b"wrong bytes")

    def test_failed_document_remains_in_review_queue(self):
        payload = deepcopy(self.payload)
        payload["results"][0].pop("prediction")
        payload["results"][0]["error"] = "Service not available"
        record = build_queue(payload)[0]
        self.assertEqual(record["run_error"], "Service not available")
        self.assertEqual(len(record["pages"]), 2)
        self.assertEqual(record["raw_prediction"], {})
        self.assertEqual(record["review_status"], "pending")

    def test_modified_raw_observations_cannot_be_approved(self):
        path, record = self.collect()
        record["raw_prediction"]["lines"][0]["quantity_raw"] = "999"
        write_json(path, record)
        with self.assertRaisesRegex(ValueError, "raw prediction was changed"):
            self.approve(path, record)
        path, record = self.collect_after_delete(path)
        record["pages"][0]["raw_extracted_lines"][0]["quantity_raw"] = "999"
        write_json(path, record)
        with self.assertRaisesRegex(ValueError, "page observations were changed"):
            self.approve(path, record)

    def collect_after_delete(self, path):
        path.unlink()
        return self.collect()

    def test_cli_collection_and_export_cannot_escape_private_output(self):
        result = self.directory / "report.json"
        write_json(result, self.payload)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(["collect", "--result", str(result), "--output-dir", str(self.directory / "outside")])
        self.assertEqual(stopped.exception.code, 2)

    def test_cli_end_to_end_with_named_human_correction(self):
        result = self.directory / "report.json"
        write_json(result, self.payload)
        with patch("collect_review.ROOT", self.directory), patch("collect_review.PRIVATE", self.directory / "output/review-data"), redirect_stdout(io.StringIO()):
            queue = self.directory / "output/review-data/queue"
            self.assertEqual(main(["collect", "--result", str(result), "--output-dir", str(queue), "--run-id", "cli-run"]), 0)
            record_path = next(queue.glob("*.json"))
            record = read_json(record_path)
            form_path = self.directory / "correction.json"
            write_json(form_path, approved_values(record))
            source_path = self.directory / "source.pdf"
            source_path.write_bytes(self.raw)
            self.assertEqual(main(["approve", "--record", str(record_path), "--approval-file", str(form_path),
                                   "--reviewer", "Human Reviewer", "--source-pdf", str(source_path)]), 0)
            target = self.directory / "output/review-data/approved-labels.json"
            self.assertEqual(main(["export", "--record", str(record_path), "--output", str(target)]), 0)
            self.assertEqual(len(read_json(target)["documents"]), 1)


if __name__ == "__main__":
    unittest.main()
