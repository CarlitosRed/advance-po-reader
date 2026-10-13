"""Tests for tools/email-testset/from_intake.py: runner --out folder -> scorer answers.jsonl.

Fictional data only, offline, fake provider only. Bypass-first: most tests damage a
real runner output folder and require the converter to fail closed (exit 2, no file).
"""

import base64
import contextlib
import copy
import errno
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from collections import Counter
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
from email_intake import parser as intake_parser  # noqa: E402
from email_intake import locking as intake_locking  # noqa: E402
from email_intake import runner as intake_runner  # noqa: E402
from email_intake.body_pdf import render  # noqa: E402
from email_intake.ledger import LedgerError  # noqa: E402
from email_intake.providers import FakeProvider, LiveProvider  # noqa: E402
from email_intake.runner import run as intake_run  # noqa: E402
from email_intake.senders import KnownSenders  # noqa: E402
from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON, LANGUAGES, MUTATIONS  # noqa: E402
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
        own = self.base[fixture_id]["intake_id"]
        self.edit(out, fixture_id, lambda r: r["reader_files"][0].update(file=r["reader_files"][0]["file"].replace(own, other)))
        self.assert_fails_closed(out, "reader_files entry field file")

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
    if len(path) == 3 and path[0] == "attachment_manifest" and path[2] == "disposition":
        # The parser keeps any non-empty lower-cased disposition token (round 2, item 1: custom, form-data, ...).
        return type(value) is str and value != "" and value == value.strip().lower() and ";" not in value
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

    def run_main(self, answers):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = from_intake.main(["--out", str(self.scripted), "--expected", str(self.expected_path), "--answers", str(answers)])
        return code, err.getvalue()

    def test_no_hard_link_support_refuses_and_never_overwrites_another_writer(self):
        # B03. Deterministic syscall schedule: os.link fails as on a filesystem without hard links, and another
        # writer creates the answers file either before the link attempt or just before a fallback replace.
        unsupported = OSError(getattr(errno, "EOPNOTSUPP", 95), "hard links not supported here")
        other = "other complete answers\n"
        real_replace, real_rename = os.replace, os.rename
        for timing in ("before-link", "before-fallback-replace"):
            with self.subTest(timing=timing):
                folder = self.root / f"nolink-{next(COUNTER)}"
                folder.mkdir()
                answers = folder / "answers.jsonl"
                moved = []

                def link(src, dst, *args, **kwargs):
                    if timing == "before-link":
                        Path(dst).write_text(other)
                    raise unsupported

                def replace(src, dst, *args, **kwargs):
                    moved.append(dst)
                    if Path(dst) == answers and not answers.exists():
                        answers.write_text(other)  # the other writer wins the race after any absence check
                    return real_replace(src, dst, *args, **kwargs)

                def rename(src, dst, *args, **kwargs):
                    moved.append(dst)
                    return real_rename(src, dst, *args, **kwargs)
                with mock.patch.object(os, "link", link), mock.patch.object(os, "replace", replace), \
                        mock.patch.object(os, "rename", rename):
                    code, err = self.run_main(answers)
                self.assertEqual(code, 2, err)
                self.assertEqual(moved, [], "no replace/rename publication without hard links")
                if timing == "before-link":
                    self.assertEqual(answers.read_text(), other)
                    self.assertEqual([p.name for p in folder.iterdir()], ["answers.jsonl"])
                else:
                    self.assertEqual(list(folder.iterdir()), [], "refused: no answers and no temp file")

    def test_cleanup_never_deletes_a_temp_file_it_did_not_create(self):
        # B04. A leftover temp of another process (old fixed name: target + PID) stays untouched, and a forced
        # collision on the unique temp name fails closed without deleting the file that was already there.
        folder = self.root / f"temp-owner-{next(COUNTER)}"
        folder.mkdir()
        answers = folder / "temp-collision.jsonl"
        stale = folder / f".temp-collision.jsonl.tmp-{os.getpid()}"
        stale.write_text("preexisting unowned temp\n")
        fixed = uuid.UUID(int=0xF1C7)
        collide = folder / f".temp-collision.jsonl.{fixed.hex}.tmp"
        collide.write_text("preexisting unowned temp\n")
        with mock.patch.object(uuid, "uuid4", return_value=fixed):
            code, err = self.run_main(answers)
        self.assertEqual(code, 2, err)
        self.assertFalse(answers.exists())
        for path in (stale, collide):
            self.assertEqual(path.read_text(), "preexisting unowned temp\n", path.name)
        code, err = self.run_main(answers)  # no forced collision: succeeds and still leaves both files alone
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([answers.name, stale.name, collide.name]))
        for path in (stale, collide):
            self.assertEqual(path.read_text(), "preexisting unowned temp\n", path.name)


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


# ---------------------------------------------------------------------------------------------------------
# Genuine producer output. Fictional emails with unusual but parseable headers and bodies go through the
# real parser and runner (fake provider, and the real LiveProvider wired to offline stubs: no network, no
# key, no spend). Every record they produce must convert (exit 0). A replay oracle built on the real runner
# then decides, for every single-field mutation of those records, whether the runner could have written
# the mutated folder; the converter must accept exactly the reachable ones.

PDF = b"%PDF-1.4\n% fictional purchase order\n"
PNG = b"\x89PNG\r\n\x1a\nfictional"
JPG = b"\xff\xd8\xfffictional"
CRLF = b"\r\n"
INTAKE_SOURCE = ROOT / "email_intake"


def mime_part(content_type, payload, disposition=None):
    headers = [b"Content-Type: " + content_type.encode()]
    if disposition is not None:
        headers.append(b"Content-Disposition: " + disposition.encode())
    headers.append(b"Content-Transfer-Encoding: base64")
    return headers, base64.encodebytes(payload).replace(b"\n", CRLF).rstrip(CRLF)


def pdf_part(tag, disposition='attachment; filename="po.pdf"'):
    return mime_part("application/pdf", PDF + tag.encode(), disposition)


def eml(stem, body="Fictional order 1001 is attached.", parts=(), *, subject="Fictional purchase order",
        message_id="own", body_type="text/plain; charset=utf-8", raw_body=None,
        sender="Fictional Buyer <buyer@fictional.example>"):
    head = [b"From: " + sender.encode(), b"To: intake@fictional.example",
            b"Subject: " + subject.encode(), b"MIME-Version: 1.0"]
    if message_id == "own":
        head.append(f"Message-ID: <{stem}@fictional.example>".encode())
    elif message_id:
        head.append(f"Message-ID: {message_id}".encode())
    text = raw_body if raw_body is not None else (body.encode("utf-8") if body is not None else None)
    if not parts:
        return CRLF.join(head + [b"Content-Type: " + body_type.encode(), b"", text or b""])
    lines = head + [b'Content-Type: multipart/mixed; boundary="FICTIONAL-BOUNDARY"', b""]
    chunks = ([([b"Content-Type: " + body_type.encode()], text)] if text is not None else []) + list(parts)
    for headers, payload in chunks:
        lines += [b"--FICTIONAL-BOUNDARY", *headers, b"", payload]
    return CRLF.join(lines + [b"--FICTIONAL-BOUNDARY--", b""])


def body_of(size):
    """An ASCII body of exactly `size` bytes that the parser keeps unchanged (already stripped)."""
    return ("Fictional order line.\n" * (size // 22 + 1))[:size - 1] + "Z"


def decided(category):
    return intake_contract.decision(category)


def held(reason):
    return {"category": "unsure", "lane": "needs_a_look", "reason_code": reason}


MISMATCH = {"category": "order", "lane": "not_an_order", "reason_code": "new_order"}  # contract.validate -> CONFLICT


def fake_corpus():
    """(stem, bytes, scripted classifier result) for the fake-provider run, in processing order."""
    items = []

    def add(stem, data, script="order"):
        items.append((stem, data, script))
    add("c01-disp-custom", eml("c01", parts=[pdf_part("c01", 'custom; filename="po.pdf"')]))
    add("c02-disp-form-data", eml("c02", parts=[pdf_part("c02", 'form-data; name="file"; filename="invoice.pdf"')]), "invoice")
    add("c03-disp-token", eml("c03", parts=[pdf_part("c03", 'x-fictional.tok_1; filename="po.pdf"')]), "change")
    add("c04-upper-case", eml("c04", parts=[mime_part("APPLICATION/PDF", PDF + b"c04", 'ATTACHMENT; filename="PO.PDF"')]))
    add("c05-spaced-media", eml("c05", parts=[mime_part("application / pdf", PDF + b"c05", 'attachment; filename="po.pdf"')]))
    add("c06-unnamed-octet", eml("c06", parts=[mime_part("application/octet-stream", b"fictional bytes c06")]))
    add("c07-text-attachment", eml("c07", parts=[mime_part("text/plain", b"fictional notes c07", 'custom; filename="notes.txt"')]))
    add("c08-three-documents", eml("c08", parts=[pdf_part("c08"), mime_part("image/png", PNG + b"c08", 'inline; filename="logo.png"'),
                                                 mime_part("image/jpeg", JPG + b"c08", 'attachment; filename="photo.JPEG"')]))
    add("c09-wrong-magic", eml("c09", parts=[mime_part("image/png", JPG + b"c09", 'attachment; filename="scan.png"')]))
    add("c10-attachment-only", eml("c10", body=None, parts=[pdf_part("c10")]))
    add("c11-empty-no-attachment", eml("c11", body=""))
    add("c12-empty-unsupported", eml("c12", body=None, parts=[mime_part("application/zip", b"PK\x03\x04c12", 'attachment; filename="po.zip"')]))
    add("c13-html-only", eml("c13", body="<p>Fictional <b>order</b> 1013</p><script>hidden()</script>",
                             body_type="text/html; charset=utf-8", parts=[pdf_part("c13")]))
    add("c14-no-message-id", eml("c14", message_id=None, parts=[pdf_part("c14")]), "spam")
    add("c15-quoted-only", eml("c15", body="> Earlier fictional order 1015\n> second quoted line", parts=[pdf_part("c15")]), "quote_request")
    add("c16-pdf-limit-control", eml("c16", body="Fictional order\x07 1016", parts=[pdf_part("c16")]))
    add("c17-pdf-limit-lines", eml("c17", body="\n".join(f"Line {i} of fictional order 1017" for i in range(70)), parts=[pdf_part("c17")]))
    add("c18-pdf-limit-emoji", eml("c18", body="Fictional order 1018 \U0001F642", parts=[pdf_part("c18")]))
    add("c19-body-at-limit", eml("c19", body=body_of(intake_parser.MAX_BODY), parts=[pdf_part("c19")]))
    add("c20-max-attachments", eml("c20", parts=[pdf_part(f"c20-{i}") for i in range(intake_parser.MAX_ATTACHMENTS)]))
    add("c21-too-many-attachments", eml("c21", parts=[pdf_part(f"c21-{i}") for i in range(intake_parser.MAX_ATTACHMENTS + 1)]))
    add("c22-body-over-limit", eml("c22", body=body_of(intake_parser.MAX_BODY + 1), parts=[pdf_part("c22")]))
    add("c23-not-an-email", b"not an email at all")
    add("c24-text-only-order", eml("c24"))
    add("c25-fake-invalid", eml("c25", parts=[pdf_part("c25")]), "garbage")
    add("c26-fake-conflict", eml("c26", parts=[pdf_part("c26")]), MISMATCH)
    add("c27-encoded-words", eml("c27", subject="=?utf-8?q?Pedido_n=C3=BAmero_1027?=",
                                 parts=[pdf_part("c27", "attachment; filename*=utf-8''pedido-%C3%BA.pdf")]))
    add("c28-cp1252-undeclared", eml("c28", raw_body=b"Pedido de caf\xe9 1028", body_type="text/plain", parts=[pdf_part("c28")]),
        "other_business")
    add("c29-inline-image-status", eml("c29", parts=[mime_part("image/png", PNG + b"c29", 'inline; filename="chart.png"')]), "status_question")
    add("c30-scripted-unsure", eml("c30", parts=[pdf_part("c30")]), "unsure")
    add("c31-cancellation", eml("c31", parts=[pdf_part("c31")]), "cancellation")
    original = eml("c40", parts=[pdf_part("c40")])
    add("c40-original", original)
    add("c41-duplicate", original)  # identical bytes: DUPLICATE of c40
    add("c42-mid-first", eml("c42", message_id="<shared-1042@fictional.example>", body="First fictional order 1042", parts=[pdf_part("c42")]))
    add("c43-mid-conflict", eml("c43", message_id="<shared-1042@fictional.example>", body="Second fictional order 1043",
                                parts=[pdf_part("c43")]))
    add("c44-mid-conflict-empty", eml("c44", message_id="<shared-1042@fictional.example>", body=None, parts=[pdf_part("c44")]))
    add("c45-shared-document", eml("c45", body="Status of fictional order 1040", parts=[pdf_part("c40")]), "status_question")
    return items


class StubLedger:
    """Offline stand-in for SpendLedger: no database, no spend."""

    def __init__(self, error=None, known=True):
        self.error, self.known = error, known

    def reserve(self, intake_id):
        if self.error:
            raise LedgerError(self.error)
        return "fictional-attempt"

    def finish(self, attempt, usage, reason):
        # Like SpendLedger.finish: usage is "known" only with integer token counts inside the reservation.
        return self.known and all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens"))


def offline_send(status, body):
    def send(request, key):  # replaces the HTTPS transport: nothing leaves the process
        return status, copy.deepcopy(body)
    return send


def completed(text):
    return {"status": "completed", "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def live_provider(target, *, known=True):
    """The real LiveProvider on offline stubs, configured so that its own code returns `target` when it can."""
    kwargs = dict(enabled=True, api_key="fictional-offline-placeholder", ledger=StubLedger(known=known),
                  send=offline_send(500, {}))
    reason = target.get("reason_code") if isinstance(target, dict) else None
    if isinstance(target, dict) and reason not in intake_contract.LOCAL_REASONS:
        kwargs["send"] = offline_send(200, completed(json.dumps(target)))
    elif reason == "LIVE_DISABLED":
        kwargs["enabled"] = False
    elif reason == "MISSING_KEY":
        kwargs["api_key"] = None
    elif reason == "LEDGER":
        kwargs["ledger"] = None
    elif reason == "CAP":
        kwargs["ledger"] = StubLedger("CAP")
    elif reason == "INCOMPLETE":
        kwargs["send"] = offline_send(200, {"status": "incomplete"})
    elif reason == "REFUSED":
        kwargs["send"] = offline_send(200, {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "refusal", "refusal": "fictional refusal"}]}]})
    elif reason == "INVALID":
        kwargs["send"] = offline_send(200, {"status": "completed", "output": "not a list"})
    elif reason == "CONFLICT":
        kwargs["send"] = offline_send(200, completed(json.dumps(MISMATCH)))
    # TRANSPORT_PENDING (status 500) and LIMIT (request over INPUT_BOUND) come from the default wiring.
    provider = LiveProvider(**kwargs)
    assert provider.send is not None and provider.send.__name__ == "send" and provider.send.__module__ == __name__
    return provider


def live_corpus():
    """(stem, bytes, provider) for sequential live runs into one folder (each run adds one email)."""
    pdf = lambda tag: [pdf_part(tag)]  # noqa: E731
    return [
        ("l01-live-disabled", eml("l01", parts=pdf("l01")), live_provider(held("LIVE_DISABLED"))),
        ("l02-missing-key", eml("l02", parts=pdf("l02")), live_provider(held("MISSING_KEY"))),
        ("l03-no-ledger", eml("l03", parts=pdf("l03")), live_provider(held("LEDGER"))),
        ("l04-request-limit", eml("l04", body=body_of(7000), parts=pdf("l04")), live_provider(held("LIMIT"))),
        ("l05-cap", eml("l05", parts=pdf("l05")), live_provider(held("CAP"))),
        ("l06-transport", eml("l06", parts=pdf("l06")), live_provider(held("TRANSPORT_PENDING"))),
        ("l07-incomplete", eml("l07", parts=pdf("l07")), live_provider(held("INCOMPLETE"))),
        ("l08-refused", eml("l08", parts=pdf("l08")), live_provider(held("REFUSED"))),
        ("l09-invalid", eml("l09", parts=pdf("l09")), live_provider(held("INVALID"))),
        ("l10-conflict", eml("l10", parts=pdf("l10")), live_provider(held("CONFLICT"))),
        ("l11-order", eml("l11", parts=pdf("l11")), live_provider(decided("order"))),
        ("l12-usage-unknown", eml("l12", parts=pdf("l12")), live_provider(decided("order"), known=False)),
        ("l13-reserve-pending", eml("l13", parts=pdf("l13")),
         LiveProvider(enabled=True, api_key="fictional-offline-placeholder", ledger=StubLedger("TRANSPORT_PENDING"),
                      send=offline_send(500, {}))),
        ("l14-text-only", eml("l14"), live_provider(decided("order"))),
    ]


KNOWN = KnownSenders(frozenset({"buyer@fictional.example"}), frozenset())  # the runner's --known-senders list
STRANGER = "Fictional Stranger <stranger@elsewhere.example>"


def policy_corpus():
    """(stem, bytes, scripted result) for one --known-senders run (the runner's UNKNOWN_SENDER hold)."""
    known_order = eml("p01", parts=[pdf_part("p01")])
    stranger_order = eml("p02", sender=STRANGER, parts=[pdf_part("p02")])
    return [
        ("p01-known-order", known_order, "order"),
        ("p02-unknown-order", stranger_order, "order"),
        ("p03-unknown-duplicate", stranger_order, "order"),
        ("p04-unknown-attachment-only", eml("p04", body=None, sender=STRANGER, parts=[pdf_part("p04")]), "order"),
        ("p05-known-attachment-only", eml("p05", body=None, parts=[pdf_part("p05")]), "order"),
        ("p06-unknown-text-only", eml("p06", sender=STRANGER), "order"),
        ("p07-known-duplicate", known_order, "order"),
        ("p08-unknown-mid-conflict", eml("p08", sender=STRANGER, message_id="<p01@fictional.example>",
                                         parts=[pdf_part("p08")]), "order"),
        ("p09-group-sender", eml("p09", sender="Buyers: buyer@fictional.example;", parts=[pdf_part("p09")]), "order"),
        ("p10-known-text-only", eml("p10"), "order"),
        ("p11-known-quiet", eml("p11", parts=[pdf_part("p11")]), "spam"),
    ]


def expected_rows(path, names, data):
    template = {"category": "unsure", "lane": "needs_a_look", "where_order": {"body": False, "attachments": []},
                "number_of_orders": 0, "language": sorted(LANGUAGES)[0], "mutation_tags": [sorted(MUTATIONS)[0]]}
    path.write_text("".join(json.dumps(dict(template, id=name, sha256=sha256(data[name]).hexdigest())) + "\n"
                            for name in names), encoding="utf-8")
    return path


def read_records(out):
    return {json.loads(p.read_text(encoding="utf-8"))["source_name"][:-4]: json.loads(p.read_text(encoding="utf-8"))
            for p in (out / "records").glob("*.json")}


_GENUINE = {}


def genuine():
    """Build the genuine corpus once: {"fake"/"live"/"policy": (out, expected path, {stem: record}, {stem: bytes},
    scripted results)}."""
    if "policy" in _GENUINE:
        return _GENUINE
    if "temp" in _GENUINE:
        _GENUINE.pop("temp").cleanup()
    temp = tempfile.TemporaryDirectory(prefix="fictional-genuine-")
    _GENUINE["temp"] = temp
    root = Path(temp.name)
    items = fake_corpus()
    data = {stem: raw for stem, raw, _ in items}
    drop = root / "fake-drop"
    drop.mkdir()
    for stem, raw, _ in items:
        (drop / f"{stem}.eml").write_bytes(raw)
    results = {sha256(raw).hexdigest(): s if s == "garbage" or isinstance(s, dict) else decided(s) for _, raw, s in items}
    intake_run(drop, root / "fake-out", FakeProvider(results))
    _GENUINE["fake"] = (root / "fake-out", expected_rows(root / "fake-expected.jsonl", list(data), data),
                        read_records(root / "fake-out"), data, results)
    live = live_corpus()
    ldata = {stem: raw for stem, raw, _ in live}
    ldrop = root / "live-drop"
    ldrop.mkdir()
    for stem, raw, provider in live:
        (ldrop / f"{stem}.eml").write_bytes(raw)
        intake_run(ldrop, root / "live-out", provider)
    _GENUINE["live"] = (root / "live-out", expected_rows(root / "live-expected.jsonl", list(ldata), ldata),
                        read_records(root / "live-out"), ldata, None)
    pitems = policy_corpus()
    pdata = {stem: raw for stem, raw, _ in pitems}
    pdrop = root / "policy-drop"
    pdrop.mkdir()
    for stem, raw, _ in pitems:
        (pdrop / f"{stem}.eml").write_bytes(raw)
    presults = {sha256(raw).hexdigest(): decided(s) for _, raw, s in pitems}
    intake_run(pdrop, root / "policy-out", FakeProvider(presults), known_senders=KNOWN)
    _GENUINE["policy"] = (root / "policy-out", expected_rows(root / "policy-expected.jsonl", list(pdata), pdata),
                          read_records(root / "policy-out"), pdata, presults)
    return _GENUINE


def tearDownModule():
    if "temp" in _GENUINE:
        _GENUINE["temp"].cleanup()


def same(a, b):
    """Deep equality that also requires equal JSON types (True is not 1)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def source_literals(pattern, *files):
    return {m for name in files for m in re.findall(pattern, (INTAKE_SOURCE / name).read_text(encoding="utf-8"))}


PARSE_ERRORS = frozenset(source_literals(r'ParseError\("([A-Z_]+)"\)', "parser.py", "runner.py"))


def parser_view(record):
    """What parse() could have returned for this record, per the parser's code; None when outside its domain.

    Re-derives what the parser derives (segments, attachment ids); keeps what only the source bytes decide
    (header texts, body text, file names, media types, dispositions, sizes, digests, magic-byte verdict)
    after checking it lies in the parser's output domain."""
    keys = ("sender", "subject", "message_id", "body", "body_segments")
    present = [key in record for key in keys]
    if not any(present):
        reason = record.get("reason_code")
        return ("refused", reason) if type(reason) is str and reason in PARSE_ERRORS else None
    if not all(present):
        return None
    sender, subject, mid, body = (record[k] for k in keys[:4])
    if not (type(sender) is str and sender and type(subject) is str and subject):
        return None
    if not (mid is None or (type(mid) is str and re.fullmatch(r"<[^\s<>@]+@[^\s<>@]+>", mid))):
        return None
    if type(body) is not str or body != body.strip():
        return None
    try:
        if len(body.encode("utf-8")) > intake_parser.MAX_BODY:
            return None
    except UnicodeError:
        return None
    manifest = record.get("attachment_manifest")
    if type(manifest) is not list or len(manifest) > intake_parser.MAX_ATTACHMENTS:
        return None
    attachments = []
    for index, item in enumerate(manifest):
        fields = ("filename", "media_type", "byte_length", "sha256", "disposition", "supported")
        if type(item) is not dict or not all(f in item for f in fields):
            return None
        name, media, size, digest, disposition, supported = (item[f] for f in fields)
        # Message.get_content_type(): lower-cased text before ';' with one '/'; message/* is refused.
        if not (type(media) is str and media == media.strip().lower() and ";" not in media and media.count("/") == 1
                and not media.startswith("message/")):
            return None
        # get_content_disposition() or "attachment": lower-cased text before ';', never empty.
        if not (type(disposition) is str and disposition and disposition == disposition.strip().lower() and ";" not in disposition):
            return None
        if not (type(name) is str and name and type(size) is int and size >= 0 and type(digest) is str
                and re.fullmatch(r"[0-9a-f]{64}", digest) and type(supported) is bool):
            return None
        extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if supported and not (media in intake_parser.SUPPORTED and extension in intake_parser.SAFE_EXTENSIONS
                              and size >= len(intake_parser.SUPPORTED[media][1])):
            return None
        attachments.append({"attachment_id": f"a{index + 1:03}", "filename": name, "media_type": media,
                            "byte_length": size, "sha256": digest, "disposition": disposition, "supported": supported})
    segments = []
    for line in body.splitlines(keepends=True):
        kind = "quoted" if line.lstrip().startswith(">") else "newest"
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["text"] += line
        else:
            segments.append({"kind": kind, "text": line})
    return ("parsed", (sender, subject, mid, body, segments, attachments))


def fake_script(target):
    if same(target, held("INVALID")):
        return "garbage"
    if same(target, held("CONFLICT")):
        return copy.deepcopy(MISMATCH)
    return copy.deepcopy(target)


class Replay:
    """Oracle: re-run the real runner over the same email files with parse() and the classifier pinned to the
    records' content, and report whether the runner writes exactly these records."""

    def __init__(self, root, stems, data, policy=False):
        """policy: replay a --known-senders run (the folder holds sender-policy.json)."""
        self.root, self.stems, self.data, self.cache, self.runs = root, stems, data, {}, 0
        self.policy = policy

    def produce(self, records):
        kinds = {json.dumps(r.get("provider")) for r in records}
        if len(kinds) != 1 or not kinds <= {'"fake"', '"live"'}:
            return None  # one provider per folder (converter policy); unknown providers do not exist
        live = kinds == {'"live"'}
        views, sizes, targets = {}, {}, {}
        for stem, record in zip(self.stems, records):
            raw = self.data[stem]
            if raw in views:
                continue  # same bytes: the runner parses them exactly like the first record
            view = parser_view(record)
            size = record.get("source_size")
            if view is None or type(size) is not int or not 0 <= size <= MAX_EMAIL:
                return None
            if view[0] == "parsed" and sum(a["byte_length"] for a in view[1][5]) > size:
                return None
            views[raw], sizes[raw] = view, size
            targets[sha256(raw).hexdigest()] = record.get("classification")
        key = json.dumps([live, [[views[self.data[s]], sizes[self.data[s]]] for s in dict.fromkeys(self.stems)],
                          sorted(targets.items(), key=lambda kv: kv[0])], sort_keys=True, default=str)
        if key not in self.cache:
            self.cache[key] = self.run(views, sizes, targets, live)
        return self.cache[key]

    def run(self, views, sizes, targets, live):
        self.runs += 1
        number = next(COUNTER)
        drop, out = self.root / f"replay-drop-{number}", self.root / f"replay-out-{number}"
        drop.mkdir(parents=True)
        for stem in self.stems:
            (drop / f"{stem}.eml").write_bytes(self.data[stem])

        def parse(raw, *, sender_hint=False):
            kind, value = views[raw]
            if kind == "refused":
                raise intake_parser.ParseError(value)
            sender, subject, mid, body, segments, attachments = copy.deepcopy(value)
            # The sender hold is pinned like the classifier: a record held as UNKNOWN_SENDER has a sender
            # outside the list; any other parsed record of a policy run has a listed one.
            unknown = same(targets.get(sha256(raw).hexdigest()), held("UNKNOWN_SENDER"))
            address = None if unknown or not sender_hint else next(iter(KNOWN.addresses))
            return intake_parser.Parsed(sender, subject, mid, body, segments, attachments,
                                        {a["attachment_id"]: b"fictional payload" for a in attachments}, address)

        class Pinned:
            def __init__(self):
                self.live = live

            def classify(self, parsed, intake_id):
                target = targets[intake_id]
                if live:
                    return live_provider(target).classify(parsed, intake_id)
                return FakeProvider({intake_id: fake_script(target)}).classify(parsed, intake_id)
        plain = lambda path: Path(path).absolute()  # noqa: E731 (alias defence: not part of record content)
        try:
            with mock.patch.object(intake_runner, "parse", parse), mock.patch.object(os, "fsync", lambda fd: None), \
                    mock.patch.object(intake_runner, "safe_path", plain), mock.patch.object(intake_locking, "safe_path", plain):
                intake_run(drop, out, Pinned(), known_senders=KNOWN if self.policy else None)
        except Exception:  # the runner cannot write a record for these inputs
            return None
        produced = read_records(out)
        result = []
        for stem in self.stems:
            record = produced[stem]
            record["source_size"] = sizes[self.data[stem]]  # decided by the source bytes, not the runner
            result.append(record)
        shutil.rmtree(drop)
        shutil.rmtree(out)
        return result

    def reachable(self, records):
        produced = self.produce(records)
        return produced is not None and all(same(p, r) for p, r in zip(produced, records))


SWEEP_POOL = [None, True, 0, -1, "", "x", [], {}]


def well_formed_reader_entries(record):
    """Runner-shaped reader entries for this record (correct paths, digests), used as additions."""
    iid = record.get("intake_id")
    original = record.get("original") or ""
    sep = "\\" if "\\" in original else "/"
    entries = []
    for a in record.get("attachment_manifest") or []:
        if isinstance(a, dict) and a.get("media_type") in intake_parser.SUPPORTED:
            entries.append({"file": sep.join(["sources", iid, a["attachment_id"] + intake_parser.SUPPORTED[a["media_type"]][0]]),
                            "attachment_id": a["attachment_id"], "sha256": a["sha256"], "derived": False,
                            "human_selection_required": True})
    body = record.get("body")
    if isinstance(body, str) and body:
        try:
            pdf = render(body)
        except (ValueError, UnicodeError):
            pdf = None
        if pdf is not None:
            entries.append({"file": sep.join(["sources", iid, "derived-body.pdf"]), "sha256": sha256(pdf).hexdigest(),
                            "derived": True, "source_text_sha256": sha256(body.encode()).hexdigest(),
                            "human_selection_required": True})
    return entries


def single_field_mutations(record, peers):
    """Every single-field deletion, addition and swap at every dict key and list index of a record."""
    result = []
    for path in leaf_paths(record):
        node = get_at(record, path)
        if path:
            step, parent = path[-1], get_at(record, path[:-1])
            if isinstance(step, str):
                result.append(("delete", path, None))
            else:
                result += [("drop-element", path, None), ("repeat-element", path, None)]
                if step + 1 < len(parent):
                    result.append(("swap-elements", path, None))
            values, seen = [], set()
            for peer in peers:
                try:
                    values.append(get_at(peer, path))
                except (KeyError, IndexError, TypeError):
                    pass
            for value in SWEEP_POOL + values:
                marker = json.dumps(value, sort_keys=True)
                if marker not in seen and not same(value, node) and len(seen) < 16:
                    seen.add(marker)
                    result.append(("set", path, value))
        if isinstance(node, dict):
            result.append(("add", path, ("unexpected", True)))
            added = set()
            for peer in peers:
                try:
                    other = get_at(peer, path)
                except (KeyError, IndexError, TypeError):
                    continue
                if isinstance(other, dict):
                    for key in other.keys() - node.keys() - added:
                        added.add(key)
                        result.append(("add", path, (key, other[key])))
            keys = sorted(node)
            result += [("swap-keys", path, pair) for pair in itertools.combinations(keys, 2)
                       if not same(node[pair[0]], node[pair[1]])]
        if isinstance(node, list):
            appended = set()
            extra = well_formed_reader_entries(record) if path == ("reader_files",) else []
            for peer in peers:
                try:
                    other = get_at(peer, path)
                except (KeyError, IndexError, TypeError):
                    continue
                if isinstance(other, list):
                    extra += other[:2]
            for element in extra:
                marker = json.dumps(element, sort_keys=True)
                if marker not in appended and not any(same(element, e) for e in node):
                    appended.add(marker)
                    result.append(("append", path, element))
    return result


def apply_mutation(record, kind, path, arg):
    record = copy.deepcopy(record)
    node = get_at(record, path)
    if kind in ("set", "delete", "drop-element", "repeat-element", "swap-elements"):
        parent, step = get_at(record, path[:-1]), path[-1]
        if kind == "set":
            parent[step] = copy.deepcopy(arg)
        elif kind == "delete":
            del parent[step]
        elif kind == "drop-element":
            parent.pop(step)
        elif kind == "repeat-element":
            parent.insert(step, copy.deepcopy(parent[step]))
        else:
            parent[step], parent[step + 1] = parent[step + 1], parent[step]
    elif kind == "add":
        node[arg[0]] = copy.deepcopy(arg[1])
    elif kind == "swap-keys":
        node[arg[0]], node[arg[1]] = node[arg[1]], node[arg[0]]
    else:
        node.append(copy.deepcopy(arg))
    return record


def converter_exit(out, expected):
    """from_intake.main's decision without publishing a file: 0 when convert() succeeds, 2 when it refuses."""
    try:
        from_intake.convert(out, expected)
    except (OSError, ValueError, RecursionError):
        return 2
    return 0


def converter_exit_texts(texts, expected, sender_policy=False):
    """The same decision for record files held in memory (every record and cross-record check; the
    folder and file-system checks are covered by the folder tests above)."""
    try:
        from_intake.convert_records([from_intake.record_from_text(text, Path(name)) for name, text in sorted(texts.items())],
                                    expected, sender_policy=sender_policy)
    except (ValueError, RecursionError):
        return 2
    return 0


class GenuineProducerOutputTests(unittest.TestCase):
    """B01 class: every value the real parser and runner write converts (exit 0)."""

    def convert_folder(self, kind):
        out, expected_path, records, _, _ = genuine()[kind]
        answers = Path(_GENUINE["temp"].name) / f"answers-{kind}-{next(COUNTER)}.jsonl"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = from_intake.main(["--out", str(out), "--expected", str(expected_path), "--answers", str(answers)])
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(stdout.getvalue()), records

    def test_unusual_but_parseable_emails_from_the_real_runner_convert(self):
        summary, records = self.convert_folder("fake")
        dispositions = {a["disposition"] for r in records.values() for a in r["attachment_manifest"]}
        self.assertTrue({"custom", "form-data", "x-fictional.tok_1", "inline", "attachment"} <= dispositions, dispositions)
        media = {a["media_type"] for r in records.values() for a in r["attachment_manifest"]}
        self.assertTrue({"application / pdf", "application/octet-stream", "text/plain", "application/zip"} <= media, media)
        reasons = {stem: r["reason_code"] for stem, r in records.items()}
        self.assertEqual({reasons[s] for s in ("c16-pdf-limit-control", "c17-pdf-limit-lines", "c18-pdf-limit-emoji",
                                               "c19-body-at-limit")}, {"PDF_LIMIT"})
        self.assertEqual(reasons["c21-too-many-attachments"], "LIMIT")
        self.assertEqual(reasons["c22-body-over-limit"], "LIMIT")
        self.assertEqual(reasons["c41-duplicate"], "DUPLICATE")
        self.assertEqual((reasons["c43-mid-conflict"], reasons["c44-mid-conflict-empty"]), ("CONFLICT", "CONFLICT"))
        self.assertEqual(len(records["c20-max-attachments"]["reader_files"]), intake_parser.MAX_ATTACHMENTS + 1)
        self.assertEqual([e["derived"] for e in records["c10-attachment-only"]["reader_files"]], [False])
        self.assertEqual(records["c45-shared-document"]["related_intakes"], [records["c40-original"]["intake_id"]])
        self.assertEqual(sum(summary["answers_by_lane"].values()), len(records))

    def test_every_local_reason_comes_from_genuine_records_and_maps_to_unsure(self):
        omitted = Counter()
        for kind in ("fake", "live", "policy"):
            summary, records = self.convert_folder(kind)
            omitted.update(summary["local_reason_codes_omitted"])
            self.assertEqual({r["provider"] for r in records.values()}, {"live" if kind == "live" else "fake"})
        self.assertEqual(set(omitted), set(intake_contract.LOCAL_REASONS))

    def test_converter_constants_are_derived_from_the_producer(self):
        # Every ParseError the parser/runner raise; FakeProvider = contract.validate(); LiveProvider adds its own
        # early exits, unpack() and every LedgerError message.
        self.assertEqual(PARSE_ERRORS, from_intake.PRE_PARSE_REASONS)
        self.assertEqual(from_intake.PROVIDER_PENDING["fake"], source_literals(r'pending\("([A-Z_]+)"\)', "contract.py"))
        live = (source_literals(r'pending\("([A-Z_]+)"\)', "providers.py", "contract.py")
                | source_literals(r'LedgerError\("([A-Z_]+)"\)', "ledger.py"))
        self.assertEqual(from_intake.PROVIDER_PENDING["live"], live)
        self.assertEqual(genuine()["fake"][2]["c24-text-only-order"]["note"], from_intake.TEXT_ONLY_NOTE)
        self.assertEqual(genuine()["live"][2]["l14-text-only"]["note"], from_intake.TEXT_ONLY_NOTE)
        runner_source = (INTAKE_SOURCE / "runner.py").read_text(encoding="utf-8")
        self.assertEqual(from_intake.PARSER_VERSIONS, frozenset(re.findall(r'"parser_version": "([^"]+)"', runner_source)))
        self.assertIs(from_intake.LOCAL_REASONS, intake_contract.LOCAL_REASONS)
        self.assertEqual(from_intake.EXTENSIONS, {k: v[0] for k, v in intake_parser.SUPPORTED.items()})

    def test_replay_oracle_reproduces_every_genuine_record(self):
        for kind in ("fake", "live", "policy"):
            out, _, records, data, _ = genuine()[kind]
            stems = sorted(records)
            replay = Replay(Path(_GENUINE["temp"].name) / f"oracle-check-{kind}", stems, data, policy=kind == "policy")
            self.assertTrue(replay.reachable([records[s] for s in stems]), kind)
            if kind == "policy":  # the same records without the policy marker: the runner cannot write them
                plain = Replay(Path(_GENUINE["temp"].name) / "oracle-check-no-policy", stems, data)
                self.assertFalse(plain.reachable([records[s] for s in stems]))

    def test_known_senders_run_converts_with_the_runner_hold(self):
        summary, records = self.convert_folder("policy")
        reasons = {stem: r["reason_code"] for stem, r in records.items()}
        self.assertEqual({s for s, r in reasons.items() if r == "UNKNOWN_SENDER"},
                         {"p02-unknown-order", "p03-unknown-duplicate", "p04-unknown-attachment-only",
                          "p06-unknown-text-only", "p08-unknown-mid-conflict", "p09-group-sender"})
        self.assertEqual(records["p03-unknown-duplicate"]["duplicate_of"], records["p02-unknown-order"]["record_id"])
        self.assertEqual(records["p08-unknown-mid-conflict"]["related_intakes"], [records["p01-known-order"]["intake_id"]])
        self.assertEqual((reasons["p01-known-order"], reasons["p07-known-duplicate"], reasons["p10-known-text-only"]),
                         ("new_order", "DUPLICATE", "TEXT_ONLY_ORDER"))
        self.assertEqual([e["derived"] for e in records["p05-known-attachment-only"]["reader_files"]], [False])
        self.assertEqual(records["p04-unknown-attachment-only"]["reader_files"], [])
        self.assertTrue(summary["sender_policy"])
        self.assertEqual(summary["local_reason_codes_omitted"]["UNKNOWN_SENDER"], 6)

    def test_later_run_duplicate_can_point_at_an_earlier_duplicate(self):
        """A second runner call into the same folder looks records up in file-name order, so its duplicate can
        point at an earlier DUPLICATE instead of the first record. Genuine: must convert."""
        root = Path(genuine()["temp"].name) / f"chain-{next(COUNTER)}"
        drop, out = root / "drop", root / "out"
        drop.mkdir(parents=True)
        raw = eml("m01", parts=[pdf_part("m01")])
        iid = sha256(raw).hexdigest()
        rid = lambda name: sha256((iid + name).encode()).hexdigest()  # noqa: E731
        second = next(f"m-b{i}.eml" for i in itertools.count() if rid(f"m-b{i}.eml") < rid("m-a.eml"))
        for name in ("m-a.eml", second):
            (drop / name).write_bytes(raw)
        intake_run(drop, out, FakeProvider({iid: decided("order")}))
        (drop / "m-z.eml").write_bytes(raw)
        intake_run(drop, out, FakeProvider({iid: decided("order")}))
        records = read_records(out)
        self.assertEqual(records[second[:-4]]["duplicate_of"], rid("m-a.eml"))
        self.assertEqual(records["m-z"]["duplicate_of"], rid(second), "the runner's lookup order changed")
        data = {stem: raw for stem in ("m-a", second[:-4], "m-z")}
        expected = score.read_rows(expected_rows(root / "expected.jsonl", list(data), data), expected=True)
        self.assertEqual(converter_exit(out, expected), 0)
        path = out / "records" / f"{rid('m-z.eml')}.json"
        for label, target in (("itself", rid("m-z.eml")), ("unknown", "0" * 64)):
            with self.subTest(points_at=label):
                record = dict(records["m-z"], duplicate_of=target)
                path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(converter_exit(out, expected), 2)
        path.write_text(json.dumps(records["m-z"]), encoding="utf-8")
        mutual = out / "records" / f"{rid(second)}.json"
        mutual.write_text(json.dumps(dict(records[second[:-4]], duplicate_of=rid("m-z.eml"))), encoding="utf-8")
        self.assertEqual(converter_exit(out, expected), 2, "two duplicates pointing at each other")


# Groups of records that the runner writes together (solo, or related). Each group is a separate genuine
# run, so a solo record has no relation to anything else. One record per distinct producer shape (outcome,
# reader-file list, attachment support, body state, pre-parse stop, provider result kind, relations); the
# remaining corpus records repeat one of these shapes and are covered by the genuine-corpus test.
SWEEP_GROUPS = [["c01-disp-custom"], ["c02-disp-form-data"], ["c03-disp-token"], ["c05-spaced-media"],
                ["c08-three-documents"], ["c10-attachment-only"], ["c11-empty-no-attachment"], ["c12-empty-unsupported"],
                ["c14-no-message-id"], ["c16-pdf-limit-control"], ["c21-too-many-attachments"], ["c23-not-an-email"],
                ["c24-text-only-order"], ["c25-fake-invalid"], ["c26-fake-conflict"],
                ["c40-original", "c41-duplicate", "c45-shared-document"],
                ["c42-mid-first", "c43-mid-conflict", "c44-mid-conflict-empty"]]
LIVE_SWEEP_GROUPS = [["l04-request-limit"], ["l06-transport"], ["l11-order"], ["l14-text-only"]]
POLICY_SWEEP_GROUPS = [["p01-known-order", "p07-known-duplicate", "p08-unknown-mid-conflict"],
                       ["p02-unknown-order", "p03-unknown-duplicate"], ["p04-unknown-attachment-only"],
                       ["p05-known-attachment-only"], ["p06-unknown-text-only"], ["p10-known-text-only"],
                       ["p11-known-quiet"]]
SWEEP_STATS = Counter()


class ProducerMutationSweepTests(unittest.TestCase):
    """B02 class: for every genuine record, EVERY single-field deletion/addition/swap. The converter must
    refuse (exit 2) exactly the mutated folders the real runner cannot write, and accept the rest."""

    @classmethod
    def tearDownClass(cls):
        print(f"\n[producer mutation sweep] {dict(sorted(SWEEP_STATS.items()))}", file=sys.stderr)

    def sweep(self, kind, stems):
        _, _, records, data, results = genuine()[kind]
        root = Path(_GENUINE["temp"].name) / f"sweep-{kind}-{next(COUNTER)}"
        drop, out = root / "drop", root / "out"
        drop.mkdir(parents=True)
        for stem in stems:
            (drop / f"{stem}.eml").write_bytes(data[stem])
        policy = kind == "policy"
        if kind in ("fake", "policy"):
            intake_run(drop, out, FakeProvider(results), known_senders=KNOWN if policy else None)
        else:
            for stem, raw, provider in live_corpus():
                if stem in stems:
                    intake_run(drop, out, provider)
        group = read_records(out)
        for stem in stems:  # each group run reproduces its records from the full corpus run (no relations lost)
            self.assertTrue(same(group[stem], records[stem]), stem)
        shutil.rmtree(out / "sources")
        for name in ("calls.jsonl", "quiet-digest.jsonl", ".intake-guard"):
            if (out / name).exists():
                (out / name).unlink()
        expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
        files = {stem: next(p for p in (out / "records").glob("*.json")
                            if json.loads(p.read_text(encoding="utf-8"))["source_name"] == f"{stem}.eml") for stem in stems}
        genuine_records = [group[stem] for stem in stems]
        replay = Replay(root, stems, data, policy=policy)
        self.assertEqual(converter_exit(out, expected), 0)
        self.assertTrue(replay.reachable(genuine_records))
        peers = [r for name in ("fake", "live", "policy") for r in genuine()[name][2].values()]
        texts = {files[stem].name: files[stem].read_text(encoding="utf-8") for stem in stems}
        self.assertEqual(converter_exit_texts(texts, expected, policy), 0)
        wrong = []
        for slot, stem in enumerate(stems):
            others = [p for p in peers if p["source_name"] != f"{stem}.eml"]
            for kind_, mpath, arg in single_field_mutations(group[stem], others):
                mutated = apply_mutation(group[stem], kind_, mpath, arg)
                candidate = list(genuine_records)
                candidate[slot] = mutated
                reachable = replay.reachable(candidate)
                code = converter_exit_texts(dict(texts, **{files[stem].name: json.dumps(mutated)}), expected, policy)
                SWEEP_STATS["mutations"] += 1
                SWEEP_STATS["reachable" if reachable else "impossible"] += 1
                if code != (0 if reachable else 2):
                    wrong.append((stem, kind_, mpath, json.dumps(arg)[:80], "reachable" if reachable else "impossible", code))
        SWEEP_STATS["replays"] += replay.runs
        self.assertEqual(wrong[:25], [], f"{len(wrong)} mutations where the converter disagrees with the runner")

    def test_fake_provider_records(self):
        for stems in SWEEP_GROUPS:
            with self.subTest(group=stems):
                self.sweep("fake", stems)

    def test_live_provider_records(self):
        for stems in LIVE_SWEEP_GROUPS:
            with self.subTest(group=stems):
                self.sweep("live", stems)

    def test_known_senders_records(self):
        for stems in POLICY_SWEEP_GROUPS:
            with self.subTest(group=stems):
                self.sweep("policy", stems)


class SenderPolicyTests(unittest.TestCase):
    """B01/B02 for the runner's --known-senders mode (main #40): its marker file and UNKNOWN_SENDER hold."""

    def folder(self):
        out, expected_path, _, _, _ = genuine()["policy"]
        target = Path(_GENUINE["temp"].name) / f"policy-copy-{next(COUNTER)}"
        shutil.copytree(out / "records", target / "records")
        shutil.copy(out / from_intake.SENDER_POLICY, target / from_intake.SENDER_POLICY)
        return target, score.read_rows(expected_path, expected=True)

    def test_genuine_marker_converts(self):
        out, expected = self.folder()
        self.assertEqual(converter_exit(out, expected), 0)

    def test_unknown_sender_without_the_marker_is_refused(self):
        out, expected = self.folder()
        (out / from_intake.SENDER_POLICY).unlink()
        self.assertEqual(converter_exit(out, expected), 2)

    def test_malformed_marker_is_refused(self):
        good = json.loads((genuine()["policy"][0] / from_intake.SENDER_POLICY).read_text(encoding="utf-8"))
        bad = {"empty object": "{}", "extra key": json.dumps(dict(good, extra=1)),
               "string version": json.dumps(dict(good, version="1")), "bool version": json.dumps(dict(good, version=True)),
               "version 2": json.dumps(dict(good, version=2)), "short hash": json.dumps(dict(good, sha256="ab")),
               "not JSON": "{", "NaN": '{"version": NaN, "sha256": "%s"}' % good["sha256"],
               "duplicate key": '{"version": 1, "version": 1, "sha256": "%s"}' % good["sha256"], "list": "[]"}
        for label, text in bad.items():
            with self.subTest(marker=label):
                out, expected = self.folder()
                (out / from_intake.SENDER_POLICY).write_text(text, encoding="utf-8")
                self.assertEqual(converter_exit(out, expected), 2)
        out, expected = self.folder()
        (out / from_intake.SENDER_POLICY).unlink()
        (out / from_intake.SENDER_POLICY).mkdir()
        self.assertEqual(converter_exit(out, expected), 2, "marker is a folder")

    def test_marker_on_a_folder_without_held_senders_converts(self):
        # A known-senders run in which every sender was listed writes exactly these records plus the marker.
        out, expected_path, _, _, _ = genuine()["fake"]
        target = Path(_GENUINE["temp"].name) / f"marker-only-{next(COUNTER)}"
        shutil.copytree(out / "records", target / "records")
        shutil.copy(genuine()["policy"][0] / from_intake.SENDER_POLICY, target / from_intake.SENDER_POLICY)
        self.assertEqual(converter_exit(target, score.read_rows(expected_path, expected=True)), 0)


class ReviewerProducerStateTests(unittest.TestCase):
    """B02 named instances (round-2 review), each built from genuine records and confirmed impossible by
    the replay oracle before the converter must refuse it."""

    def folder(self, stems, change):
        _, _, records, data, _ = genuine()["fake"]
        root = Path(_GENUINE["temp"].name) / f"named-{next(COUNTER)}"
        (root / "out" / "records").mkdir(parents=True)
        mutated = {stem: copy.deepcopy(records[stem]) for stem in stems}
        change(mutated)
        for stem in stems:
            (root / "out" / "records" / f"{mutated[stem]['record_id']}.json").write_text(json.dumps(mutated[stem]), encoding="utf-8")
        expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
        oracle = Replay(root, stems, data).reachable([mutated[s] for s in stems])
        return converter_exit(root / "out", expected), oracle

    def assert_impossible_and_refused(self, stems, change):
        code, oracle = self.folder(stems, change)
        self.assertFalse(oracle, "the runner can write this; the case is not a counterexample")
        self.assertEqual(code, 2)

    def test_named_cases(self):
        order, quiet, text_only = "c08-three-documents", "c29-inline-image-status", "c24-text-only-order"
        long_body = body_of(intake_parser.MAX_BODY + 1)

        def blank_order(m):
            r = m[order]
            r.update(body="", body_segments=[])
            r["reader_files"] = [e for e in r["reader_files"] if not e["derived"]]

        def unsupported_derived_only(m):
            r = m[order]
            for a in r["attachment_manifest"]:
                a["supported"] = False
            r["reader_files"] = [e for e in r["reader_files"] if e["derived"]]

        def add_derived(stem):
            def change(m):
                m[stem]["reader_files"].append(well_formed_reader_entries(m[stem])[-1])
            return change

        def text_only_with_attachments(m):
            r = m[quiet]
            pair = held("TEXT_ONLY_ORDER")
            r.update(pair, classification=dict(pair), note=from_intake.TEXT_ONLY_NOTE, needs_a_look=["TEXT_ONLY_ORDER"],
                     reader_files=[])

        def pdf_limit_with_derived(m):
            r = m[order]
            pair = held("PDF_LIMIT")
            r.update(pair, classification=dict(pair), needs_a_look=["PDF_LIMIT"])

        def oversized_body(m):
            r = m[order]
            r.update(body=long_body, body_segments=[{"kind": "newest", "text": long_body}])
            r["reader_files"][-1]["source_text_sha256"] = sha256(long_body.encode()).hexdigest()

        def too_many_attachments(m):
            r = m[quiet]
            first = r["attachment_manifest"][0]
            r["attachment_manifest"] = [dict(first, attachment_id=f"a{i + 1:03}",
                                             retained_file=first["retained_file"].replace("a001", f"a{i + 1:03}"))
                                        for i in range(intake_parser.MAX_ATTACHMENTS + 1)]
            r["source_size"] = MAX_EMAIL

        cases = {f"drop reader entry {i}": ([order], lambda m, i=i: m[order]["reader_files"].pop(i)) for i in range(4)}
        cases.update({
            "attachment-only without reader files": (["c10-attachment-only"], lambda m: m["c10-attachment-only"].update(reader_files=[])),
            "blank body, segments and derived file of an order": ([order], blank_order),
            "blank body of a quiet record": ([quiet], lambda m: m[quiet].update(body="", body_segments=[])),
            "unsupported attachments with derived-only order": ([order], unsupported_derived_only),
            "derived reader file on a quiet record": ([quiet], add_derived(quiet)),
            "derived reader file on a TEXT_ONLY_ORDER record": ([text_only], add_derived(text_only)),
            "TEXT_ONLY_ORDER classification and outcome with attachments": ([quiet], text_only_with_attachments),
            "PDF_LIMIT classification and outcome with a derived file": ([order], pdf_limit_with_derived),
            "body over the parser limit, re-derived": ([order], oversized_body),
            "more attachments than the parser limit": ([quiet], too_many_attachments),
            "unrelated intake in related_intakes": (["c01-disp-custom", "c02-disp-form-data"], lambda m: m["c02-disp-form-data"].update(
                related_intakes=[m["c01-disp-custom"]["intake_id"]])),
            "mutually pointing duplicates": (["c40-original", "c41-duplicate"], lambda m: (
                m["c40-original"].update(held("DUPLICATE"), classification=held("DUPLICATE"), needs_a_look=["DUPLICATE"],
                                         reader_files=[], duplicate_of=m["c41-duplicate"]["record_id"]))),
            "related listed in both directions": (["c40-original", "c45-shared-document"], lambda m: m["c40-original"].update(
                related_intakes=[m["c45-shared-document"]["intake_id"]])),
            "message-id conflict that is not CONFLICT": (["c42-mid-first", "c43-mid-conflict"], lambda m: m["c43-mid-conflict"].update(
                decided("order"), classification=decided("order"), needs_a_look=[],
                reader_files=well_formed_reader_entries(m["c43-mid-conflict"]))),
        })
        for label, (stems, change) in cases.items():
            with self.subTest(case=label):
                self.assert_impossible_and_refused(stems, change)


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
