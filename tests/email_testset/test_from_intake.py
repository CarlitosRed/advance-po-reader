"""Tests for tools/email-testset/from_intake.py: runner --out folder -> scorer answers.jsonl.

Fictional data only, offline, fake provider only. Bypass-first: most tests damage a
real runner output folder and require the converter to fail closed (exit 2, no file).
"""

import contextlib
import io
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "email-testset"
sys.path[:0] = [str(TOOLS), str(ROOT)]
import from_intake  # noqa: E402
import generate  # noqa: E402
import score  # noqa: E402
from email_intake import VERSION  # noqa: E402
from email_intake import contract as intake_contract  # noqa: E402
from email_intake.providers import FakeProvider  # noqa: E402
from email_intake.runner import run as intake_run  # noqa: E402
from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON  # noqa: E402
for entry in (str(TOOLS), str(ROOT)):
    sys.path.remove(entry)

SEED = 20261008
COUNTER = itertools.count(1)


def perfect_map(expected):
    return {row["sha256"]: {"category": row["category"], "lane": CATEGORY_LANE[row["category"]],
                            "reason_code": CATEGORY_REASON[row["category"]]} for row in expected}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-from-intake-")
        cls.root = Path(cls.temp.name)
        cls.set = cls.root / "set"
        cls.rows = generate.generate(SEED, cls.set)
        cls.expected_path = cls.set / "expected.jsonl"
        cls.expected = {row["id"]: row for row in cls.rows}
        cls.scripted = cls.root / "scripted-out"
        intake_run(cls.set, cls.scripted, FakeProvider(perfect_map(cls.rows)))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fresh_out(self):
        target = self.root / f"out-{next(COUNTER)}"
        shutil.copytree(self.scripted / "records", target / "records")
        return target

    def record_path(self, out, fixture_id):
        for path in (out / "records").glob("*.json"):
            if json.loads(path.read_text(encoding="utf-8"))["source_name"] == f"{fixture_id}.eml":
                return path
        raise AssertionError(fixture_id)

    def edit(self, out, fixture_id, change):
        path = self.record_path(out, fixture_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def convert(self, out):
        answers = self.root / f"answers-{next(COUNTER)}.jsonl"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = from_intake.main(["--out", str(out), "--expected", str(self.expected_path), "--answers", str(answers)])
        return code, err.getvalue(), answers, stdout.getvalue()

    def assert_fails_closed(self, out, fragment):
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 2, err)
        self.assertIn(fragment, err)
        self.assertFalse(answers.exists(), "no answers file may be written on failure")

    def first(self, **wanted):
        for row in self.rows:
            if all(row[k] == v for k, v in wanted.items()):
                return row["id"]
        raise AssertionError(wanted)

    def order_with_document(self, out, reply_free=True):
        for row in self.rows:
            if row["category"] == "order":
                record = json.loads(self.record_path(out, row["id"]).read_text(encoding="utf-8"))
                if record["lane"] == "order" and any(a["disposition"] == "attachment" for a in record["attachment_manifest"]):
                    return row["id"]
        raise AssertionError("no order with a document")


class BypassTests(Base):
    def test_baseline_scripted_folder_converts(self):
        code, err, answers, _ = self.convert(self.scripted)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(answers.read_text(encoding="utf-8").splitlines()), 200)

    def test_missing_record(self):
        out = self.fresh_out()
        self.record_path(out, "fictional-0005").unlink()
        self.assert_fails_closed(out, "fictional-0005.eml")

    def test_empty_records_folder(self):
        out = self.fresh_out()
        for path in (out / "records").glob("*.json"):
            path.unlink()
        self.assert_fails_closed(out, "no record")

    def test_partial_record_missing_field(self):
        for field in ("lane", "category", "reason_code", "source_name", "intake_id", "attachment_manifest"):
            with self.subTest(field=field):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, f=field: r.pop(f))
                self.assert_fails_closed(out, "missing fields")

    def test_truncated_and_empty_and_non_object_record(self):
        for text in ('{"version": "email-intake-v1", "lane"', "", "[]", "null", '"order"'):
            with self.subTest(text=text):
                out = self.fresh_out()
                self.record_path(out, "fictional-0007").write_text(text, encoding="utf-8")
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_extra_field(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(approved=True))
        self.assert_fails_closed(out, "unknown fields")

    def test_unknown_lane(self):
        for lane in ("Order", "no", "approved", "", "needs-a-look", None, 3):
            with self.subTest(lane=lane):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, v=lane: r.update(lane=v))
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_inconsistent_triples(self):
        cases = [("order", "needs_a_look", "new_order"), ("spam", "order", "spam_only"),
                 ("order", "order", "CONFLICT"), ("unsure", "order", "CONFLICT"),
                 ("unsure", "not_an_order", "CONFLICT"), ("order", "order", "spam_only"),
                 ("bogus", "order", "new_order"), ("unsure", "needs_a_look", "MADE_UP_CODE"),
                 ("unsure", "needs_a_look", "conflict"), ("change", "needs_a_look", "CONFLICT")]
        for category, lane, reason in cases:
            with self.subTest(case=(category, lane, reason)):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r: r.update(category=category, lane=lane, reason_code=reason))
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_duplicate_ids_two_records_one_email(self):
        out = self.fresh_out()
        source = self.record_path(out, "fictional-0007")
        record = json.loads(source.read_text(encoding="utf-8"))
        record["record_id"] = "f" * 64
        (out / "records" / ("f" * 64 + ".json")).write_text(json.dumps(record), encoding="utf-8")
        self.assert_fails_closed(out, "two records for fictional-0007.eml")

    def test_duplicate_json_key_in_record(self):
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"lane":', '"lane": "order", "lane":', 1), encoding="utf-8")
        self.assert_fails_closed(out, "duplicate JSON key")

    def test_renamed_field(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(route=r.pop("lane")))
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 2, err)
        self.assertFalse(answers.exists())

    def test_record_for_a_different_email_than_expected(self):
        out = self.fresh_out()
        a, b = self.record_path(out, "fictional-0007"), self.record_path(out, "fictional-0008")
        ra, rb = json.loads(a.read_text()), json.loads(b.read_text())
        ra["source_name"], rb["source_name"] = rb["source_name"], ra["source_name"]
        a.write_text(json.dumps(ra)), b.write_text(json.dumps(rb))
        self.assert_fails_closed(out, "does not match the expected email bytes")

    def test_changed_email_bytes_hash_mismatch(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(intake_id="0" * 64))
        self.assert_fails_closed(out, "does not match the expected email bytes")

    def test_extra_record_not_in_expected(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(source_name="fictional-9999.eml"))
        self.assert_fails_closed(out, "not in expected.jsonl")

    def test_wrong_platform_paths(self):
        bad_names = ["sub\\fictional-0007.eml", "sub/fictional-0007.eml", "..\\fictional-0007.eml",
                     "../fictional-0007.eml", "C:\\drop\\fictional-0007.eml", "C:fictional-0007.eml",
                     "/abs/fictional-0007.eml", "fictional-0007.eml\x00.txt", "fictional-0007.EML", "fictional-0007"]
        for name in bad_names:
            with self.subTest(source_name=name):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, n=name: r.update(source_name=n))
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())
        for original in ("/etc/passwd", "C:\\Windows\\x.eml", "..\\x.eml", "sources/../../x.eml", "\\\\server\\share\\x.eml", "", 5):
            with self.subTest(original=original):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, o=original: r.update(original=o))
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_both_platform_separators_in_stored_relative_paths_are_accepted(self):
        # The runner stores str(Path); a folder made on Windows uses backslashes, on POSIX slashes.
        for original in ("sources\\abc\\original.eml", "sources/abc/original.eml"):
            with self.subTest(original=original):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, o=original: r.update(original=o))
                code, err, _, _ = self.convert(out)
                self.assertEqual(code, 0, err)

    def test_out_is_a_file_or_missing_or_has_no_records(self):
        for make in ("file", "missing", "empty"):
            with self.subTest(make=make):
                target = self.root / f"bad-out-{make}"
                if make == "file":
                    target.write_text("x")
                elif make == "empty":
                    target.mkdir()
                code, err, answers, _ = self.convert(target)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_local_reason_code_is_omitted_not_passed_through(self):
        out = self.fresh_out()
        limited = [row["id"] for row in self.rows if json.loads(self.record_path(out, row["id"]).read_text())["reason_code"] == "PDF_LIMIT"]
        self.assertTrue(limited, "the scripted run must contain PDF_LIMIT records")
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 0, err)
        by_id = {json.loads(line)["id"]: json.loads(line) for line in answers.read_text().splitlines()}
        for fixture_id in limited:
            self.assertEqual(by_id[fixture_id], {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
        self.assertEqual(score.main(["--expected", str(self.expected_path), "--answers", str(answers)]), 0)

    def test_naive_passthrough_is_rejected_by_the_scorer(self):
        # Why the converter exists: copying the runner's triple verbatim exits 2 in the scorer.
        out = self.fresh_out()
        rows = []
        for row in self.rows:
            record = json.loads(self.record_path(out, row["id"]).read_text())
            rows.append({k: record[k] for k in ("category", "lane", "reason_code")} | {"id": row["id"]})
        naive = self.root / "naive.jsonl"
        naive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(score.main(["--expected", str(self.expected_path), "--answers", str(naive)]), 2)

    def test_every_local_reason_maps_to_unsure_needs_a_look(self):
        for reason in sorted(from_intake.LOCAL_REASONS):
            with self.subTest(reason=reason):
                out = self.fresh_out()
                fixture_id = self.first(category="invoice")

                def pend(r, reason=reason):
                    r.update(category="unsure", lane="needs_a_look", reason_code=reason, needs_a_look=[reason])
                    r["duplicate_of"] = "a" * 64 if reason == "DUPLICATE" else None
                self.edit(out, fixture_id, pend)
                code, err, answers, summary = self.convert(out)
                self.assertEqual(code, 0, err)
                rows = {json.loads(line)["id"]: json.loads(line) for line in answers.read_text().splitlines()}
                self.assertEqual(rows[fixture_id], {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
                self.assertEqual(json.loads(summary)["local_reason_codes_omitted"].get(reason), 1 + (reason == "PDF_LIMIT") * 10)

    def test_inconsistent_review_list_is_rejected(self):
        out = self.fresh_out()
        self.edit(out, self.first(category="change"), lambda r: r.update(needs_a_look=[]))
        self.assert_fails_closed(out, "needs_a_look list disagrees")

    def test_duplicate_of_without_duplicate_reason(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(duplicate_of="a" * 64))
        self.assert_fails_closed(out, "DUPLICATE")

    def test_unfinished_run_lock_file(self):
        out = self.fresh_out()
        (out / ".intake-lock").write_text("")
        self.assert_fails_closed(out, "run in progress")

    def test_mixed_providers(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(provider="live"))
        self.assert_fails_closed(out, "more than one provider")

    def test_unknown_versions_and_hash_kind(self):
        for field, value in (("version", "email-intake-v2"), ("parser_version", "mime-v2"),
                             ("source_hash_kind", "md5"), ("provider", "other"), ("source_size", True)):
            with self.subTest(field=field):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, f=field, v=value: r.update({f: v}))
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_oversized_source_without_limit_is_rejected(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(source_hash_kind="bounded_prefix_and_size"))
        self.assert_fails_closed(out, "oversized source without LIMIT")

    def test_stray_file_and_bom_and_nan_in_records(self):
        out = self.fresh_out()
        (out / "records" / "notes.txt").write_text("x")
        self.assert_fails_closed(out, "unexpected file")
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 2, err)
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        path.write_text(path.read_text().replace('"source_size": ', '"source_size": NaN, "x": ', 1))
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 2, err)

    def test_existing_answers_file_is_never_overwritten(self):
        answers = self.root / "keep.jsonl"
        answers.write_text("keep\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = from_intake.main(["--out", str(self.scripted), "--expected", str(self.expected_path), "--answers", str(answers)])
        self.assertEqual(code, 2)
        self.assertEqual(answers.read_text(), "keep\n")

    def test_bad_expected_file(self):
        bad = self.root / "bad-expected.jsonl"
        bad.write_text('{"id": "x"}\n')
        answers = self.root / "never.jsonl"
        with contextlib.redirect_stderr(io.StringIO()):
            code = from_intake.main(["--out", str(self.scripted), "--expected", str(bad), "--answers", str(answers)])
        self.assertEqual(code, 2)
        self.assertFalse(answers.exists())


class DecisionTests(Base):
    def test_text_only_order_goes_to_check(self):
        out = self.fresh_out()
        fixture_id = next(r["id"] for r in self.rows if r["category"] == "order" and r["where_order"]["body"]
                          and not r["where_order"]["attachments"])
        record = json.loads(self.record_path(out, fixture_id).read_text())
        self.assertEqual(record["lane"], "order")
        self.assertFalse(any(a["disposition"] == "attachment" for a in record["attachment_manifest"]))
        code, err, answers, summary = self.convert(out)
        self.assertEqual(code, 0, err)
        rows = {json.loads(line)["id"]: json.loads(line) for line in answers.read_text().splitlines()}
        self.assertEqual(rows[fixture_id]["lane"], "needs_a_look")
        self.assertEqual(rows[fixture_id]["category"], "unsure")
        self.assertGreater(json.loads(summary)["orders_downgraded_to_needs_a_look"]["text_only"], 0)

    def test_reply_order_is_never_sure(self):
        out = self.fresh_out()
        fixture_id = self.order_with_document(out)
        code, err, answers, _ = self.convert(out)
        rows = {json.loads(line)["id"]: json.loads(line) for line in answers.read_text().splitlines()}
        self.assertEqual(rows[fixture_id]["lane"], "order")
        for subject in ("RE: purchase order", "  re : orden", "Re:x"):
            with self.subTest(subject=subject):
                out = self.fresh_out()
                self.edit(out, fixture_id, lambda r, s=subject: r.update(subject=s))
                code, err, answers, summary = self.convert(out)
                self.assertEqual(code, 0, err)
                rows = {json.loads(line)["id"]: json.loads(line) for line in answers.read_text().splitlines()}
                self.assertEqual(rows[fixture_id], {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
                self.assertEqual(json.loads(summary)["orders_downgraded_to_needs_a_look"], {"reply": 1, "text_only": 70})

    def test_changes_cancellations_quotes_are_never_sure(self):
        code, err, answers, _ = self.convert(self.scripted)
        for line in answers.read_text().splitlines():
            row = json.loads(line)
            if self.expected[row["id"]]["category"] in ("change", "cancellation", "quote_request"):
                self.assertEqual(row["lane"], "needs_a_look", row)
            if row["lane"] == "order":
                self.assertEqual(self.expected[row["id"]]["category"], "order")

    def test_quiet_attachment_review_stays_in_not_an_order_and_is_counted(self):
        code, err, answers, summary = self.convert(self.scripted)
        self.assertEqual(json.loads(summary)["quiet_attachment_review_not_in_scored_lane"], 4)

    def test_deterministic_bytes_and_row_order(self):
        _, _, first, out1 = self.convert(self.scripted)
        _, _, second, out2 = self.convert(self.fresh_out())
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(out1, out2)
        self.assertEqual([json.loads(l)["id"] for l in first.read_text().splitlines()], [r["id"] for r in self.rows])
        self.assertNotIn(b"\r", first.read_bytes())

    def test_contract_vocabulary_matches_the_runner(self):
        self.assertEqual(from_intake.LOCAL_REASONS, intake_contract.LOCAL_REASONS)
        self.assertEqual(intake_contract.PAIRS, {c: (CATEGORY_LANE[c], CATEGORY_REASON[c]) for c in CATEGORY_LANE})
        self.assertIn(VERSION, from_intake.ACCEPTED_VERSIONS)


class EndToEndTests(unittest.TestCase):
    """Real CLIs in separate processes: generate -> email-intake.py (offline) -> from_intake.py -> score.py."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-e2e-")
        cls.root = Path(cls.temp.name)
        cls.set = cls.root / "set"
        cls.rows = generate.generate(SEED, cls.set)
        cls.expected = cls.set / "expected.jsonl"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True,
                              encoding="utf-8", timeout=300, cwd=ROOT)

    def pipeline(self, name, fake_results=None):
        out, answers = self.root / f"out-{name}", self.root / f"answers-{name}.jsonl"
        command = [ROOT / "scripts" / "email-intake.py", "--drop", self.set, "--out", out]
        if fake_results:
            command += ["--fake-results", fake_results]
        ran = self.cli(*command)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        converted = self.cli(TOOLS / "from_intake.py", "--out", out, "--expected", self.expected, "--answers", answers)
        self.assertEqual(converted.returncode, 0, converted.stderr)
        scored = self.cli(TOOLS / "score.py", "--expected", self.expected, "--answers", answers)
        return json.loads(converted.stdout), scored, answers

    def test_default_fake_provider_everything_is_needs_a_look_and_nothing_is_lost(self):
        summary, scored, answers = self.pipeline("default")
        self.assertEqual(scored.returncode, 0, scored.stderr)
        result = json.loads(scored.stdout)
        self.assertEqual(summary["answers_by_lane"], {"needs_a_look": 200, "not_an_order": 0, "order": 0})
        self.assertEqual((result["emails"], result["true_order_emails"], result["number_of_orders"]), (200, 120, 150))
        self.assertEqual((result["lost_orders"], result["lost_order_emails"], result["lost"]), (0, 0, []))
        self.assertEqual((result["order_recall"], result["order_or_needs_a_look_recall"]), (0.0, 1.0))
        self.assertIsNone(result["order_precision"])
        # 120 true orders >= 100 and none lost: the bar is "met" only because everything went to review.
        self.assertTrue(result["pass_bar_met"])
        for line in answers.read_text().splitlines():
            self.assertEqual(set(json.loads(line)), {"id", "category", "lane", "reason_code"})

    def test_scripted_results_with_one_wrongly_dropped_order_fail_the_scorer(self):
        victim = next(r for r in self.rows if r["category"] == "order" and r["number_of_orders"] > 1)
        mapping = perfect_map(self.rows)
        mapping[victim["sha256"]] = {"category": "spam", "lane": "not_an_order", "reason_code": "spam_only"}
        scripted = self.root / "scripted.json"
        scripted.write_text(json.dumps(mapping), encoding="utf-8")
        summary, scored, _ = self.pipeline("scripted", scripted)
        self.assertEqual(scored.returncode, 1, scored.stderr)
        result = json.loads(scored.stdout)
        self.assertEqual(result["lost"], [{"id": victim["id"], "number_of_orders": victim["number_of_orders"]}])
        self.assertEqual((result["lost_order_emails"], result["lost_orders"]), (1, victim["number_of_orders"]))
        self.assertFalse(result["pass_bar_met"])
        # Hand-computed from the perfect script: 120 true orders = 40 with a real attached document (Sure),
        # 70 text-only (Check, downgraded) and 10 PDF_LIMIT (pending). The victim (3 PDFs, document order) is
        # one of the 40, so it moves from order to not_an_order: order 39, not_an_order 40 + 1, needs_a_look 120.
        self.assertFalse(victim["where_order"]["body"])
        self.assertEqual(result["true_order_emails"], 120)
        self.assertEqual(summary["local_reason_codes_omitted"], {"PDF_LIMIT": 10})
        self.assertEqual(summary["orders_downgraded_to_needs_a_look"], {"text_only": 70})
        self.assertEqual(summary["answers_by_lane"], {"needs_a_look": 120, "not_an_order": 41, "order": 39})
        self.assertEqual(result["lane_confusion"]["order"], {"needs_a_look": 80, "not_an_order": 1, "order": 39})

if __name__ == "__main__":
    unittest.main()
