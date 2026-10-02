"""Evidence identity, split leakage and explicit human release boundaries."""
from copy import deepcopy
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from pypdf import PdfWriter

from po_reader.vlm_dataset import (archive_documents, build, digest, export_approved, load_annotations,
                                   prepare, read_json, validate_dataset, value_digest, write_json, write_jsonl)


def pdf_bytes(pages=1, title=None):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=120, height=160)
    if title:
        writer.add_metadata({"/Title": title})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def observation(value=None):
    return dict(value=value, printed_label=None, status="missing" if value is None else "observed", evidence_text=value)


def target():
    address = {key: observation() for key in ("company", "address", "postcode", "country", "phone")}
    return dict(document_type="other", po_number=observation(), po_date=observation(), buyer=observation(),
                supplier=observation(), shipping=deepcopy(address), billing=deepcopy(address), currency=observation(),
                totals=[], additional_fields=[], notes=[], lines=[])


class VLMDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.zip_path = self.root / "source.zip"
        self.work = self.root / "work"
        self.output = self.root / "dataset"
        self.reviews = self.root / "reviews"
        self.reviews.mkdir()
        self.release = self.root / "released"
        self.raw = pdf_bytes(pages=2)
        self.write_zip({"../source.pdf": self.raw})

    def tearDown(self):
        self.temp.cleanup()

    def write_zip(self, entries):
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            for filename, raw in entries.items():
                archive.writestr(filename, raw)

    def annotate(self, page, page_target=None, status="candidate"):
        annotation = dict(source_sha256=page["source_sha256"], page=page["page"], image_sha256=page["image_sha256"],
                          layout_family="blank-example", annotation_origin="codex_visual_transcription",
                          review_status="pending_human_review", page_status=status,
                          target=target() if status == "candidate" and page_target is None else page_target, notes=[])
        write_json(self.work / "annotations" / f"{page['page_id']}.json", annotation)
        return annotation

    def make_dataset(self, second_status="candidate"):
        inventory = prepare(self.zip_path, self.work)
        pages = inventory["documents"][0]["pages"]
        self.annotate(pages[0])
        self.annotate(pages[1], status=second_status)
        return build(self.zip_path, self.work, self.output)

    def completed_review(self, manifest):
        doc = manifest["documents"][0]
        review = read_json(self.output / "review/templates" / f"{doc['source_sha256']}.json")
        review.update(reviewer="Human Reviewer", reviewed_utc="2026-10-01T18:00:00-06:00",
                      release_for_training=True, source_document_review_complete=True)
        for page in review["pages"]:
            page.update(decision="approve", approved_target=target())
        return review

    def test_zip_paths_and_duplicates_are_preserved_as_metadata_only(self):
        self.write_zip({"../outside.pdf": self.raw, "C:/absolute.pdf": self.raw, "notes.txt": b"not a pdf"})
        docs, ignored = archive_documents(self.zip_path)
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(docs[0]["aliases"]), 2)
        self.assertEqual(len(ignored), 1)
        inventory = prepare(self.zip_path, self.work)
        self.assertEqual(inventory["counts"]["pdf_entries"], 2)
        self.assertFalse((self.root / "outside.pdf").exists())
        self.assertEqual((self.work / f"sources/{digest(self.raw)}.pdf").read_bytes(), self.raw)

    def test_drafts_remain_unapproved_and_unresolved_pages_are_counted(self):
        manifest = self.make_dataset(second_status="unresolved")
        self.assertEqual(manifest["counts"]["pages"], 2)
        self.assertEqual(manifest["counts"]["draft_examples"], 1)
        self.assertEqual(manifest["counts"]["approved_examples"], 0)
        self.assertEqual(manifest["counts"]["page_status"]["unresolved"], 1)
        self.assertEqual((self.output / "approved/all.jsonl").read_text(), "")
        self.assertTrue(validate_dataset(self.output)["valid"])
        with self.assertRaisesRegex(ValueError, "No completed human reviews"):
            export_approved(self.output, self.reviews, self.release)
        self.assertFalse(self.release.exists())

    def test_schema_and_image_mismatch_are_rejected(self):
        inventory = prepare(self.zip_path, self.work)
        page = inventory["documents"][0]["pages"][0]
        annotation = self.annotate(page)
        annotation["image_sha256"] = "a" * 64
        path = self.work / "annotations" / f"{page['page_id']}.json"
        write_json(path, annotation)
        with self.assertRaisesRegex(ValueError, "image SHA-256"):
            load_annotations(self.work / "annotations", inventory["documents"][0]["pages"])
        annotation["image_sha256"] = page["image_sha256"]
        annotation["target"]["catalog_product_id"] = "unrequested canonical data"
        write_json(path, annotation)
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            load_annotations(self.work / "annotations", inventory["documents"][0]["pages"])

    def test_identical_images_cannot_receive_conflicting_candidates(self):
        inventory = prepare(self.zip_path, self.work)
        pages = inventory["documents"][0]["pages"]
        self.annotate(pages[0])
        conflicting = target()
        conflicting["po_number"] = observation("INVENTED")
        self.annotate(pages[1], conflicting)
        with self.assertRaisesRegex(ValueError, "Conflicting candidate targets"):
            build(self.zip_path, self.work, self.output)

    def test_all_pages_hashes_and_explicit_human_release_are_required(self):
        manifest = self.make_dataset()
        review = self.completed_review(manifest)
        path = self.reviews / "review.json"
        incomplete = deepcopy(review)
        incomplete["pages"].pop()
        write_json(path, incomplete)
        with self.assertRaisesRegex(ValueError, "every original page"):
            export_approved(self.output, self.reviews, self.release)
        review["release_for_training"] = False
        write_json(path, review)
        with self.assertRaisesRegex(ValueError, "release_for_training"):
            export_approved(self.output, self.reviews, self.release)
        review["release_for_training"] = True
        review["pages"][0]["image_sha256"] = "f" * 64
        write_json(path, review)
        with self.assertRaisesRegex(ValueError, "image_sha256"):
            export_approved(self.output, self.reviews, self.release)
        self.assertFalse(self.release.exists())

    def test_complete_human_review_bundle_releases_only_approved_examples(self):
        manifest = self.make_dataset()
        review = self.completed_review(manifest)
        review["pages"][1].update(decision="exclude", approved_target=None)
        write_json(self.reviews / "reviews.json", dict(schema_version=1, reviews=[review]))
        result = export_approved(self.output, self.reviews, self.release)
        self.assertEqual(result["human_approved_examples"], 1)
        import json
        row = json.loads((self.release / "all.jsonl").read_text())
        self.assertEqual(row["metadata"]["label_status"], "human_approved_released")
        self.assertTrue(row["metadata"]["training_eligible"])
        self.assertEqual(json.loads(row["messages"][-1]["content"]), target())
        self.assertTrue((self.release / row["images"][0]).exists())

    def test_changed_png_fails_validation_and_blocks_release(self):
        manifest = self.make_dataset()
        page = manifest["documents"][0]["pages"][0]
        image = self.output / page["image_path"]
        image.write_bytes(image.read_bytes() + b"altered")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            validate_dataset(self.output)

    def test_near_duplicates_and_layout_families_share_a_proposed_split(self):
        self.write_zip({"first.pdf": pdf_bytes(title="first"), "second.pdf": pdf_bytes(title="second")})
        inventory = prepare(self.zip_path, self.work)
        for doc in inventory["documents"]:
            self.annotate(doc["pages"][0])
        manifest = build(self.zip_path, self.work, self.output)
        self.assertEqual(len(manifest["grouping"]["groups"]), 1)
        self.assertEqual(len({d["proposed_split"] for d in manifest["documents"]}), 1)
        self.assertTrue(manifest["grouping"]["page_links"])

    def test_reruns_cannot_replace_existing_dataset_or_candidate_reviews(self):
        self.make_dataset()
        with self.assertRaisesRegex(ValueError, "empty"):
            build(self.zip_path, self.work, self.output)

    def test_exact_reprints_have_one_unique_example_and_all_occurrences(self):
        import json
        manifest = self.make_dataset()
        self.assertEqual(manifest["counts"]["draft_examples"], 2)
        self.assertEqual(manifest["counts"]["unique_draft_examples"], 1)
        row = json.loads((self.output / "draft/unique-all.jsonl").read_text())
        self.assertEqual(len(row["metadata"]["duplicate_source_pages"]), 2)
        review = self.completed_review(manifest)
        write_json(self.reviews / "complete.json", review)
        result = export_approved(self.output, self.reviews, self.release)
        self.assertEqual(result["human_approved_examples"], 2)
        self.assertEqual(result["unique_human_approved_examples"], 1)

    def test_modified_draft_and_forged_approved_placeholders_are_rejected(self):
        manifest = self.make_dataset()
        write_jsonl(self.output / "approved/all.jsonl", [dict(label_status="human_approved_released")])
        with self.assertRaisesRegex(ValueError, "placeholders"):
            validate_dataset(self.output)
        write_jsonl(self.output / "approved/all.jsonl", [])
        import json
        rows = [json.loads(line) for line in (self.output / "draft/all.jsonl").read_text().splitlines()]
        rows[0]["metadata"]["training_eligible"] = True
        write_jsonl(self.output / "draft/all.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "Draft row differs"):
            validate_dataset(self.output)

    def test_review_bundle_cannot_bind_a_different_archive(self):
        manifest = self.make_dataset()
        write_json(self.reviews / "bundle.json", dict(schema_version=1, archive_sha256="a" * 64,
                                                      reviews=[self.completed_review(manifest)]))
        with self.assertRaisesRegex(ValueError, "archive SHA-256"):
            export_approved(self.output, self.reviews, self.release)

    def test_rebinding_changed_image_hash_cannot_hide_source_disagreement(self):
        manifest = self.make_dataset()
        page = manifest["documents"][0]["pages"][0]
        path = self.output / page["image_path"]
        path.write_bytes(path.read_bytes() + b"different")
        page["image_sha256"] = digest(path.read_bytes())
        write_json(self.output / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "freshly rendered original source"):
            validate_dataset(self.output)

    def test_cli_cannot_write_private_corpus_outside_ignored_output(self):
        from build_vlm_dataset import main
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["prepare", "--work-dir", str(self.root / "public-dataset")])
        self.assertEqual(code, 2)
        self.assertIn("ignored output/", errors.getvalue())
        self.assertFalse((self.root / "public-dataset").exists())


if __name__ == "__main__":
    unittest.main()
