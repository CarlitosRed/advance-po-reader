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
from email_intake import senders as intake_senders  # noqa: E402
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


def copy_original(source_out, target_out, intake_id):
    """Copy the email the runner kept for one intake id (sources/<intake_id>/original.eml)."""
    folder = target_out / "sources" / intake_id
    folder.mkdir(parents=True, exist_ok=True)
    original = source_out / "sources" / intake_id / "original.eml"
    if original.exists():
        shutil.copy(original, folder / "original.eml")


def write_originals(out, data):
    """Write the runner's kept copy of every email (bytes) into a test folder."""
    for raw in data:
        folder = out / "sources" / sha256(raw).hexdigest()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "original.eml").write_bytes(raw)


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
        """A copy of the scripted run: records plus the emails the runner keeps (sources/<intake_id>/original.eml)."""
        target = self.root / f"out-{next(COUNTER)}"
        shutil.copytree(self.scripted / "records", target / "records")
        for fixture_id, record in self.base.items():
            copy_original(self.scripted, target, record["intake_id"])
        return target

    def solo(self, fixture_id):
        """A folder holding only one record, with an expected file of only that email (fast sweeps)."""
        number = next(COUNTER)
        target = self.root / f"solo-{number}"
        (target / "records").mkdir(parents=True)
        shutil.copy(self.scripted / "records" / self.names[fixture_id], target / "records" / self.names[fixture_id])
        copy_original(self.scripted, target, self.base[fixture_id]["intake_id"])
        expected = self.root / f"solo-expected-{number}.jsonl"
        expected.write_text(self.lines[fixture_id] + "\n", encoding="utf-8")
        return target, expected

    def mini(self, files, mapping=None):
        """A real runner run over these (name -> bytes) emails; every parseable one is scripted order."""
        number = next(COUNTER)
        drop = self.root / f"mini-drop-{number}"
        drop.mkdir()
        template = json.loads(self.lines["fictional-0001"])
        lines, script = [], {}
        for name, data in files.items():
            (drop / name).write_bytes(data)
            digest = sha256(data).hexdigest()
            lines.append(json.dumps(dict(template, id=name[:-4], sha256=digest)))
            script[digest] = (mapping or {}).get(name, {"category": "order", "lane": "order", "reason_code": "new_order"})
        expected = self.root / f"mini-expected-{number}.jsonl"
        expected.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = self.root / f"mini-out-{number}"
        intake_run(drop, out, FakeProvider(script))
        return out, expected

    def mini_records(self, out):
        return {json.loads(p.read_text())["source_name"]: json.loads(p.read_text()) for p in (out / "records").glob("*.json")}

    def edit_named(self, out, name, change):
        """Edit the record of source file `name` in place (its file name and record id unchanged)."""
        path = next(p for p in (out / "records").glob("*.json") if json.loads(p.read_text())["source_name"] == name)
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")

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

    def test_kept_email_is_required_and_must_be_the_expected_bytes(self):
        # Source values are re-derived from sources/<intake_id>/original.eml, which the runner always writes.
        fixture_id = self.order_with_document()
        original = Path("sources") / self.base[fixture_id]["intake_id"] / "original.eml"
        out, expected = self.solo(fixture_id)
        (out / original).unlink()
        self.assert_fails_closed(out, "original.eml is missing", expected)
        out, expected = self.solo(fixture_id)
        (out / original).write_bytes((out / original).read_bytes() + b"\r\n")
        self.assert_fails_closed(out, "not this record's email", expected)
        out, expected = self.solo(fixture_id)
        (out / original).unlink()
        (out / original).mkdir()
        self.assert_fails_closed(out, "not a regular file", expected)

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
        # Genuine emails with reply subjects, through the real runner: the order lane is kept as the runner wrote it.
        for subject in ("RE: purchase order", "  re : orden", "Re:x"):
            with self.subTest(subject=subject):
                out, expected = self.mini({"fictional-0001.eml": eml("r01", subject=subject, parts=[pdf_part("r01")])})
                code, err, answers, _ = self.convert(out, expected)
                self.assertEqual(code, 0, err)
                row = self.answer_rows(answers)["fictional-0001"]
                self.assertEqual((row["category"], row["lane"]), ("order", "order"))
        # A subject edited in the record no longer matches the email the runner kept: refused.
        fixture_id = self.order_with_document()
        out, expected = self.solo(fixture_id)
        self.edit(out, fixture_id, lambda r: r.update(subject="RE: purchase order"))
        self.assert_fails_closed(out, "subject is not what the parser derives", expected)

    def test_attachment_disposition_does_not_change_the_runner_lane(self):
        for disposition in ("inline", "attachment"):
            with self.subTest(disposition=disposition):
                raw = eml("r02", parts=[pdf_part("r02", f'{disposition}; filename="po.pdf"')])
                out, expected = self.mini({"fictional-0001.eml": raw})
                code, err, answers, _ = self.convert(out, expected)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.answer_rows(answers)["fictional-0001"]["lane"], "order")
                flipped = "attachment" if disposition == "inline" else "inline"
                self.edit_named(out, "fictional-0001.eml", lambda r: [a.update(disposition=flipped) for a in r["attachment_manifest"]])
                self.assert_fails_closed(out, "attachment_manifest is not what the parser derives", expected)

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
        # Every value is re-derived from the kept email or the runner's routing, so no single change is valid
        # (source values such as sender, subject, file names, sizes and dispositions included).
        self.assertEqual(accepted, [], f"{fixture_id}: changed values accepted")

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
        out, expected = self.mini({"fictional-0001.eml": b"not an email at all"})
        code, err, answers, summary = self.convert(out, expected)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(summary)["local_reason_codes_omitted"], {"PARSE_FAILED": 1})
        cases = {"other local reason": lambda r: r.update(reason_code="CONFLICT", needs_a_look=["CONFLICT"]),
                 "LIMIT instead of the parser's PARSE_FAILED": lambda r: r.update(reason_code="LIMIT", needs_a_look=["LIMIT"]),
                 "a parsed field": lambda r: r.update(subject="x")}
        for label, change in cases.items():
            with self.subTest(case=label):
                out, expected = self.mini({"fictional-0001.eml": b"not an email at all"})
                self.edit_named(out, "fictional-0001.eml", change)
                self.assert_fails_closed(out, expected_path=expected)
        # A pre-parse refusal written for an email the parser reads is not the runner's record either.
        fixture_id = self.first(category="invoice")
        out, expected = self.solo(fixture_id)
        self.edit(out, fixture_id, pre_parse_refusal)
        self.assert_fails_closed(out, "the parser reads this email", expected)


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

    records = Base.mini_records

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
    if isinstance(target, dict) and (type(reason) is not str or reason not in intake_contract.LOCAL_REASONS):
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


def fake_script(target):
    if same(target, held("INVALID")):
        return "garbage"
    if same(target, held("CONFLICT")):
        return copy.deepcopy(MISMATCH)
    return copy.deepcopy(target)


def run_sequences(stems):
    """Every sequence of runner calls that processes each email exactly once (ordered set partitions)."""
    if not stems:
        yield []
        return
    for size in range(1, len(stems) + 1):
        for first in itertools.combinations(stems, size):
            rest = [s for s in stems if s not in first]
            for tail in run_sequences(rest):
                yield [list(first)] + tail


class Replay:
    """Oracle: re-run the real runner over the same email files and report whether it writes exactly these
    records. Everything is the producer's own code on the real bytes (parser, sender list, routing, files);
    only the classifier is pinned, to the result its code returns when scripted with the original record's
    classification, because a provider's answer is the one value a folder cannot re-derive.

    schedules: the runner calls to try, each a list of stems processed by one call. Default: one call with
    every email. A record set is reachable when ANY schedule writes it."""

    def __init__(self, root, stems, data, policy=False, schedules=None):
        """policy: replay --known-senders runs with the KNOWN list (the folder holds sender-policy.json)."""
        self.root, self.stems, self.data, self.cache, self.runs = root, stems, data, {}, 0
        self.policy, self.parsed = policy, {}
        self.schedules = schedules or [[list(stems)]]

    def results(self, records):
        """{intake_id: (result, audit)} the pinned classifier returns, or None for a folder no runner writes."""
        kinds = {json.dumps(r.get("provider")) for r in records}
        if len(kinds) != 1 or not kinds <= {'"fake"', '"live"'}:
            return None  # one provider per folder (converter policy); unknown providers do not exist
        live = kinds == {'"live"'}
        results = {}
        for stem in self.stems:
            raw = self.data[stem]
            iid = sha256(raw).hexdigest()
            if iid in results:
                continue
            copies = [r for s, r in zip(self.stems, records) if self.data[s] == raw]
            # The runner calls the provider at most once per email: for its first record (duplicate_of null).
            originals = [r for r in copies if r.get("duplicate_of") is None]
            target = (originals or copies)[0].get("classification")
            if raw not in self.parsed:  # the real parser, once per email (it is deterministic)
                try:
                    self.parsed[raw] = intake_parser.parse(raw, sender_hint=self.policy)
                except intake_parser.ParseError:
                    self.parsed[raw] = None
            parsed = self.parsed[raw]
            if parsed is None:
                results[iid] = None
                continue
            provider = live_provider(target) if live else FakeProvider({iid: fake_script(target)})
            results[iid] = provider.classify(parsed, iid)
        return live, results

    def run(self, schedule, live, results):
        self.runs += 1
        number = next(COUNTER)
        drop, out = self.root / f"replay-drop-{number}", self.root / f"replay-out-{number}"

        class Pinned:
            def __init__(self):
                self.live = live

            def classify(self, parsed, intake_id):
                return copy.deepcopy(results[intake_id])
        plain = lambda path: Path(path).absolute()  # noqa: E731 (alias defence: not part of record content)
        with mock.patch.object(os, "fsync", lambda fd: None), mock.patch.object(intake_runner, "safe_path", plain), \
                mock.patch.object(intake_locking, "safe_path", plain):
            for call in schedule:
                if drop.exists():
                    shutil.rmtree(drop)
                drop.mkdir(parents=True)
                for stem in call:
                    (drop / f"{stem}.eml").write_bytes(self.data[stem])
                intake_run(drop, out, Pinned(), known_senders=KNOWN if self.policy else None)
        produced = read_records(out)
        shutil.rmtree(drop)
        shutil.rmtree(out)
        return [produced[stem] for stem in self.stems]

    def reachable(self, records):
        pinned = self.results(records)
        if pinned is None:
            return False
        live, results = pinned
        decided_results = {iid: None if value is None else value[0] for iid, value in results.items()}
        for index, schedule in enumerate(self.schedules):
            key = json.dumps([index, live, sorted(decided_results.items())], sort_keys=True)
            if key not in self.cache:
                self.cache[key] = self.run(schedule, live, results)
            if all(same(p, r) for p, r in zip(self.cache[key], records)):
                return True
        return False


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


def converter_exit(out, expected, known_senders=None):
    """from_intake.main's decision without publishing a file: 0 when convert() succeeds, 2 when it refuses."""
    try:
        from_intake.convert(out, expected, known_senders)
    except (OSError, ValueError, RecursionError):
        return 2
    return 0


def converter_exit_texts(texts, expected, data, known_senders=None):
    """The same decision for record files held in memory (every record, source and cross-record check; the
    folder and file-system checks are covered by the folder tests above). data: the emails' bytes, which the
    runner keeps as sources/<intake_id>/original.eml."""
    sources = {sha256(raw).hexdigest(): raw for raw in data}
    try:
        from_intake.convert_records([from_intake.record_from_text(text, Path(name)) for name, text in sorted(texts.items())],
                                    expected, sources, known_senders)
    except (ValueError, RecursionError):
        return 2
    return 0


def known_list_file():
    """The KNOWN list as the text file a --known-senders run reads (for the converter's CLI)."""
    path = Path(genuine()["temp"].name) / "known-senders.txt"
    if not path.exists():
        path.write_text("\n".join(sorted(KNOWN.addresses | KNOWN.domains)) + "\n", encoding="utf-8")
    return path


def run_calls(drop, out, calls, data, results, known_senders=None):
    """Genuine multi-run history: one real runner call per list of stems, into the same --out folder."""
    for call in calls:
        if drop.exists():
            shutil.rmtree(drop)
        drop.mkdir(parents=True)
        for stem in call:
            (drop / f"{stem}.eml").write_bytes(data[stem])
        intake_run(drop, out, FakeProvider(results), known_senders=known_senders)
    return read_records(out)


def lower_id_name(iid, prefix, below):
    """A drop-file stem whose record id (for this email) sorts before `below`."""
    return next(stem for stem in (f"{prefix}{i}" for i in itertools.count())
                if sha256((iid + stem + ".eml").encode()).hexdigest() < below)


def multi_run_corpus():
    """Genuine folders written by SEVERAL runner calls (round-3 review, process note 2), built once:
    {name: (stems, data, calls, records, results)}.

    chain: one email copied four times, one call per copy, record ids ordered D < C < B < A; each later call
    loads the folder in record-file order, so the runner writes A <- B <- C <- D (each copy points at the
    lowest-id earlier copy, not at the first record).
    mixed: two calls with a shared attachment digest, a shared message id (CONFLICT) and a duplicate."""
    store = genuine()
    if "multi" in store:
        return store["multi"]
    root = Path(store["temp"].name) / "multi"
    corpus = {}
    raw = eml("m01", parts=[pdf_part("m01")])
    iid = sha256(raw).hexdigest()
    rid = lambda stem: sha256((iid + stem + ".eml").encode()).hexdigest()  # noqa: E731
    a = "chain-a"
    b = lower_id_name(iid, "chain-b", rid(a))
    c = lower_id_name(iid, "chain-c", rid(b))
    d = lower_id_name(iid, "chain-d", rid(c))
    data = {stem: raw for stem in (a, b, c, d)}
    results = {iid: decided("order")}
    calls = [[a], [b], [c], [d]]
    records = run_calls(root / "chain-drop", root / "chain-out", calls, data, results)
    corpus["chain"] = ([a, b, c, d], data, calls, records, results)
    x = eml("m2x", parts=[pdf_part("m2x")])
    y = eml("m2y", body="Second fictional order 2002", parts=[pdf_part("m2x")])  # shares x's document
    z = eml("m2z", message_id="<m2y@fictional.example>", body="Third fictional order 2003", parts=[pdf_part("m2z")])
    data = {"mixed-a": x, "mixed-b": y, "mixed-c": x, "mixed-d": z}
    results = {sha256(v).hexdigest(): decided("order") for v in data.values()}
    calls = [["mixed-b", "mixed-d"], ["mixed-a", "mixed-c"]]
    records = run_calls(root / "mixed-drop", root / "mixed-out", calls, data, results)
    corpus["mixed"] = (list(data), data, calls, records, results)
    store["multi"] = corpus
    return corpus


class GenuineProducerOutputTests(unittest.TestCase):
    """B01 class: every value the real parser and runner write converts (exit 0)."""

    def convert_folder(self, kind):
        out, expected_path, records, _, _ = genuine()[kind]
        answers = Path(_GENUINE["temp"].name) / f"answers-{kind}-{next(COUNTER)}.jsonl"
        known = ["--known-senders", str(known_list_file())] if kind == "policy" else []
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = from_intake.main(["--out", str(out), "--expected", str(expected_path), "--answers", str(answers), *known])
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
        # The converter re-parses with the runner's own parser and loads lists with the runner's own loader.
        self.assertIs(from_intake.parse, intake_parser.parse)
        self.assertIs(from_intake.load_senders, intake_senders.load)
        self.assertIn('folder / "original.eml"', runner_source)
        self.assertEqual(from_intake.ORIGINAL, "original.eml")

    def test_replay_oracle_reproduces_every_genuine_record(self):
        for kind in ("fake", "live", "policy"):
            out, _, records, data, _ = genuine()[kind]
            stems = sorted(records)
            replay = Replay(Path(_GENUINE["temp"].name) / f"oracle-check-{kind}", stems, data, policy=kind == "policy")
            self.assertTrue(replay.reachable([records[s] for s in stems]), kind)
            if kind == "policy":  # the same records without the policy marker: the runner cannot write them
                plain = Replay(Path(_GENUINE["temp"].name) / "oracle-check-no-policy", stems, data)
                self.assertFalse(plain.reachable([records[s] for s in stems]))
        for name, (stems, data, calls, records, _) in multi_run_corpus().items():
            with self.subTest(multi_run=name):
                genuine_records = [records[s] for s in stems]
                single = Replay(Path(_GENUINE["temp"].name) / f"oracle-check-{name}-single", stems, data)
                self.assertFalse(single.reachable(genuine_records), "needs several runner calls")
                every = Replay(Path(_GENUINE["temp"].name) / f"oracle-check-{name}", stems, data,
                               schedules=list(run_sequences(stems)))
                self.assertTrue(every.reachable(genuine_records))

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

    def test_multi_run_histories_convert(self):
        """Folders written by several runner calls (each later call looks earlier records up in record-file
        order) are genuine: they must convert, including the four-copy chain A <- B <- C <- D."""
        for name, (stems, data, calls, records, _) in multi_run_corpus().items():
            with self.subTest(multi_run=name):
                root = Path(_GENUINE["temp"].name) / f"multi-convert-{name}-{next(COUNTER)}"
                out = root / "out"
                run_calls(root / "drop", out, calls, data, multi_run_corpus()[name][4])
                expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
                self.assertEqual(converter_exit(out, expected), 0)
        stems, _, _, records, _ = multi_run_corpus()["chain"]
        a, b, c, d = (records[s] for s in stems)
        self.assertEqual([b["duplicate_of"], c["duplicate_of"], d["duplicate_of"]],
                         [a["record_id"], b["record_id"], c["record_id"]], "the runner's lookup order changed")
        mixed = multi_run_corpus()["mixed"][3]
        self.assertEqual(mixed["mixed-a"]["related_intakes"], [mixed["mixed-b"]["intake_id"]])
        self.assertEqual(mixed["mixed-c"]["duplicate_of"], mixed["mixed-a"]["record_id"])
        self.assertEqual(mixed["mixed-d"]["reason_code"], "CONFLICT")

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
    refuse (exit 2) exactly the mutated folders the real runner cannot write, and accept the rest. The oracle
    re-runs the real runner on the real email bytes (source-derived fields included) and, for the multi-run
    groups, over every possible sequence of runner calls."""

    @classmethod
    def tearDownClass(cls):
        print(f"\n[producer mutation sweep] {dict(sorted(SWEEP_STATS.items()))}", file=sys.stderr)

    def compare(self, stems, data, group, replay, expected, known_senders=None):
        """Every single-field mutation of every record of `group` ({stem: record}): converter vs oracle."""
        genuine_records = [group[stem] for stem in stems]
        names = {stem: f"{group[stem]['record_id']}.json" for stem in stems}
        texts = {names[stem]: json.dumps(group[stem]) for stem in stems}
        raws = list(data.values())
        self.assertTrue(replay.reachable(genuine_records))
        self.assertEqual(converter_exit_texts(texts, expected, raws, known_senders), 0)
        peers = [r for name in ("fake", "live", "policy") for r in genuine()[name][2].values()]
        wrong = []
        for slot, stem in enumerate(stems):
            others = [p for p in peers if p["source_name"] != f"{stem}.eml"] + [
                group[s] for s in stems if s != stem]
            for kind_, mpath, arg in single_field_mutations(group[stem], others):
                mutated = apply_mutation(group[stem], kind_, mpath, arg)
                candidate = list(genuine_records)
                candidate[slot] = mutated
                reachable = replay.reachable(candidate)
                code = converter_exit_texts(dict(texts, **{names[stem]: json.dumps(mutated)}), expected, raws, known_senders)
                SWEEP_STATS["mutations"] += 1
                SWEEP_STATS["reachable" if reachable else "impossible"] += 1
                if code != (0 if reachable else 2):
                    wrong.append((stem, kind_, mpath, json.dumps(arg)[:80], "reachable" if reachable else "impossible", code))
        SWEEP_STATS["replays"] += replay.runs
        self.assertEqual(wrong[:25], [], f"{len(wrong)} mutations where the converter disagrees with the runner")

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
        expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
        self.assertEqual(converter_exit(out, expected, KNOWN if policy else None), 0)
        replay = Replay(root, stems, data, policy=policy)
        self.compare(stems, {s: data[s] for s in stems}, group, replay, expected, KNOWN if policy else None)

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

    def test_multi_run_records(self):
        """Folders of several runner calls; the oracle tries every sequence of calls (75 for four emails)."""
        for name, (stems, data, calls, records, _) in multi_run_corpus().items():
            with self.subTest(multi_run=name):
                root = Path(_GENUINE["temp"].name) / f"sweep-multi-{name}-{next(COUNTER)}"
                expected = score.read_rows(expected_rows(root.with_suffix(".jsonl"), stems, data), expected=True)
                replay = Replay(root, stems, data, schedules=list(run_sequences(stems)))
                self.compare(stems, data, records, replay, expected)


class SenderPolicyTests(unittest.TestCase):
    """B01/B02 for the runner's --known-senders mode (main #40): its marker file and UNKNOWN_SENDER hold.
    The marker holds only the list's fingerprint, so the converter takes the list itself (same fingerprint)
    and re-derives every hold from the parsed sender address."""

    def folder(self):
        out, expected_path, _, _, _ = genuine()["policy"]
        target = Path(_GENUINE["temp"].name) / f"policy-copy-{next(COUNTER)}"
        shutil.copytree(out / "records", target / "records")
        shutil.copytree(out / "sources", target / "sources")
        shutil.copy(out / from_intake.SENDER_POLICY, target / from_intake.SENDER_POLICY)
        return target, score.read_rows(expected_path, expected=True)

    def test_genuine_marker_converts(self):
        out, expected = self.folder()
        self.assertEqual(converter_exit(out, expected, KNOWN), 0)

    def test_the_runs_list_is_required(self):
        out, expected = self.folder()
        self.assertEqual(converter_exit(out, expected), 2, "membership cannot be checked against a fingerprint")
        other = KnownSenders(KNOWN.addresses | {"stranger@elsewhere.example"}, KNOWN.domains)
        self.assertEqual(converter_exit(out, expected, other), 2, "a different list than the run used")
        domain = KnownSenders(frozenset(), frozenset({"fictional.example"}))
        self.assertEqual(converter_exit(out, expected, domain), 2, "same members for these emails, other fingerprint")

    def test_list_for_a_run_without_the_marker_is_refused(self):
        out, expected_path, _, _, _ = genuine()["fake"]
        self.assertEqual(converter_exit(out, score.read_rows(expected_path, expected=True), KNOWN), 2)

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
                self.assertEqual(converter_exit(out, expected, KNOWN), 2)
        out, expected = self.folder()
        (out / from_intake.SENDER_POLICY).unlink()
        (out / from_intake.SENDER_POLICY).mkdir()
        self.assertEqual(converter_exit(out, expected, KNOWN), 2, "marker is a folder")

    def test_marker_on_a_folder_without_held_senders_converts(self):
        # A known-senders run in which every sender was listed writes exactly these records plus the marker.
        out, expected_path, _, _, _ = genuine()["fake"]
        target = Path(_GENUINE["temp"].name) / f"marker-only-{next(COUNTER)}"
        shutil.copytree(out / "records", target / "records")
        shutil.copytree(out / "sources", target / "sources")
        shutil.copy(genuine()["policy"][0] / from_intake.SENDER_POLICY, target / from_intake.SENDER_POLICY)
        self.assertEqual(converter_exit(target, score.read_rows(expected_path, expected=True), KNOWN), 0)

    def test_hold_membership_is_re_derived_round_3(self):
        """Round 3, new class from #40: both copies from a LISTED sender relabelled UNKNOWN_SENDER (reader files
        cleared, genuine marker kept) must be refused; and the reverse, a held stranger relabelled as decided."""
        _, _, records, data, _ = genuine()["policy"]

        def hold(record):
            pair = held("UNKNOWN_SENDER")
            record.update(pair, classification=dict(pair), needs_a_look=["UNKNOWN_SENDER"], reader_files=[])
            record.pop("note", None)

        def release(record):
            record.update(decided("order"), classification=decided("order"), needs_a_look=[],
                          reader_files=well_formed_reader_entries(record))
        cases = {"listed sender held (both copies)": (["p01-known-order", "p07-known-duplicate"], ["p01-known-order", "p07-known-duplicate"], hold),
                 "listed sender held (original only)": (["p01-known-order", "p07-known-duplicate"], ["p01-known-order"], hold),
                 "stranger released": (["p02-unknown-order"], ["p02-unknown-order"], release)}
        for label, (stems, changed, change) in cases.items():
            with self.subTest(case=label):
                root = Path(_GENUINE["temp"].name) / f"membership-{next(COUNTER)}"
                out = root / "out"
                (out / "records").mkdir(parents=True)
                shutil.copy(genuine()["policy"][0] / from_intake.SENDER_POLICY, out / from_intake.SENDER_POLICY)
                write_originals(out, [data[s] for s in stems])
                mutated = []
                for stem in stems:
                    record = copy.deepcopy(records[stem])
                    if stem in changed:
                        change(record)
                    mutated.append(record)
                    (out / "records" / f"{record['record_id']}.json").write_text(json.dumps(record), encoding="utf-8")
                expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
                self.assertFalse(Replay(root, stems, data, policy=True).reachable(mutated), "not a counterexample")
                self.assertEqual(converter_exit(out, expected, KNOWN), 2)
                answers = root / "answers.jsonl"
                with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
                    code = from_intake.main(["--out", str(out), "--expected", str(root / "expected.jsonl"),
                                             "--answers", str(answers), "--known-senders", str(known_list_file())])
                self.assertEqual(code, 2)
                self.assertIn("UNKNOWN_SENDER" if label.startswith("listed") else "known-senders", err.getvalue())
                self.assertFalse(answers.exists())


class ReviewerProducerStateTests(unittest.TestCase):
    """B02 named instances (round-2 and round-3 reviews), each built from genuine records and confirmed
    impossible by the replay oracle before the converter must refuse it."""

    def check(self, stems, data, records, change, schedules=None):
        root = Path(_GENUINE["temp"].name) / f"named-{next(COUNTER)}"
        (root / "out" / "records").mkdir(parents=True)
        write_originals(root / "out", {data[s] for s in stems})
        mutated = {stem: copy.deepcopy(records[stem]) for stem in stems}
        change(mutated)
        for stem in stems:
            (root / "out" / "records" / f"{mutated[stem]['record_id']}.json").write_text(json.dumps(mutated[stem]), encoding="utf-8")
        expected = score.read_rows(expected_rows(root / "expected.jsonl", stems, data), expected=True)
        oracle = Replay(root, stems, data, schedules=schedules).reachable([mutated[s] for s in stems])
        return converter_exit(root / "out", expected), oracle

    def folder(self, stems, change):
        _, _, records, data, _ = genuine()["fake"]
        return self.check(stems, data, records, change)

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

    def test_round_3_source_values_are_re_derived(self):
        """Round 3, B02 part 1 and P3: values the parser derives from the kept email, changed in the record."""
        order = "c08-three-documents"

        def manifest(field, value):
            def change(m):
                for a in m[order]["attachment_manifest"]:
                    a[field] = value
            return change
        cases = {
            "malformed media type token": ([order], manifest("media_type", "bad type/thing")),
            "malformed media type token, unsupported attachment": (["c06-unnamed-octet"], lambda m: (
                m["c06-unnamed-octet"]["attachment_manifest"][0].update(media_type="bad type/thing"))),
            "malformed disposition token, unsupported attachment": (["c06-unnamed-octet"], lambda m: (
                m["c06-unnamed-octet"]["attachment_manifest"][0].update(disposition="bad token"))),
            "malformed disposition token": ([order], manifest("disposition", "bad token")),
            "well-formed but different disposition": ([order], manifest("disposition", "inline")),
            "well-formed but different file name": ([order], manifest("filename", "other.pdf")),
            "source_size one byte more": ([order], lambda m: m[order].update(source_size=m[order]["source_size"] + 1)),
            "different sender": ([order], lambda m: m[order].update(sender="Other <other@fictional.example>")),
            "message id removed": ([order], lambda m: m[order].update(message_id=None)),
            "PARSE_FAILED relabelled LIMIT": (["c23-not-an-email"], lambda m: m["c23-not-an-email"].update(
                reason_code="LIMIT", needs_a_look=["LIMIT"])),
        }
        for label, (stems, change) in cases.items():
            with self.subTest(case=label):
                self.assert_impossible_and_refused(stems, change)

    def test_round_3_identical_malformed_emails_one_relabelled_limit(self):
        """Round 3, P3: two copies of one malformed email are both PARSE_FAILED; one relabelled LIMIT."""
        raw = b"not an email at all"
        data = {"bad-a": raw, "bad-b": raw}
        root = Path(_GENUINE["temp"].name) / f"two-malformed-{next(COUNTER)}"
        records = run_calls(root / "drop", root / "out", [list(data)], data, {})
        self.assertEqual({r["reason_code"] for r in records.values()}, {"PARSE_FAILED"})
        expected = score.read_rows(expected_rows(root / "expected.jsonl", list(data), data), expected=True)
        self.assertEqual(converter_exit(root / "out", expected), 0)
        code, oracle = self.check(list(data), data, records, lambda m: m["bad-b"].update(reason_code="LIMIT", needs_a_look=["LIMIT"]))
        self.assertFalse(oracle)
        self.assertEqual(code, 2)

    def test_round_3_four_copy_chain_cannot_bypass_a_lower_id_copy(self):
        """Round 3, B02 part 2: A <- B <- C <- D over four calls (ids D < C < B < A). D pointing at A instead
        of C is a folder no sequence of runner calls writes (C has the lowest earlier id when D is added)."""
        stems, data, calls, records, _ = multi_run_corpus()["chain"]
        a, b, c, d = stems
        every = list(run_sequences(stems))
        code, oracle = self.check(stems, data, records, lambda m: None, schedules=every)
        self.assertEqual((code, oracle), (0, True), "the genuine chain must convert")
        code, oracle = self.check(stems, data, records, lambda m: m[d].update(duplicate_of=records[a]["record_id"]),
                                  schedules=every)
        self.assertFalse(oracle, "the runner can write this; the case is not a counterexample")
        self.assertEqual(code, 2)
        # Genuine alternative histories are accepted, like the oracle: D -> B (A; B; then C and D in one call,
        # both find B first) and C -> A (A; then B and C in one call, both find only A; then D finds C first).
        for label, stem, target in (("D -> B", d, b), ("C -> A", c, a)):
            with self.subTest(case=label):
                code, oracle = self.check(stems, data, records,
                                          lambda m, s=stem, t=target: m[s].update(duplicate_of=records[t]["record_id"]),
                                          schedules=every)
                self.assertEqual((code, oracle), (0, True))


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
