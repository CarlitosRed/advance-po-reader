"""Check evaluation truth boundaries, duplicate grouping, and ZIP handling."""
import io
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from benchmark_vision import gold_template, group_duplicates, load_gold, main, read_archive, score_document, summarize_scores


def row(code="00123-A", quantity="2", unit="EA", role="vendor_product_code"):
    return dict(identifiers=[dict(raw_value=code, role=role, printed_label="Part Number")],
                quantity=quantity, uom=unit, kind="product")


def gold(lines, po="00042"):
    return dict(review_status="visually_verified", expected=dict(po_number=po, lines=lines))


class BenchmarkTruthTests(unittest.TestCase):
    def test_unverified_template_cannot_create_accuracy(self):
        doc = dict(filename="sample.pdf", archive_entry="Full Data Set/sample.pdf", sha256="a" * 64,
                   leakage_group="leakage-001")
        label = gold_template([doc])["documents"][0]
        self.assertIsNone(label["expected"]["lines"])
        self.assertIsNone(label["expected"]["po_number"])
        self.assertFalse(score_document(label, dict(lines=[row()]))["scored"])

    def test_ids_preserve_leading_zero_and_suffix(self):
        label = gold([row()])
        for altered in ("123-A", "00123", "00123-B"):
            with self.subTest(code=altered):
                score = score_document(label, dict(order_number={"value": "00042"}, lines=[row(altered)]))
                self.assertEqual(score["exact_raw_id_rows"], 0)
        self.assertFalse(score_document(label, dict(order_number={"value": "42"}, lines=[row()]))["po_number_correct"])

    def test_reordered_rows_score_but_extra_rows_reduce_precision(self):
        label = gold([row("A-1"), row("B-2", "4")])
        actual = dict(order_number={"value": "00042"}, lines=[row("B-2", "4.00"), row("A-1", "2.0"), row("A-1")])
        score = score_document(label, actual)
        self.assertEqual(score["exact_id_quantity_uom_rows"], 2)
        self.assertEqual(score["exact_line_recall"], 1)
        self.assertAlmostEqual(score["exact_line_precision"], 2/3)
        self.assertFalse(score["complete_document_correct"])

    def test_raw_id_credit_does_not_hide_role_or_quantity_error(self):
        label = gold([row()])
        actual = dict(order_number={"value": "00042"}, lines=[row(role="customer_item_number", quantity="3")])
        score = score_document(label, actual)
        self.assertEqual(score["exact_raw_id_rows"], 1)
        self.assertEqual(score["exact_id_and_role_rows"], 0)
        self.assertEqual(score["exact_id_quantity_uom_rows"], 0)
        self.assertFalse(score["catalog_decision_scored"])

    def test_wrong_identifier_role_cannot_count_as_complete_document(self):
        label = gold([row()])
        actual = dict(order_number={"value": "00042"}, lines=[row(role="customer_item_number")])
        score = score_document(label, actual)
        self.assertEqual(score["exact_line_recall"], 1)
        self.assertEqual(score["exact_raw_line_recall"], 1)
        self.assertEqual(score["exact_role_line_recall"], 0)
        self.assertEqual(score["exact_role_line_precision"], 0)
        self.assertFalse(score["complete_document_correct"])
        actual["lines"] = [row()]
        self.assertTrue(score_document(label, actual)["complete_document_correct"])

    def test_summary_separates_raw_and_role_aware_line_agreement(self):
        label = gold([row()])
        prediction = dict(order_number={"value": "00042"}, lines=[row(role="customer_item_number")])
        score = score_document(label, prediction)
        summary = summarize_scores([dict(prediction=prediction, score=score)], [dict(sha256="a" * 64)], {"a" * 64: label})
        self.assertEqual(summary["exact_id_role_quantity_uom_rows"], 0)
        self.assertEqual(summary["exact_line_recall"], summary["exact_raw_line_recall"])
        self.assertEqual(summary["exact_line_precision"], summary["exact_raw_line_precision"])
        self.assertEqual(summary["exact_raw_line_recall"], 1)
        self.assertEqual(summary["exact_role_line_recall"], 0)
        self.assertEqual(summary["exact_role_line_precision"], 0)
        self.assertEqual(summary["complete_labeled_documents_correct"], 0)
        self.assertIn("roles excluded", summary["line_metric_definitions"]["exact_line_recall"])

    def test_weaker_duplicate_label_cannot_replace_verified_evidence(self):
        verified = dict(sha256="a" * 64, **gold([row()]), evidence=dict(method="Original independent visual review"))
        unverified = dict(verified, review_status="unverified", evidence=dict(method=None))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "labels.json"
            for documents in ([verified, unverified], [unverified, verified]):
                with self.subTest(order=[item["review_status"] for item in documents]):
                    target.write_text(json.dumps(dict(schema_version=1, documents=documents)), encoding="utf-8")
                    labels = load_gold(target)
                    self.assertEqual(labels["a" * 64]["review_status"], "visually_verified")
                    self.assertEqual(labels["a" * 64]["evidence"], verified["evidence"])

    def test_conflicting_duplicate_expectations_are_still_rejected(self):
        verified = dict(sha256="a" * 64, **gold([row()]))
        conflicting = dict(sha256="a" * 64, **gold([row("DIFFERENT")]))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "labels.json"
            target.write_text(json.dumps(dict(schema_version=1, documents=[verified, conflicting])), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting gold labels"):
                load_gold(target)

    def test_units_cannot_be_converted_for_accuracy(self):
        score = score_document(gold([row(unit="PK")]), dict(lines=[row(unit="EA")]))
        self.assertEqual(score["exact_id_quantity_uom_rows"], 0)

    def test_null_quantity_and_unit_expectations_never_count_as_correct(self):
        label = gold([row(quantity=None, unit=None)])
        score = score_document(label, dict(order_number={"value": "00042"}, lines=[row(quantity=None, unit=None)]))
        self.assertEqual(score["exact_raw_id_rows"], 1)
        self.assertEqual(score["expected_quantity_labels"], 0)
        self.assertEqual(score["expected_uom_labels"], 0)
        self.assertEqual(score["exact_id_quantity_uom_rows"], 0)
        self.assertFalse(score["complete_document_correct"])

    def test_missing_openai_key_exits_before_reading_dataset_or_initializing_provider(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(stream):
            with self.assertRaises(SystemExit) as stopped:
                main(["--mode", "vision", "--provider", "openai", "--model", "example", "--zip", "absent.zip"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("OPENAI_API_KEY is not configured", stream.getvalue())

    def test_openai_cannot_silently_claim_local_cascade_pipeline(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(stream):
            with self.assertRaises(SystemExit) as stopped:
                main(["--mode", "vision", "--provider", "openai", "--pipeline", "cascade", "--model", "example", "--zip", "absent.zip"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("cascade requires the local Ollama provider", stream.getvalue())

    def test_internal_model_page_failure_preserves_report_and_returns_failure(self):
        doc = dict(filename="sample.pdf", archive_entry="sample.pdf", sha256="a" * 64,
                   leakage_group="leakage-001", raw=b"sample", size_bytes=6, pages=[dict(page=1)])
        partial = dict(filename="sample.pdf", sha256="a" * 64, status="partial", lines=[],
                       extraction=dict(pages=[], failures=[dict(page=1, error="incomplete response")]))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.zip"
            source.write_bytes(b"mock archive bytes")
            destination = Path(temp) / "reports"
            with patch("benchmark_vision.read_archive", return_value=[doc]), \
                    patch("benchmark_vision.inventory_documents", return_value={}), \
                    patch("benchmark_vision.load_catalog", return_value={}), \
                    patch("po_reader.model_provider.build_provider", return_value=object()), \
                    patch("po_reader.vision.analyze_vision", return_value=partial), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = main(["--mode", "vision", "--model", "mock", "--zip", str(source), "--output-dir", str(destination)])
            self.assertEqual(status, 1)
            report = json.loads((destination / "vision-benchmark-vision.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["failed_model_pages"], 1)
            self.assertEqual(report["summary"]["partial_predictions"], 1)
            self.assertEqual(report["results"][0]["prediction"]["extraction"]["failures"][0]["error"], "incomplete response")

    def test_empty_labeled_document_penalizes_invented_product(self):
        score = score_document(gold([]), dict(order_number={"value": "00042"}, lines=[row()]))
        self.assertEqual(score["expected_product_lines"], 0)
        self.assertFalse(score["complete_document_correct"])

    def test_shared_pages_connect_document_split_groups(self):
        documents = [dict(sha256="a", archive_entry="a.pdf", page_fingerprints=["order-a", "terms"]),
                     dict(sha256="b", archive_entry="b.pdf", page_fingerprints=["order-b", "terms"]),
                     dict(sha256="c", archive_entry="c.pdf", page_fingerprints=["order-c"])]
        duplicate = group_duplicates(documents)
        self.assertEqual(documents[0]["leakage_group"], documents[1]["leakage_group"])
        self.assertNotEqual(documents[1]["leakage_group"], documents[2]["leakage_group"])
        self.assertEqual(duplicate["duplicate_page_occurrences"], 1)

    def test_traversal_archive_member_is_read_in_memory_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.zip"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("../../outside.pdf", b"pdf bytes")
                archive.writestr("ignore.txt", b"not a pdf")
            path.write_bytes(buffer.getvalue())
            docs = read_archive(path)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["filename"], "outside.pdf")
            self.assertEqual(docs[0]["raw"], b"pdf bytes")
            self.assertEqual([p.name for p in Path(temp).iterdir()], ["input.zip"])


if __name__ == "__main__":
    unittest.main()
