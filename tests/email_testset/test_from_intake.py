"""Tests for tools/email-testset/from_intake.py: runner --out folder -> scorer answers.jsonl.

Fictional data only, offline, fake provider only. Bypass-first: most tests damage a
real runner output folder and require the converter to fail closed (exit 2, no file).
"""

import contextlib
import copy
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

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
MAX_EMAIL = 2 * 1024 * 1024


def perfect_map(expected):
    return {row["sha256"]: {"category": row["category"], "lane": CATEGORY_LANE[row["category"]],
                            "reason_code": CATEGORY_REASON[row["category"]]} for row in expected}


def pre_parse_refusal(record, reason="PARSE_FAILED", intake_id=None):
    """Turn a record into what the runner writes when it stops before parsing (no parsed fields)."""
    for key in ("sender", "subject", "message_id", "body", "body_segments", "classification", "note"):
        record.pop(key, None)
    if intake_id:
        record.update(intake_id=intake_id, original=f"sources/{intake_id}/original.eml")
    record.update(category="unsure", lane="needs_a_look", reason_code=reason, needs_a_look=[reason],
                  attachment_manifest=[], reader_files=[], related_intakes=[], duplicate_of=None)


def record_id_for(record):
    return sha256((record["intake_id"] + record["source_name"]).encode()).hexdigest()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-from-intake-")
        cls.root = Path(cls.temp.name)
        cls.set = cls.root / "set"
        cls.rows = generate.generate(SEED, cls.set)
        cls.expected_path = cls.set / "expected.jsonl"
        cls.expected = {row["id"]: row for row in cls.rows}
        cls.lines = {json.loads(line)["id"]: line for line in cls.expected_path.read_text(encoding="utf-8").splitlines()}
        cls.scripted = cls.root / "scripted-out"
        intake_run(cls.set, cls.scripted, FakeProvider(perfect_map(cls.rows)))
        cls.names = {}
        cls.base = {}
        for path in (cls.scripted / "records").glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            fixture_id = record["source_name"][:-4]
            cls.names[fixture_id] = path.name
            cls.base[fixture_id] = record

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fresh_out(self):
        target = self.root / f"out-{next(COUNTER)}"
        shutil.copytree(self.scripted / "records", target / "records")
        return target

    def solo(self, fixture_id):
        """A folder holding only one record, with an expected file of only that email (fast sweeps)."""
        number = next(COUNTER)
        target = self.root / f"solo-{number}"
        (target / "records").mkdir(parents=True)
        shutil.copy(self.scripted / "records" / self.names[fixture_id], target / "records" / self.names[fixture_id])
        expected = self.root / f"solo-expected-{number}.jsonl"
        expected.write_text(self.lines[fixture_id] + "\n", encoding="utf-8")
        return target, expected

    def record_path(self, out, fixture_id):
        return out / "records" / self.names[fixture_id]

    def edit(self, out, fixture_id, change):
        path = self.record_path(out, fixture_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def rewrite(self, out, fixture_id, change, remove_old=True):
        """Apply a change, re-derive record_id and file name from the new identity (a careful forger)."""
        old = self.record_path(out, fixture_id)
        record = json.loads(old.read_text(encoding="utf-8"))
        change(record)
        record["record_id"] = record_id_for(record)
        if remove_old:
            old.unlink()
        new = out / "records" / (record["record_id"] + ".json")
        new.write_text(json.dumps(record), encoding="utf-8")
        return new

    def convert(self, out, expected_path=None, answers=None):
        answers = answers or self.root / f"answers-{next(COUNTER)}.jsonl"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = from_intake.main(["--out", str(out), "--expected", str(expected_path or self.expected_path),
                                     "--answers", str(answers)])
        return code, err.getvalue(), answers, stdout.getvalue()

    def assert_fails_closed(self, out, fragment=None, expected_path=None):
        code, err, answers, _ = self.convert(out, expected_path)
        self.assertEqual(code, 2, err)
        if fragment:
            self.assertIn(fragment, err)
        self.assertFalse(answers.exists(), "no answers file may be written on failure")
        self.assertEqual([p.name for p in answers.parent.glob(f".{answers.name}*")], [], "no temp file left")

    def answer_rows(self, answers):
        return {json.loads(line)["id"]: json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()}

    def first(self, **wanted):
        for row in self.rows:
            if all(row[k] == v for k, v in wanted.items()):
                return row["id"]
        raise AssertionError(wanted)

    def first_record(self, predicate):
        for row in self.rows:
            if predicate(self.base[row["id"]]):
                return row["id"]
        raise AssertionError("no such record")

    def order_with_document(self):
        return self.first_record(lambda r: r["lane"] == "order")

    def text_only_order(self):
        return self.first_record(lambda r: r["reason_code"] == "TEXT_ONLY_ORDER")


class BypassTests(Base):
    def test_baseline_scripted_folder_converts(self):
        code, err, answers, _ = self.convert(self.scripted)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(answers.read_text(encoding="utf-8").splitlines()), 200)
        self.assertEqual([p.name for p in answers.parent.glob(".answers-*")], [], "no temp file after success")

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
                self.assert_fails_closed(out)

    def test_extra_field(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(approved=True))
        self.assert_fails_closed(out, "unknown fields")

    def test_unknown_lane(self):
        for lane in ("Order", "no", "approved", "", "needs-a-look", None, 3):
            with self.subTest(lane=lane):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, v=lane: r.update(lane=v))
                self.assert_fails_closed(out)

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
                self.assert_fails_closed(out)

    def test_duplicate_ids_two_records_one_email(self):
        out = self.fresh_out()
        # A second complete, internally consistent record for the same source name but another email hash.
        self.rewrite(out, "fictional-0007", lambda r: pre_parse_refusal(r, intake_id="f" * 64), remove_old=False)
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
        self.assert_fails_closed(out)

    def test_record_for_a_different_email_than_expected(self):
        out = self.fresh_out()
        ra = json.loads(self.record_path(out, "fictional-0007").read_text())
        rb = json.loads(self.record_path(out, "fictional-0008").read_text())
        for fixture, record in (("fictional-0007", rb), ("fictional-0008", ra)):
            record = dict(record, source_name=f"{fixture}.eml")
            record["record_id"] = record_id_for(record)
            self.record_path(out, fixture).unlink()
            (out / "records" / (record["record_id"] + ".json")).write_text(json.dumps(record))
        self.assert_fails_closed(out, "does not match the expected email bytes")

    def test_changed_email_bytes_hash_mismatch(self):
        out, expected = self.solo("fictional-0007")
        row = json.loads(self.lines["fictional-0007"])
        row["sha256"] = "0" * 64
        expected.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assert_fails_closed(out, "does not match the expected email bytes", expected)

    def test_extra_record_not_in_expected(self):
        out = self.fresh_out()
        self.rewrite(out, "fictional-0007", lambda r: r.update(source_name="fictional-9999.eml"))
        self.assert_fails_closed(out, "not in expected.jsonl")

    def test_wrong_platform_paths(self):
        bad_names = ["sub\\fictional-0007.eml", "sub/fictional-0007.eml", "..\\fictional-0007.eml",
                     "../fictional-0007.eml", "C:\\drop\\fictional-0007.eml", "C:fictional-0007.eml",
                     "/abs/fictional-0007.eml", "fictional-0007.eml\x00.txt", "fictional-0007.EML", "fictional-0007"]
        for name in bad_names:
            with self.subTest(source_name=name):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, n=name: r.update(source_name=n))
                self.assert_fails_closed(out)
                out = self.fresh_out()
                self.rewrite(out, "fictional-0007", lambda r, n=name: r.update(source_name=n))
                self.assert_fails_closed(out)
        for original in ("/etc/passwd", "C:\\Windows\\x.eml", "..\\x.eml", "sources/../../x.eml", "\\\\server\\share\\x.eml", "", 5):
            with self.subTest(original=original):
                out = self.fresh_out()
                self.edit(out, "fictional-0007", lambda r, o=original: r.update(original=o))
                self.assert_fails_closed(out)

    def test_both_platform_separators_in_stored_relative_paths_are_accepted(self):
        # The runner stores str(Path); a folder made on Windows uses backslashes, on POSIX slashes.
        iid = self.base["fictional-0007"]["intake_id"]
        for original in (f"sources\\{iid}\\original.eml", f"sources/{iid}/original.eml"):
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
                self.assert_fails_closed(target)

    def test_naive_passthrough_is_rejected_by_the_scorer(self):
        # Why the converter exists: copying the runner's triple verbatim exits 2 in the scorer.
        rows = [{k: self.base[r["id"]][k] for k in ("category", "lane", "reason_code")} | {"id": r["id"]} for r in self.rows]
        naive = self.root / "naive.jsonl"
        naive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(score.main(["--expected", str(self.expected_path), "--answers", str(naive)]), 2)

    def test_every_local_reason_maps_to_unsure_needs_a_look(self):
        for reason in sorted(from_intake.LOCAL_REASONS - {"DUPLICATE", "TEXT_ONLY_ORDER"}):
            with self.subTest(reason=reason):
                fixture_id = self.first(category="invoice")
                out, expected = self.solo(fixture_id)

                def pend(r, reason=reason):
                    pair = {"category": "unsure", "lane": "needs_a_look", "reason_code": reason}
                    r.update(pair)
                    r["classification"] = dict(pair) if reason != "PDF_LIMIT" else {
                        "category": "order", "lane": "order", "reason_code": "new_order"}
                    r["needs_a_look"] = [reason]
                self.edit(out, fixture_id, pend)
                code, err, answers, summary = self.convert(out, expected)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.answer_rows(answers)[fixture_id],
                                 {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
                self.assertEqual(json.loads(summary)["local_reason_codes_omitted"], {reason: 1})

    def test_text_only_order_runner_outcome_maps_to_pending(self):
        fixture_id = self.text_only_order()
        out, expected = self.solo(fixture_id)
        code, err, answers, summary = self.convert(out, expected)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.answer_rows(answers)[fixture_id], {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
        self.assertEqual(json.loads(summary)["local_reason_codes_omitted"], {"TEXT_ONLY_ORDER": 1})

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
                self.assert_fails_closed(out)

    def test_stray_file_and_bom_and_nan_in_records(self):
        out = self.fresh_out()
        (out / "records" / "notes.txt").write_text("x")
        self.assert_fails_closed(out, "unexpected file")
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assert_fails_closed(out)
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        path.write_text(path.read_text().replace('"source_size": ', '"source_size": NaN, "x": ', 1))
        self.assert_fails_closed(out)

    def test_unknown_files_in_the_folder_root_are_rejected(self):
        for name in ("notes.txt", "answers.jsonl", "records-old"):
            with self.subTest(name=name):
                out = self.fresh_out()
                (out / name).write_text("x")
                self.assert_fails_closed(out, "unexpected entries")

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


class IdentityTests(Base):
    """P1: every record must be provably this run's record for the expected email, for every hash kind."""

    def foreign_limit_record(self):
        drop = self.root / f"foreign-drop-{next(COUNTER)}"
        drop.mkdir()
        (drop / "foreign.eml").write_bytes(b"From: a@b.example\r\nSubject: x\r\n\r\n" + b"A" * (MAX_EMAIL + 1))
        out = self.root / f"foreign-out-{next(COUNTER)}"
        intake_run(drop, out, FakeProvider())
        (path,) = list((out / "records").glob("*.json"))
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((record["source_hash_kind"], record["reason_code"]), ("bounded_prefix_and_size", "LIMIT"))
        return record

    def test_foreign_limit_record_cannot_replace_a_missing_order(self):
        victim = "fictional-0005"
        self.assertEqual(self.expected[victim]["category"], "order")
        foreign = self.foreign_limit_record()
        # Variant A: only the source name is changed; the file name and record id stay the foreign ones.
        out = self.fresh_out()
        self.record_path(out, victim).unlink()
        (out / "records" / (foreign["record_id"] + ".json")).write_text(
            json.dumps(dict(foreign, source_name=f"{victim}.eml")), encoding="utf-8")
        self.assert_fails_closed(out)
        # Variant B: a careful forger also re-derives the record id and file name.
        out = self.fresh_out()
        self.record_path(out, victim).unlink()
        forged = dict(foreign, source_name=f"{victim}.eml")
        forged["record_id"] = record_id_for(forged)
        (out / "records" / (forged["record_id"] + ".json")).write_text(json.dumps(forged), encoding="utf-8")
        self.assert_fails_closed(out, "cannot be bound")

    def test_real_oversized_source_is_rejected_not_matched_to_a_fixture(self):
        # The expected data holds only the whole-file hash, which an oversized source never produces.
        foreign = self.foreign_limit_record()
        out = self.fresh_out()
        self.record_path(out, "fictional-0005").unlink()
        forged = dict(foreign, source_name="fictional-0005.eml")
        forged["record_id"] = record_id_for(forged)
        (out / "records" / (forged["record_id"] + ".json")).write_text(json.dumps(forged), encoding="utf-8")
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 2, err)
        self.assertFalse(answers.exists())

    def test_small_record_relabelled_bounded_prefix_with_limit(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(
            source_hash_kind="bounded_prefix_and_size", reason_code="LIMIT", category="unsure", lane="needs_a_look",
            needs_a_look=["LIMIT"]))
        self.assert_fails_closed(out)

    def test_oversized_source_without_limit_is_rejected(self):
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(source_hash_kind="bounded_prefix_and_size"))
        self.assert_fails_closed(out)

    def test_record_id_must_derive_from_intake_id_and_source_name(self):
        out = self.fresh_out()
        path = self.record_path(out, "fictional-0007")
        record = json.loads(path.read_text(encoding="utf-8"))
        record["record_id"] = sha256(b"anything else").hexdigest()
        path.unlink()
        (out / "records" / (record["record_id"] + ".json")).write_text(json.dumps(record), encoding="utf-8")
        self.assert_fails_closed(out, "record_id is not derived")

    def test_record_of_another_email_renamed_with_everything_re_derived(self):
        out = self.fresh_out()
        self.record_path(out, "fictional-0007").unlink()
        other = json.loads(self.record_path(out, "fictional-0008").read_text(encoding="utf-8"))
        other["source_name"] = "fictional-0007.eml"
        other["record_id"] = record_id_for(other)
        (out / "records" / (other["record_id"] + ".json")).write_text(json.dumps(other), encoding="utf-8")
        self.assert_fails_closed(out, "does not match the expected email bytes")

    def test_stored_paths_must_belong_to_the_records_own_intake_id(self):
        other = self.base["fictional-0008"]["intake_id"]
        out = self.fresh_out()
        self.edit(out, "fictional-0007", lambda r: r.update(original=f"sources/{other}/original.eml"))
        self.assert_fails_closed(out, "invalid original path")
        out = self.fresh_out()
        fixture_id = self.order_with_document()
        self.edit(out, fixture_id, lambda r: r["reader_files"][0].update(file=f"sources/{other}/a001.pdf"))
        self.assert_fails_closed(out, "reader file path")

    def test_duplicate_of_and_related_intakes_must_name_this_run(self):
        victim = self.first(category="invoice")
        out = self.fresh_out()
        pair = dict(category="unsure", lane="needs_a_look", reason_code="DUPLICATE")
        self.edit(out, victim, lambda r: r.update(pair, duplicate_of="a" * 64, needs_a_look=["DUPLICATE"],
                                                           classification=dict(pair)))
        self.assert_fails_closed(out, "duplicate_of is not a record of this run")
        out = self.fresh_out()
        self.edit(out, victim, lambda r: r.update(related_intakes=["b" * 64]))
        self.assert_fails_closed(out, "related_intakes")


class RawRunnerTests(Base):
    """P2-2: the answer is the runner's own category and lane; the converter adds no policy."""

    def test_lane_and_category_of_every_answer_equal_the_runner_record(self):
        code, err, answers, summary = self.convert(self.scripted)
        self.assertEqual(code, 0, err)
        rows = self.answer_rows(answers)
        for fixture_id, record in self.base.items():
            row = rows[fixture_id]
            self.assertEqual(row["lane"], record["lane"], fixture_id)
            self.assertEqual(row["category"], record["category"], fixture_id)
            if "reason_code" in row:
                self.assertEqual(row["reason_code"], record["reason_code"], fixture_id)
        by_lane = {lane: sum(r["lane"] == lane for r in self.base.values()) for lane in ("order", "needs_a_look", "not_an_order")}
        self.assertEqual(by_lane, {"order": 50, "needs_a_look": 110, "not_an_order": 40})
        self.assertEqual(json.loads(summary)["answers_by_lane"], by_lane)
        self.assertNotIn("orders_downgraded_to_needs_a_look", json.loads(summary))

    def test_a_reply_subject_does_not_change_the_runner_lane(self):
        fixture_id = self.order_with_document()
        for subject in ("RE: purchase order", "  re : orden", "Re:x"):
            with self.subTest(subject=subject):
                out, expected = self.solo(fixture_id)
                self.edit(out, fixture_id, lambda r, s=subject: r.update(subject=s))
                code, err, answers, _ = self.convert(out, expected)
                self.assertEqual(code, 0, err)
                row = self.answer_rows(answers)[fixture_id]
                self.assertEqual((row["category"], row["lane"]), ("order", "order"))

    def test_attachment_disposition_does_not_change_the_runner_lane(self):
        fixture_id = self.order_with_document()
        for disposition in ("inline", "attachment"):
            with self.subTest(disposition=disposition):
                out, expected = self.solo(fixture_id)
                self.edit(out, fixture_id, lambda r, d=disposition: [a.update(disposition=d) for a in r["attachment_manifest"]])
                code, err, answers, _ = self.convert(out, expected)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.answer_rows(answers)[fixture_id]["lane"], "order")

    def test_runner_false_positive_is_not_erased(self):
        # A non-order email (invoice with a supported attachment) wrongly classified order by the classifier.
        victim = next(r["id"] for r in self.rows if r["category"] == "invoice"
                      and any(a["supported"] for a in self.base[r["id"]]["attachment_manifest"]))
        mapping = perfect_map(self.rows)
        mapping[self.expected[victim]["sha256"]] = {"category": "order", "lane": "order", "reason_code": "new_order"}
        out = self.root / f"fp-out-{next(COUNTER)}"
        intake_run(self.set, out, FakeProvider(mapping))
        raw = {json.loads(p.read_text())["source_name"][:-4]: json.loads(p.read_text()) for p in (out / "records").glob("*.json")}
        self.assertEqual((raw[victim]["category"], raw[victim]["lane"]), ("order", "order"))
        code, err, answers, _ = self.convert(out)
        self.assertEqual(code, 0, err)
        rows = self.answer_rows(answers)
        self.assertEqual((rows[victim]["category"], rows[victim]["lane"]), ("order", "order"))
        result = score.score(score.read_rows(self.expected_path, expected=True), score.read_rows(answers, expected=False))
        self.assertEqual(result["predicted_order_emails"], 51)
        self.assertEqual(result["order_precision"], 50 / 51)

    def test_contract_vocabulary_matches_the_runner(self):
        self.assertEqual(from_intake.LOCAL_REASONS, intake_contract.LOCAL_REASONS)
        self.assertEqual(intake_contract.PAIRS, {c: (CATEGORY_LANE[c], CATEGORY_REASON[c]) for c in CATEGORY_LANE})
        self.assertIn(VERSION, from_intake.ACCEPTED_VERSIONS)
        self.assertEqual(self.base[self.text_only_order()]["note"], from_intake.TEXT_ONLY_NOTE)
        from email_intake.parser import MAX_EMAIL as RUNNER_MAX, SUPPORTED
        self.assertEqual(RUNNER_MAX, from_intake.MAX_EMAIL)
        self.assertEqual({k: v[0] for k, v in SUPPORTED.items()}, from_intake.EXTENSIONS)


POOL = [None, True, False, 0, 1, 12, -1, 1.5, "", "x", "spam", "A" * 64, [], {}, [{}], ["x"], [[]], {"a": 1}]
BENIGN_STRING = {("sender",), ("subject",)}


def leaf_paths(value, prefix=()):
    """Every dict key and list index of a record, containers included."""
    yield prefix
    if isinstance(value, dict):
        for key in value:
            yield from leaf_paths(value[key], prefix + (key,))
    elif isinstance(value, list):
        for index in range(len(value)):
            yield from leaf_paths(value[index], prefix + (index,))


def get_at(root, path):
    for step in path:
        root = root[step]
    return root


def is_benign(path, value):
    """Replacement values that are legitimately valid, so the sweep expects exit 0 for them."""
    if path in BENIGN_STRING:
        return type(value) is str and value != ""
    if path == ("message_id",):
        return value is None
    if path == ("source_size",):
        return type(value) is int and 0 <= value <= MAX_EMAIL
    if len(path) == 3 and path[0] == "attachment_manifest" and path[2] == "filename":
        return type(value) is str and value != ""
    if len(path) == 3 and path[0] == "attachment_manifest" and path[2] == "byte_length":
        return type(value) is int and value >= 0
    if len(path) == 3 and path[0] == "attachment_manifest" and path[2] == "supported":
        return value is False  # the magic-byte verdict cannot be re-derived from the manifest; false only narrows
    return False


class MalformedValueTests(Base):
    """P2-3: partial or wrong-typed values and nested entries fail closed, never read as stronger certainty."""

    def sweep(self, fixture_id):
        out, expected = self.solo(fixture_id)
        path_file = self.record_path(out, fixture_id)
        original = json.loads(path_file.read_text(encoding="utf-8"))
        accepted = []
        for path in leaf_paths(original):
            if not path:
                continue
            candidates = [("delete", None)] if isinstance(path[-1], str) and path not in (("note",),) else []
            candidates += [("set", value) for value in POOL]
            candidates.append(("add-key", None))
            for kind, value in candidates:
                record = copy.deepcopy(original)
                parent = get_at(record, path[:-1])
                current = parent[path[-1]]
                if kind == "set":
                    if value == current and type(value) is type(current):
                        continue
                    parent[path[-1]] = value
                elif kind == "delete":
                    del parent[path[-1]]
                else:
                    if not isinstance(current, dict):
                        continue
                    current["unexpected"] = True
                path_file.write_text(json.dumps(record), encoding="utf-8")
                code, err, answers, _ = self.convert(out, expected)
                if code == 0:
                    accepted.append((path, kind, value))
                    answers.unlink()
                else:
                    self.assertEqual(code, 2, (path, kind, value, err))
                    self.assertFalse(answers.exists())
        unexpected = [a for a in accepted if not (a[1] == "set" and is_benign(a[0], a[2]))]
        self.assertEqual(unexpected, [], f"{fixture_id}: malformed values accepted")

    def test_sweep_order_with_document(self):
        self.sweep(self.order_with_document())

    def test_sweep_text_only_order(self):
        self.sweep(self.text_only_order())

    def test_sweep_quiet_not_an_order_with_attachment(self):
        self.sweep(self.first_record(lambda r: r["lane"] == "not_an_order" and r["attachment_manifest"]))

    def test_sweep_change_request(self):
        self.sweep(self.first(category="change"))

    def test_named_cases_from_review(self):
        fixture_id = self.order_with_document()
        cases = {
            "approval false": lambda r: r.update(human_product_approval_required=False),
            "approval string": lambda r: r.update(human_product_approval_required="true"),
            "related_intakes empty object": lambda r: r.update(related_intakes=[{}]),
            "classification string": lambda r: r.update(classification="spam"),
            "classification other category": lambda r: r.update(classification=dict(category="spam", lane="not_an_order", reason_code="spam_only")),
            "body integer": lambda r: r.update(body=12),
            "manifest reduced": lambda r: r.update(attachment_manifest=[{"supported": True, "disposition": "attachment"}]),
            "reader file reduced": lambda r: r.update(reader_files=[{"file": "missing.pdf", "derived": False}]),
            "subject deleted": lambda r: r.pop("subject"),
            "all parsed fields deleted": lambda r: [r.pop(k) for k in ("sender", "subject", "message_id", "body", "body_segments", "classification")],
            "manifest emptied": lambda r: r.update(attachment_manifest=[]),
            "reader files emptied": lambda r: r.update(reader_files=[]),
        }
        for label, change in cases.items():
            with self.subTest(case=label):
                out, expected = self.solo(fixture_id)
                self.edit(out, fixture_id, change)
                self.assert_fails_closed(out, expected_path=expected)

    def test_pre_parse_refusal_is_accepted_but_not_when_it_carries_parsed_data(self):
        # A genuine record that stopped before parsing has no parsed fields; that absence is legitimate.
        fixture_id = self.first(category="invoice")
        out, expected = self.solo(fixture_id)

        self.edit(out, fixture_id, pre_parse_refusal)

        code, err, answers, summary = self.convert(out, expected)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(summary)["local_reason_codes_omitted"], {"PARSE_FAILED": 1})
        self.edit(out, fixture_id, lambda r: r.update(reason_code="CONFLICT", needs_a_look=["CONFLICT"]))
        self.assert_fails_closed(out, expected_path=expected)
        self.edit(out, fixture_id, lambda r: r.update(reason_code="PARSE_FAILED", needs_a_look=["PARSE_FAILED"], subject="x"))
        self.assert_fails_closed(out, expected_path=expected)


class WindowsPathTests(Base):
    """P2-4: aliases and invalid Windows path syntax are rejected; ordinary relative paths still pass."""

    def make_junction(self, link, target):
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest(f"cannot create a junction here: {result.stderr or result.stdout}")
        self.addCleanup(os.rmdir, link)  # removes the link only, never the target

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_junction_as_out_folder(self):
        out = self.fresh_out()
        link = self.root / f"junction-out-{next(COUNTER)}"
        self.make_junction(link, out)
        self.assertEqual(self.convert(out)[0], 0)
        self.assert_fails_closed(link)

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_junction_as_records_folder_and_as_ancestor_of_out(self):
        real = self.fresh_out()
        out = self.root / f"out-with-junction-records-{next(COUNTER)}"
        out.mkdir()
        self.make_junction(out / "records", real / "records")
        self.assert_fails_closed(out)
        parent_link = self.root / f"junction-parent-{next(COUNTER)}"
        holder = self.root / f"holder-{next(COUNTER)}"
        (holder).mkdir()
        shutil.copytree(real / "records", holder / "run" / "records")
        self.make_junction(parent_link, holder)
        self.assert_fails_closed(parent_link / "run")

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_junction_as_answers_folder(self):
        target = self.root / f"answers-target-{next(COUNTER)}"
        target.mkdir()
        link = self.root / f"answers-link-{next(COUNTER)}"
        self.make_junction(link, target)
        code, err, answers, _ = self.convert(self.scripted, answers=link / "answers.jsonl")
        self.assertEqual(code, 2, err)
        self.assertEqual(list(target.iterdir()), [])

    def test_invalid_stored_paths(self):
        iid = self.base["fictional-0007"]["intake_id"]
        bad = [f"sources/{iid}/original.eml:stream", f"sources/{iid}/original.eml::$DATA", f"sources/C:stream/original.eml",
               f"sources/{iid}/NUL", f"sources/NUL/original.eml", f"sources/{iid}/original.eml.", f"sources/{iid}/original.eml ",
               f"sources/{iid}/CON.eml", f"sources/{iid}/original.eml/.", f"sources/file:stream", f"sources/{iid}/./original.eml",
               f"sources//{iid}/original.eml", f"sources/{iid}/ORIGINAL.EML", f"sources/{iid}/or*ginal.eml", f"C:sources/{iid}/original.eml"]
        for original in bad:
            with self.subTest(original=original):
                out, expected = self.solo("fictional-0007")
                self.edit(out, "fictional-0007", lambda r, o=original: r.update(original=o))
                self.assert_fails_closed(out, expected_path=expected)

    def test_invalid_stored_paths_in_manifest_and_reader_files(self):
        fixture_id = self.order_with_document()
        record = self.base[fixture_id]
        iid = record["intake_id"]
        reader = record["reader_files"][0]["file"].replace("\\", "/")
        retained = record["attachment_manifest"][0]["retained_file"].replace("\\", "/")
        for suffix in (":stream", "::$DATA", ".", " "):
            for label, change in (
                    ("reader", lambda r, s=suffix: r["reader_files"][0].update(file=reader + s)),
                    ("retained", lambda r, s=suffix: r["attachment_manifest"][0].update(retained_file=retained + s))):
                with self.subTest(label=label, suffix=suffix):
                    out, expected = self.solo(fixture_id)
                    self.edit(out, fixture_id, change)
                    self.assert_fails_closed(out, expected_path=expected)
        for device in (f"sources/{iid}/NUL", "sources/NUL/a001.pdf", f"sources/{iid}/COM1.pdf", f"sources/{iid}/aux"):
            with self.subTest(device=device):
                out, expected = self.solo(fixture_id)
                self.edit(out, fixture_id, lambda r, d=device: r["reader_files"][0].update(file=d))
                self.assert_fails_closed(out, expected_path=expected)

    def test_command_line_paths(self):
        for answers in ("answers.jsonl:stream", "NUL", "con.jsonl", "C:answers.jsonl", "answers.jsonl.", "a?.jsonl"):
            with self.subTest(answers=answers):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = from_intake.main(["--out", str(self.scripted), "--expected", str(self.expected_path),
                                             "--answers", str(self.root / answers) if answers[1:2] != ":" else answers])
                self.assertEqual(code, 2, err.getvalue())
        for out in ("C:stream", "NUL", "records:x"):
            with self.subTest(out=out):
                code, err, answers, _ = self.convert(out)
                self.assertEqual(code, 2, err)
                self.assertFalse(answers.exists())

    def test_ordinary_relative_paths_still_work(self):
        out = self.fresh_out()
        previous = Path.cwd()
        os.chdir(out.parent)
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = from_intake.main(["--out", out.name, "--expected", str(self.expected_path),
                                         "--answers", f"relative-answers-{next(COUNTER)}.jsonl"])
            self.assertEqual(code, 0, err.getvalue())
        finally:
            os.chdir(previous)


class DeepJsonTests(Base):
    """P2-5: byte-bounded but pathologically nested JSON is invalid input (exit 2), not a traceback."""

    DEPTH = 16000

    def deep_text(self, record):
        marker = "@@DEEP@@"
        text = json.dumps(dict(record, body_segments=marker))
        return text.replace(f'"{marker}"', "[" * self.DEPTH + "]" * self.DEPTH)

    def test_deep_record_in_process(self):
        out, expected = self.solo("fictional-0007")
        path = self.record_path(out, "fictional-0007")
        path.write_text(self.deep_text(self.base["fictional-0007"]), encoding="utf-8")
        self.assertLess(path.stat().st_size, from_intake.MAX_RECORD_BYTES)
        self.assert_fails_closed(out, expected_path=expected)

    def test_deep_record_through_the_real_cli(self):
        out, expected = self.solo("fictional-0007")
        self.record_path(out, "fictional-0007").write_text(self.deep_text(self.base["fictional-0007"]), encoding="utf-8")
        answers = self.root / f"deep-answers-{next(COUNTER)}.jsonl"
        ran = subprocess.run([sys.executable, str(TOOLS / "from_intake.py"), "--out", str(out), "--expected", str(expected),
                              "--answers", str(answers)], capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(ran.returncode, 2, ran.stderr)
        self.assertNotIn("Traceback", ran.stderr)
        self.assertFalse(answers.exists())

    def test_deep_expected_file(self):
        row = json.loads(self.lines["fictional-0007"])
        marker = "@@DEEP@@"
        text = json.dumps(dict(row, mutation_tags=marker)).replace(f'"{marker}"', "[" * self.DEPTH + "]" * self.DEPTH)
        expected = self.root / f"deep-expected-{next(COUNTER)}.jsonl"
        expected.write_text(text + "\n", encoding="utf-8")
        out, _ = self.solo("fictional-0007")
        self.assert_fails_closed(out, expected_path=expected)


class AtomicWriteTests(Base):
    """P2-6: a failed write never leaves a partial answers file or temp file; an existing file is never replaced."""

    def failing_open(self, folder, allow=0):
        real_open = Path.open
        written = []

        class Failing:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()
                return False

            def write(self, text):
                self.handle.write(text[:50])
                self.handle.flush()
                written.append(len(text[:50]))
                raise OSError("disk full")

            def __getattr__(self, name):
                return getattr(self.handle, name)

        def patched(self, mode="r", *args, **kwargs):
            handle = real_open(self, mode, *args, **kwargs)
            return Failing(handle) if ("x" in mode or "w" in mode) and self.parent == folder else handle
        return mock.patch.object(Path, "open", patched), written

    def test_disk_full_during_write_leaves_nothing(self):
        folder = self.root / f"atomic-{next(COUNTER)}"
        folder.mkdir()
        answers = folder / "answers.jsonl"
        patch, written = self.failing_open(folder)
        err = io.StringIO()
        with patch, contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = from_intake.main(["--out", str(self.scripted), "--expected", str(self.expected_path), "--answers", str(answers)])
        self.assertEqual(code, 2, err.getvalue())
        self.assertTrue(written, "the injected failure must have fired")
        self.assertEqual(list(folder.iterdir()), [], "no partial answers file and no temp file may remain")
        # A retry after the failure succeeds (nothing blocks the path).
        code, err2, _, _ = self.convert(self.scripted, answers=answers)
        self.assertEqual(code, 0, err2)
        self.assertEqual([p.name for p in folder.iterdir()], ["answers.jsonl"])

    def test_existing_answers_survive_a_late_collision(self):
        folder = self.root / f"atomic-{next(COUNTER)}"
        folder.mkdir()
        answers = folder / "answers.jsonl"
        real_convert = from_intake.convert

        def convert_then_collide(*args):
            result = real_convert(*args)
            answers.write_text("someone else\n")
            return result
        err = io.StringIO()
        with mock.patch.object(from_intake, "convert", convert_then_collide), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = from_intake.main(["--out", str(self.scripted), "--expected", str(self.expected_path), "--answers", str(answers)])
        self.assertEqual(code, 2, err.getvalue())
        self.assertEqual(answers.read_text(), "someone else\n")
        self.assertEqual([p.name for p in folder.iterdir()], ["answers.jsonl"])


class RealRunnerPendingTests(Base):
    """Genuine pending outcomes from the real runner on a small drop: kept as unsure/needs_a_look, never invented."""

    def mini(self, files):
        number = next(COUNTER)
        drop = self.root / f"mini-drop-{number}"
        drop.mkdir()
        template = json.loads(self.lines["fictional-0001"])
        lines, mapping = [], {}
        for name, data in files.items():
            (drop / name).write_bytes(data)
            digest = sha256(data).hexdigest()
            lines.append(json.dumps(dict(template, id=name[:-4], sha256=digest)))
            mapping[digest] = {"category": "order", "lane": "order", "reason_code": "new_order"}
        expected = self.root / f"mini-expected-{number}.jsonl"
        expected.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = self.root / f"mini-out-{number}"
        intake_run(drop, out, FakeProvider(mapping))
        return out, expected

    def records(self, out):
        return {json.loads(p.read_text())["source_name"]: json.loads(p.read_text()) for p in (out / "records").glob("*.json")}

    def test_duplicate_conflict_and_parse_failure_map_to_pending(self):
        base = (self.set / "fictional-0001.eml").read_bytes()
        conflicting = base.replace(b"Subject: ", b"Subject: other ", 1)
        out, expected = self.mini({"fictional-0001.eml": base, "fictional-0002.eml": base,
                                   "fictional-0003.eml": conflicting, "fictional-0004.eml": b"not an email at all"})
        reasons = {name: r["reason_code"] for name, r in self.records(out).items()}
        self.assertEqual(reasons["fictional-0002.eml"], "DUPLICATE")
        self.assertEqual(reasons["fictional-0003.eml"], "CONFLICT")
        self.assertEqual(reasons["fictional-0004.eml"], "PARSE_FAILED")
        code, err, answers, summary = self.convert(out, expected)
        self.assertEqual(code, 0, err)
        rows = self.answer_rows(answers)
        for fixture_id in ("fictional-0002", "fictional-0003", "fictional-0004"):
            self.assertEqual(rows[fixture_id], {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"})
        self.assertEqual(json.loads(summary)["local_reason_codes_omitted"], {"CONFLICT": 1, "DUPLICATE": 1, "PARSE_FAILED": 1, "TEXT_ONLY_ORDER": 1})

    def test_real_oversized_email_is_rejected_for_its_expected_id(self):
        big = b"From: a@b.example\r\nSubject: x\r\n\r\n" + b"A" * (MAX_EMAIL + 1)
        out, expected = self.mini({"fictional-0001.eml": big})
        (record,) = self.records(out).values()
        self.assertEqual(record["source_hash_kind"], "bounded_prefix_and_size")
        self.assert_fails_closed(out, "cannot be bound", expected)

    def test_duplicate_must_point_at_a_record_with_the_same_intake_id(self):
        base = (self.set / "fictional-0001.eml").read_bytes()
        out, expected = self.mini({"fictional-0001.eml": base, "fictional-0002.eml": base})
        other = next(r for n, r in self.records(out).items() if n == "fictional-0002.eml")
        path = out / "records" / (other["record_id"] + ".json")
        record = json.loads(path.read_text())
        record["duplicate_of"] = record["record_id"]  # points at itself
        path.write_text(json.dumps(record))
        self.assert_fails_closed(out, "duplicate_of is not a record of this run", expected)


class DecisionTests(Base):
    def test_changes_cancellations_quotes_are_needs_a_look_from_the_runner(self):
        code, err, answers, _ = self.convert(self.scripted)
        for row in self.answer_rows(answers).values():
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

    def test_perfect_script_keeps_the_runner_lanes(self):
        mapping = perfect_map(self.rows)
        scripted = self.root / "perfect.json"
        scripted.write_text(json.dumps(mapping), encoding="utf-8")
        summary, scored, _ = self.pipeline("perfect", scripted)
        self.assertEqual(scored.returncode, 0, scored.stderr)
        result = json.loads(scored.stdout)
        # The runner (text-only orders are TEXT_ONLY_ORDER there) decides: 50 order / 110 needs_a_look / 40 not_an_order.
        self.assertEqual(summary["answers_by_lane"], {"needs_a_look": 110, "not_an_order": 40, "order": 50})
        self.assertEqual(summary["local_reason_codes_omitted"], {"TEXT_ONLY_ORDER": 70})
        self.assertEqual(result["order_precision"], 1.0)
        self.assertEqual(result["order_recall"], 50 / 120)

    def test_scripted_results_with_one_wrongly_dropped_order_fail_the_scorer(self):
        victim = next(r for r in self.rows if r["category"] == "order" and r["number_of_orders"] > 1
                      and r["where_order"]["attachments"] and not r["where_order"]["body"])
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
        # Perfect script: order 50, needs_a_look 110, not_an_order 40. The victim moves from order to not_an_order.
        self.assertEqual(result["true_order_emails"], 120)
        self.assertEqual(summary["local_reason_codes_omitted"], {"TEXT_ONLY_ORDER": 70})
        self.assertEqual(summary["answers_by_lane"], {"needs_a_look": 110, "not_an_order": 41, "order": 49})
        self.assertEqual(result["lane_confusion"]["order"], {"needs_a_look": 70, "not_an_order": 1, "order": 49})


if __name__ == "__main__":
    unittest.main()
