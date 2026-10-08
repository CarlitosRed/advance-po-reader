"""Regression counterexamples from Claudio's review of f0a2380; offline only."""
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from email_intake.contract import decision
from email_intake.ledger import CAP_NANO, INPUT_BOUND, LedgerError, SpendLedger
from email_intake.parser import parse
from email_intake.providers import FakeProvider, LiveProvider, request_for
from email_intake.runner import run

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("review_helpers", Path(__file__).with_name("test_core.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
email, response = _helpers.email, _helpers.response


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.drop, self.out = self.base / "drop", self.base / "out"
        self.drop.mkdir()
        spec = importlib.util.spec_from_file_location("review_cli", ROOT / "scripts" / "email-intake.py")
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def ledger(self):
        return SpendLedger(self.base / "spend.sqlite3", initialize=True)

    def test_shared_attachment_is_a_link_not_a_conflict(self):
        for media, name, data in [("image/png", "logo.png", b"\x89PNG\r\n\x1a\nfictional"),
                                  ("image/jpeg", "logo.jpeg", b"\xff\xd8\xfffictional"),
                                  ("application/pdf", "terms.pdf", b"%PDF-fictional")]:
            with self.subTest(media=media):
                answers = {}
                for index in range(3):
                    raw = email(body=f"Please ship {index + 1} stools, PO FICT-{index}.",
                                mid=f"<order-{index}@example.test>", attachment=(media, name, data))
                    (self.drop / f"{index}.eml").write_bytes(raw)
                    answers[sha256(raw).hexdigest()] = decision("order")
                out = self.base / name
                results = run(self.drop, out, FakeProvider(answers))
                self.assertEqual([r["lane"] for r in results], ["order"] * 3)
                self.assertEqual(len((out / "calls.jsonl").read_text().splitlines()), 3)
                records = [json.loads(p.read_text()) for p in (out / "records").glob("*.json")]
                self.assertEqual(sum(bool(r["related_intakes"]) for r in records), 2)

    def test_body_order_with_supported_attachment_has_both_candidates(self):
        for media, name, data in [("image/png", "logo.png", b"\x89PNG\r\n\x1a\nfictional"),
                                  ("application/pdf", "terms.pdf", b"%PDF-fictional")]:
            with self.subTest(media=media):
                raw = email(body="Please ship 50 units of widget, PO FICT-123.",
                            attachment=(media, name, data))
                (self.drop / "a.eml").write_bytes(raw)
                out = self.base / name
                result = run(self.drop, out, FakeProvider({sha256(raw).hexdigest(): decision("order")}))[0]
                self.assertEqual(result["reader_file_count"], 2)
                record = json.loads(next((out / "records").glob("*.json")).read_text())
                derived = next(c for c in record["reader_files"] if c["derived"])
                self.assertTrue(derived["file"].endswith("derived-body.pdf"))
                self.assertEqual(derived["source_text_sha256"], sha256(record["body"].encode()).hexdigest())
                self.assertIn(b"Please ship 50 units", (out / derived["file"]).read_bytes())
                self.assertTrue(all(c["human_selection_required"] for c in record["reader_files"]))

    def test_offline_then_live_reports_reuse_and_original_provider(self):
        (self.drop / "a.eml").write_bytes(email())
        run(self.drop, self.out)
        before = next((self.out / "records").glob("*.json")).read_bytes()
        ledger = self.ledger()
        printed = io.StringIO()
        with patch("os.environ.get", return_value="fictional"), patch("sys.stdout", printed), \
             patch.object(self.cli, "SpendLedger", return_value=ledger), \
             patch("http.client.HTTPSConnection", side_effect=AssertionError("no network")):
            self.assertEqual(self.cli.main(["--drop", str(self.drop), "--out", str(self.out),
                                           "--live", "--ledger", str(ledger.path)]), 0)
        result = json.loads(printed.getvalue())
        self.assertIs(result.get("reused"), True)
        self.assertEqual(result.get("provider"), "fake")
        self.assertEqual(next((self.out / "records").glob("*.json")).read_bytes(), before)
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_keyless_then_keyed_reports_reuse_without_retry(self):
        (self.drop / "a.eml").write_bytes(email())
        ledger = self.ledger()
        run(self.drop, self.out, LiveProvider(enabled=True, ledger=ledger))
        with patch("http.client.HTTPSConnection", side_effect=AssertionError("no network")):
            result = run(self.drop, self.out, LiveProvider(enabled=True, api_key="fictional", ledger=ledger))[0]
        self.assertIs(result.get("reused"), True)
        self.assertEqual(result.get("provider"), "live")
        self.assertEqual(result["reason_code"], "MISSING_KEY")
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_missing_ledger_never_silently_creates_a_cap(self):
        path = self.base / "typo.sqlite3"
        with self.assertRaises(LedgerError):
            SpendLedger(path)
        self.assertFalse(path.exists())

    def test_prompt_and_schema_are_counted_once(self):
        parsed = parse(email(body="Please ship 50 units. " * 100))
        size = len(json.dumps(request_for(parsed, "a" * 64), ensure_ascii=True).encode())
        self.assertLessEqual(size, INPUT_BOUND)
        self.assertGreater(size + 2048, INPUT_BOUND)
        calls = []
        result, _ = LiveProvider(enabled=True, api_key="fictional", ledger=self.ledger(),
                                 send=lambda *args: (calls.append(args[0]) or (200, response()))).classify(parsed, "a" * 64)
        self.assertEqual(result, decision("order"))
        self.assertEqual(len(calls), 1)

    def test_serialized_byte_ceiling_admits_exact_bound_and_blocks_next_byte(self):
        base_size = len(json.dumps(request_for(parse(email(body="x")), "b" * 64), ensure_ascii=True).encode())
        ledger = self.ledger()
        calls = []
        provider = LiveProvider(enabled=True, api_key="fictional", ledger=ledger,
                                send=lambda *args: (calls.append(args[0]) or (200, response())))
        for extra, reason in [(0, "new_order"), (1, "LIMIT")]:
            parsed = parse(email(body="x" * (INPUT_BOUND - base_size + 1 + extra)))
            iid = ("b" if extra == 0 else "c") * 64
            self.assertEqual(len(json.dumps(request_for(parsed, iid), ensure_ascii=True).encode()), INPUT_BOUND + extra)
            self.assertEqual(provider.classify(parsed, iid)[0]["reason_code"], reason)
        self.assertEqual(len(calls), 1)
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_cli_requires_init_and_prints_absolute_ledger_without_key_lookup(self):
        path = self.base / "phase.sqlite3"
        stdout, stderr = io.StringIO(), io.StringIO()
        get_env = os.environ.get
        def guarded_env(key, *args):
            if key == "OPENAI_API_KEY":
                self.fail("key lookup before ledger validation")
            return get_env(key, *args)
        with patch("os.environ.get", side_effect=guarded_env), \
             patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            self.assertEqual(self.cli.main(["--drop", str(self.drop), "--out", str(self.out),
                                           "--live", "--ledger", str(path)]), 2)
        self.assertFalse(path.exists())
        self.assertEqual(json.loads(stdout.getvalue())["reason_code"], "LEDGER")
        self.assertEqual(json.loads(stderr.getvalue())["ledger"], str(path.resolve()))
        with patch("os.environ.get", return_value=None), patch("sys.stdout"), patch("sys.stderr"):
            self.assertEqual(self.cli.main(["--drop", str(self.drop), "--out", str(self.out),
                                           "--live", "--ledger", str(path), "--init-ledger"]), 0)
        self.assertTrue(path.exists())

    def test_init_existing_ledger_preserves_cap_through_relative_alias(self):
        ledger = self.ledger()
        with ledger.connect() as db:
            db.execute("INSERT INTO attempts(id,intake_id,charge,state) VALUES('prior','prior',?,'settled')", (CAP_NANO,))
        relative = Path(os.path.relpath(ledger.path))
        reopened = SpendLedger(relative, initialize=True)
        self.assertEqual(reopened.path, ledger.path)
        with self.assertRaisesRegex(LedgerError, "CAP"):
            reopened.reserve("second")

    def test_removed_or_empty_ledger_cannot_be_recreated_by_connect(self):
        ledger = self.ledger()
        ledger.path.unlink()
        with self.assertRaisesRegex(LedgerError, "LEDGER"):
            ledger.reserve("removed")
        self.assertFalse(ledger.path.exists())
        ledger.path.touch()
        with self.assertRaisesRegex(LedgerError, "LEDGER"):
            SpendLedger(ledger.path, initialize=True)

    def test_body_pdf_failure_with_attachment_retains_sources_for_review(self):
        raw = email(body="Fictional order: 2 stools, price ₡ 10.",
                    attachment=("image/png", "logo.png", b"\x89PNG\r\n\x1a\nfictional"))
        (self.drop / "a.eml").write_bytes(raw)
        result = run(self.drop, self.out, FakeProvider({sha256(raw).hexdigest(): decision("order")}))[0]
        self.assertEqual(result["reason_code"], "PDF_LIMIT")
        self.assertEqual(result["reader_file_count"], 1)
        record = json.loads(next((self.out / "records").glob("*.json")).read_text())
        self.assertIn("₡ 10", record["body"])
        self.assertEqual((self.out / record["original"]).read_bytes(), raw)
        self.assertFalse(result["reused"])
        self.assertEqual(result["provider"], "fake")


if __name__ == "__main__":
    unittest.main()
