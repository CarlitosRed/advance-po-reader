"""E2 regressions and bypass probes. Fictional sources; transport is forbidden."""
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from email_intake.contract import decision, validate
from email_intake.ledger import CAP_NANO, LedgerError, SpendLedger
from email_intake.parser import MAX_BODY, ParseError, parse
from email_intake.providers import FakeProvider, LiveProvider
from email_intake.runner import exclusive, run

_spec = importlib.util.spec_from_file_location("e2_helpers", Path(__file__).with_name("test_core.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
email = _helpers.email

ROOT = Path(__file__).resolve().parents[2]
PDF = ("application/pdf", "fictional.pdf", b"%PDF-fictional attachment")


class E2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.drop, self.out = self.base / "drop", self.base / "out"
        self.drop.mkdir()
        self.enterContext(patch("http.client.HTTPSConnection", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("socket.socket", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        spec = importlib.util.spec_from_file_location("e2_cli", ROOT / "scripts" / "email-intake.py")
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def invoke(self, *extra, out=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.cli.main(["--drop", str(self.drop), "--out", str(out or self.out), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def record(self, out=None):
        return json.loads(next(((out or self.out) / "records").glob("*.json")).read_text())

    def test_item_1_hard_kill_lock_recovers_only_with_explicit_flag(self):
        self.out.mkdir()
        program = ("from pathlib import Path; import sys,time; "
                   "from email_intake.runner import exclusive; "
                   "lock=exclusive(Path(sys.argv[1])); lock.__enter__(); "
                   "print('READY',flush=True); time.sleep(30)")
        child = subprocess.Popen([sys.executable, "-c", program, str(self.out)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "READY")
        finally:
            child.kill()
            child.communicate(timeout=10)
        before = (self.out / ".intake-lock").read_bytes()
        code, stdout, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("--break-lock", json.loads(stdout).get("hint", ""))
        self.assertEqual((self.out / ".intake-lock").read_bytes(), before)
        self.assertEqual(self.invoke("--break-lock")[0], 0)
        self.assertFalse((self.out / ".intake-lock").exists())

    def test_item_2_all_reused_live_warns_and_never_retries(self):
        (self.drop / "a.eml").write_bytes(email())
        run(self.drop, self.out)
        before = next((self.out / "records").glob("*.json")).read_bytes()
        ledger = SpendLedger(self.base / "spend.sqlite3", initialize=True)
        code, stdout, stderr = self.invoke("--live", "--ledger", str(ledger.path))
        self.assertEqual(code, 0)
        self.assertIn("ALL_REUSED", stderr)
        self.assertTrue(json.loads(stdout)["reused"])
        self.assertEqual(next((self.out / "records").glob("*.json")).read_bytes(), before)
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
        (self.drop / "b.eml").write_bytes(email(mid="<new@example.test>"))
        self.assertNotIn("ALL_REUSED", self.invoke("--live", "--ledger", str(ledger.path))[2])
        self.assertNotIn("ALL_REUSED", self.invoke()[2])

    def test_item_3_explicit_init_recovers_only_zero_byte_ledger(self):
        path = self.base / "empty.sqlite3"
        path.touch()
        with self.assertRaises(LedgerError):
            SpendLedger(path)
        self.assertEqual(path.stat().st_size, 0)
        recovered = SpendLedger(path, initialize=True)
        with recovered.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
            db.execute("INSERT INTO attempts(id,intake_id,charge,state) VALUES('prior','prior',?,'settled')", (CAP_NANO,))
        with self.assertRaisesRegex(LedgerError, "CAP"):
            SpendLedger(path, initialize=True).reserve("new")
        for data in (b"broken", b"\x00", b"SQLite format 3\x00" + b"\x00" * 100):
            with self.subTest(data=data):
                bad = self.base / "bad.sqlite3"
                bad.write_bytes(data)
                with self.assertRaises(LedgerError):
                    SpendLedger(bad, initialize=True)
                self.assertEqual(bad.read_bytes(), data)

    def test_item_4_charsetless_windows_1252_is_strict_and_bounded(self):
        for media, body in (("text/plain", "Pedido 2 sillas, \u20ac 10 \u2013 ficci\u00f3n"),
                            ("text/html", "<p>Pedido 2 sillas, \u20ac 10 \u2013 ficci\u00f3n</p>")):
            raw = (f"From: buyer@example.test\nSubject: Fictional order\nContent-Type: {media}\n"
                   "Content-Transfer-Encoding: 8bit\n\n").encode() + body.encode("cp1252")
            with self.subTest(media=media):
                self.assertIn("\u20ac 10 \u2013 ficci\u00f3n", parse(raw).body)
                with self.assertRaises(ParseError):
                    parse(raw.replace(b"Content-Type: " + media.encode(),
                                      b"Content-Type: " + media.encode() + b"; charset=utf-8"))
        prefix = b"From: buyer@example.test\nSubject: Fictional\nContent-Type: text/plain\nContent-Transfer-Encoding: 8bit\n\n"
        self.assertEqual(parse(prefix + "Pedido \u20ac".encode()).body, "Pedido \u20ac")
        self.assertEqual(parse(prefix + b"ASCII").body, "ASCII")
        for data in (b"\x81", b"\x80" * (MAX_BODY // 3 + 1)):
            with self.assertRaises(ParseError):
                parse(prefix + data)

    def test_item_5_non_eml_regular_files_have_one_private_summary(self):
        for name in ("fictional.txt", "private-name.pdf", "README"):
            (self.drop / name).write_bytes(b"must never be opened")
        (self.drop / "folder").mkdir()
        (self.drop / "a.EML").write_bytes(email())
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path.parent == self.drop and path.suffix.lower() != ".eml":
                self.fail("opened skipped input")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            code, stdout, stderr = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertEqual([json.loads(line) for line in stderr.splitlines()], [{"skipped_non_eml_files": 3}])
        self.assertNotIn("private-name", stdout + stderr)

    def test_item_6_empty_or_unsupported_skips_classifier_and_reservation(self):
        ledger = SpendLedger(self.base / "spend.sqlite3", initialize=True)
        provider = LiveProvider(enabled=True, api_key="fictional", ledger=ledger,
                                send=lambda *_: self.fail("paid classifier called"))
        samples = [email(body=""), email(body="", attachment=PDF),
                   email(attachment=("application/zip", "fictional.zip", b"PKopaque")),
                   email(attachment=("application/pdf", "false.pdf", b"PKdisguised")),
                   email(attachment=("application/pdf", "wrong.txt", b"%PDF-fictional"))]
        with patch.object(provider, "classify", side_effect=AssertionError("classifier called")):
            for index, raw in enumerate(samples):
                with self.subTest(index=index):
                    (self.drop / "a.eml").write_bytes(raw)
                    out = self.base / f"out-{index}"
                    result = run(self.drop, out, provider)[0]
                    self.assertEqual(result["lane"], "needs_a_look")
                    self.assertFalse((out / "calls.jsonl").exists())
                    self.assertEqual((out / self.record(out)["original"]).read_bytes(), raw)
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_item_7_text_only_order_has_plain_note_and_no_reader_file(self):
        for body in ("Please order 2 fictional stools.", "> Please order 2 fictional stools.", "Pedido ficticio: 2 sillas \u20a1 10"):
            raw = email(body=body)
            (self.drop / "a.eml").write_bytes(raw)
            out = self.base / sha256(raw).hexdigest()
            result = run(self.drop, out, FakeProvider({sha256(raw).hexdigest(): decision("order")}))[0]
            self.assertEqual(result["lane"], "needs_a_look")
            self.assertEqual(result["reason_code"], "TEXT_ONLY_ORDER")
            self.assertIn("email text", result.get("note", ""))
            self.assertIn("attachments", result["note"])
            self.assertEqual(result["reader_file_count"], 0)
            self.assertEqual(self.record(out)["classification"], decision("order"))
            self.assertEqual((out / self.record(out)["original"]).read_bytes(), raw)
        self.assertEqual(validate(decision("order") | {"reason_code": "TEXT_ONLY_ORDER"})["reason_code"], "CONFLICT")

    def test_break_lock_refuses_active_run_and_preserves_marker(self):
        self.out.mkdir()
        with exclusive(self.out):
            before = (self.out / ".intake-lock").read_bytes()
            self.assertEqual(self.invoke("--break-lock")[0], 2)
            self.assertEqual((self.out / ".intake-lock").read_bytes(), before)
        self.assertEqual(self.invoke()[0], 0)

    def test_break_lock_refuses_unknown_or_live_pid_markers(self):
        self.out.mkdir()
        for data in (b"", b"busy", b'{"pid":true}', b'{"pid":-1}',
                     b'{"pid":1,"pid":2147483647}', b'{"pid":2147483647,"extra":1}', b"x" * 1025,
                     json.dumps({"pid": os.getpid()}).encode()):
            with self.subTest(data=data):
                (self.out / ".intake-lock").write_bytes(data)
                self.assertEqual(self.invoke("--break-lock")[0], 2)
                self.assertEqual((self.out / ".intake-lock").read_bytes(), data)

    def test_empty_body_pdf_stays_selectable_without_conflict_or_text_note(self):
        raw = email(body="", attachment=PDF)
        (self.drop / "a.eml").write_bytes(raw)
        result = run(self.drop, self.out)[0]
        self.assertEqual(result["lane"], "needs_a_look")
        self.assertEqual(result["reason_code"], "unclear")
        self.assertEqual(result["reader_file_count"], 1)
        self.assertNotIn("note", result)
        candidate = self.record()["reader_files"][0]
        self.assertTrue(candidate["human_selection_required"])
        self.assertFalse(candidate["derived"])
        self.assertEqual((self.out / candidate["file"]).read_bytes(), PDF[2])

    def test_unsupported_mixed_with_supported_never_prepares_or_classifies(self):
        msg = EmailMessage()
        msg["From"], msg["Subject"] = "buyer@example.test", "Fictional attachments"
        msg.set_content("Please order 2 fictional stools.")
        msg.add_attachment(PDF[2], maintype="application", subtype="pdf", filename=PDF[1])
        msg.add_attachment(b"opaque macro", maintype="application", subtype="octet-stream", filename="fictional.xlsm")
        raw = msg.as_bytes()
        (self.drop / "a.eml").write_bytes(raw)
        provider = FakeProvider({sha256(raw).hexdigest(): decision("order")})
        with patch.object(provider, "classify", side_effect=AssertionError("classifier called")):
            result = run(self.drop, self.out, provider)[0]
        self.assertEqual((result["lane"], result["reader_file_count"]), ("needs_a_look", 0))
        self.assertEqual(len(self.record()["attachment_manifest"]), 2)

    def test_duplicate_and_message_id_conflict_precede_local_routes(self):
        raw = email(body="", attachment=PDF)
        (self.drop / "a.eml").write_bytes(raw)
        (self.drop / "b.eml").write_bytes(raw)
        (self.drop / "c.eml").write_bytes(email(body="Please order a different fictional stool."))
        results = run(self.drop, self.out)
        self.assertEqual([r["reason_code"] for r in results], ["unclear", "DUPLICATE", "CONFLICT"])
        self.assertEqual([r["reader_file_count"] for r in results], [1, 0, 0])
        self.assertFalse((self.out / "calls.jsonl").exists())

    def test_empty_ledger_with_sidecar_refuses_recovery(self):
        path = self.base / "empty.sqlite3"
        path.touch()
        sidecar = Path(str(path) + "-wal")
        sidecar.write_bytes(b"unknown prior spend")
        with self.assertRaises(LedgerError):
            SpendLedger(path, initialize=True)
        self.assertEqual(sidecar.read_bytes(), b"unknown prior spend")
        self.assertEqual(path.stat().st_size, 0)

    def test_recovery_guard_excludes_competing_process_after_stale_marker_removal(self):
        self.out.mkdir()
        (self.out / ".intake-lock").write_text('{"pid":2147483647}')
        entered, release = Event(), Event()
        def recover():
            with exclusive(self.out, break_lock=True):
                entered.set()
                self.assertTrue(release.wait(10))
        with patch("email_intake.locking.process_alive", return_value=False), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(recover)
            try:
                self.assertTrue(entered.wait(10))
                program = ("from pathlib import Path; import sys; "
                           "from email_intake.runner import run; "
                           "run(Path(sys.argv[1]), Path(sys.argv[2]), break_lock=True)")
                other = subprocess.run([sys.executable, "-c", program, str(self.drop), str(self.out)],
                                       cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(other.returncode, 0)
                self.assertIn("LockError", other.stderr)
                self.assertTrue((self.out / ".intake-lock").exists())
            finally:
                release.set()
                future.result(timeout=10)
        self.assertEqual(self.invoke()[0], 0)

    def test_concurrent_zero_byte_initialization_never_resets_spend(self):
        path = self.base / "empty.sqlite3"
        path.touch()
        def initialize(index):
            try:
                ledger = SpendLedger(path, initialize=True)
                ledger.reserve(str(index))
                return True
            except (LedgerError, OSError):
                # Another initializer's uncommitted sidecar can safely refuse.
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(initialize, range(8)))
        self.assertGreaterEqual(sum(admitted), 1)
        with SpendLedger(path, initialize=True).connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM policy").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], sum(admitted))

    def test_cli_zero_byte_ledger_requires_init_before_key_lookup(self):
        path = self.base / "empty.sqlite3"
        path.touch()
        get_env = os.environ.get
        def guarded_env(key, *args):
            if key == "OPENAI_API_KEY":
                self.fail("key lookup before validation")
            return get_env(key, *args)
        with patch("os.environ.get", side_effect=guarded_env):
            self.assertEqual(self.invoke("--live", "--ledger", str(path))[0], 2)
        self.assertEqual(path.stat().st_size, 0)
        self.assertEqual(self.invoke("--live", "--ledger", str(path), "--init-ledger")[0], 0)
        self.assertNotIn("ALL_REUSED", self.invoke("--live", "--ledger", str(path))[2])

    def test_text_only_nonorders_keep_classifier_routing(self):
        for category in ("invoice", "spam", "change", "unsure"):
            raw = email(body="Fictional business text", mid=f"<{category}@example.test>")
            (self.drop / "a.eml").write_bytes(raw)
            result = run(self.drop, self.base / category, FakeProvider({sha256(raw).hexdigest(): decision(category)}))[0]
            self.assertEqual(result["reason_code"], decision(category)["reason_code"])
            self.assertNotIn("note", result)


if __name__ == "__main__":
    unittest.main()
