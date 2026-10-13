"""E3 admission probes, using fictional mail and no credential/network access."""
from contextlib import redirect_stderr, redirect_stdout
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
import unittest
from unittest.mock import patch

from email_intake.contract import decision, PAIRS, SCHEMA
from email_intake.providers import FakeProvider
from email_intake.runner import run
from email_intake.senders import SenderListError, load

ROOT = Path(__file__).resolve().parents[2]


def mail(sender="buyer@customer.example.test", *, body="Please order 2 fictional stools.",
         attachment=True, extra_from=None):
    msg = EmailMessage()
    msg["Subject"] = "Fictional order"
    msg.set_content(body)
    if attachment:
        msg.add_attachment(b"%PDF-fictional attachment", maintype="application",
                           subtype="pdf", filename="fictional.pdf")
    # Preserve attack syntax literally; EmailMessage otherwise repairs malformed
    # headers during serialization and the probe would test the repaired mail.
    raw = b"From: " + sender.encode("utf-8") + b"\n" + msg.as_bytes()
    if extra_from is not None:
        raw = b"From: " + extra_from.encode() + b"\n" + raw
    return raw


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Windows runners can expose TEMP itself through an 8.3 alias.
        # Compare/spy on the same resolved paths that list admission opens.
        self.base = Path(self.temp.name).resolve(strict=True)
        self.drop, self.out = self.base / "drop", self.base / "out"
        self.drop.mkdir()
        self.allow = self.base / "known-senders.txt"
        self.allow.write_text("buyer@customer.example.test\ntrusted.example.test\n", encoding="utf-8")
        self.fake = self.base / "fake.json"
        self.enterContext(patch("http.client.HTTPSConnection", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("socket.socket", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        spec = importlib.util.spec_from_file_location("e3_cli", ROOT / "scripts" / "email-intake.py")
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def invoke(self, *, raw=None, category="order", list_path=None, out=None, hint=True, live=False):
        if raw is not None:
            (self.drop / "fictional.eml").write_bytes(raw)
            self.fake.write_text(json.dumps({sha256(raw).hexdigest(): decision(category)}))
        args = ["--drop", str(self.drop), "--out", str(out or self.out)]
        if hint:
            args += ["--known-senders", str(list_path or self.allow)]
        if live:
            args += ["--live", "--ledger", str(self.base / "ledger.sqlite3"), "--init-ledger"]
        else:
            args += ["--fake-results", str(self.fake)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = self.cli.main(args)
            except SystemExit:
                self.fail("CLI rejected the authorized --known-senders option")
        return code, stdout.getvalue(), stderr.getvalue()

    def record(self, out=None):
        return json.loads(next(((out or self.out) / "records").glob("*.json")).read_text())

    def rejected(self, senders):
        for index, sender in enumerate(senders):
            with self.subTest(sender=sender):
                out = self.base / f"case-{index}"
                code, stdout, _ = self.invoke(raw=mail(sender), out=out)
                self.assertEqual(code, 0)
                result = json.loads(stdout)
                self.assertEqual(result["lane"], "needs_a_look")
                self.assertIn(result["reason_code"], {"UNKNOWN_SENDER", "PARSE_FAILED"})
                self.assertEqual(self.record(out)["reader_files"], [])
                self.assertFalse((out / "calls.jsonl").exists())

    def test_display_name_cannot_supply_trusted_address(self):
        self.rejected(['"buyer@customer.example.test" <stranger@outside.example.test>',
                       '"trusted.example.test" <buyer@outside.example.test>',
                       '=?utf-8?b?YnV5ZXJAY3VzdG9tZXIuZXhhbXBsZS50ZXN0?= <a@outside.example.test>'])

    def test_subdomain_and_domain_suffix_prefix_lookalikes(self):
        self.rejected(["buyer@sub.customer.example.test", "a@sub.trusted.example.test",
                       "a@trusted.example.test.evil.test", "a@eviltrusted.example.test",
                       "a@trusted-example.test", "a@trusted.example.test."])

    def test_case_normalization_still_requires_exact_identity(self):
        self.rejected(["STRANGER@CUSTOMER.EXAMPLE.TEST", "A@SUB.TRUSTED.EXAMPLE.TEST"])
        for index, sender in enumerate(["BUYER@CUSTOMER.EXAMPLE.TEST", "A@TRUSTED.EXAMPLE.TEST"]):
            with self.subTest(sender=sender):
                out = self.base / f"positive-{index}"
                self.assertEqual(self.invoke(raw=mail(sender), out=out)[0], 0)
                self.assertEqual(self.record(out)["lane"], "order")

    def test_plus_addressing_never_inherits_address_or_domain_trust(self):
        self.rejected(["buyer+order@customer.example.test", "a+order@trusted.example.test",
                       "BUYER+ORDER@CUSTOMER.EXAMPLE.TEST"])

    def test_internationalized_confusable_and_punycode_domains(self):
        self.rejected(["buyer@custоmer.example.test", "a@trustеd.example.test",
                       "a@trusted。example.test", "a@xn--trusted-9za.example.test",
                       "a@trusted.xn--example-9za.test", "K@trusted.example.test"])

    def test_multiple_from_headers_fail_closed(self):
        for sender in ["buyer@customer.example.test", "a@outside.example.test"]:
            with self.subTest(sender=sender):
                out = self.base / sha256(sender.encode()).hexdigest()
                self.assertEqual(self.invoke(raw=mail(extra_from=sender), out=out)[0], 0)
                self.assertEqual(self.record(out)["lane"], "needs_a_look")
                self.assertFalse((out / "calls.jsonl").exists())

    def test_multiple_mailboxes_and_groups_fail_closed(self):
        self.rejected(["buyer@customer.example.test, a@outside.example.test",
                       "buyer@customer.example.test, a@trusted.example.test",
                       "People: buyer@customer.example.test;",
                       "People: buyer@customer.example.test, a@trusted.example.test;"])

    def test_missing_from_is_retained_for_review(self):
        raw = mail().replace(b"From: buyer@customer.example.test\n", b"")
        self.assertEqual(self.invoke(raw=raw)[0], 0)
        self.assertEqual(self.record()["reason_code"], "PARSE_FAILED")
        self.assertFalse((self.out / "calls.jsonl").exists())

    def test_malformed_from_is_never_promoted(self):
        for index, sender in enumerate(["buyer", "buyer@@customer.example.test", "<>",
                                       "buyer@", "buyer@customer..example.test", '"buyer"@customer.example.test',
                                       "a@[127.0.0.1]", "buyer@customer.example.test (unfinished",
                                       '"buyer"@customer.example.test (comment <trick>)']):
            with self.subTest(sender=sender):
                out = self.base / f"malformed-{index}"
                self.assertEqual(self.invoke(raw=mail(sender), out=out)[0], 0)
                self.assertEqual(self.record(out)["lane"], "needs_a_look")
                self.assertFalse((out / "calls.jsonl").exists())

    def test_missing_list_refuses_before_provider_or_output(self):
        with patch.object(self.cli, "FakeProvider", side_effect=AssertionError("provider constructed")):
            code, stdout, _ = self.invoke(raw=mail(), list_path=self.base / "missing.txt")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["reason_code"], "SENDER_LIST_ERROR")
        self.assertFalse(self.out.exists())

    def test_empty_and_whitespace_list_refuse(self):
        for content in ["", " \n\t\r\n"]:
            with self.subTest(content=content):
                self.allow.write_text(content)
                self.assertEqual(self.invoke(raw=mail())[0], 2)
                self.assertFalse(self.out.exists())

    def test_malformed_list_refuses_entire_file(self):
        entries = ["*@trusted.example.test", "*.trusted.example.test", "@trusted.example.test",
                   "buyer+order@customer.example.test", "Name <buyer@customer.example.test>",
                   "customer.example.test.", "localhost", "[127.0.0.1]", "a..b@trusted.example.test",
                   "custоmer.example.test", "xn--trusted-9za.example.test", "a@-trusted.example.test",
                   "a@trusted_.example.test", "a@@trusted.example.test", "a@trusted.example.test,b@trusted.example.test",
                   "# comment", "a@trusted.example.test\x00", "a@" + "a" * 64 + ".test"]
        for entry in entries:
            with self.subTest(entry=entry):
                self.allow.write_text("buyer@customer.example.test\n" + entry + "\n", encoding="utf-8")
                code, stdout, _ = self.invoke(raw=mail())
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stdout)["reason_code"], "SENDER_LIST_ERROR")
                self.assertFalse(self.out.exists())

    def test_invalid_encoding_directory_and_unreadable_list_refuse(self):
        self.allow.write_bytes(b"\xff\xfe")
        self.assertEqual(self.invoke(raw=mail())[0], 2)
        self.assertEqual(self.invoke(list_path=self.drop)[0], 2)
        self.allow.write_text("trusted.example.test\n")
        original_open = Path.open
        def blocked(path, *args, **kwargs):
            if path == self.allow:
                raise PermissionError("fictional denial")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", blocked):
            self.assertEqual(self.invoke()[0], 2)
        self.assertFalse(self.out.exists())

    def test_env_named_list_never_opened(self):
        with patch.object(Path, "open", side_effect=AssertionError("must not open")):
            code, stdout, _ = self.invoke(list_path=self.base / ".env.fake")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["reason_code"], "SENDER_LIST_ERROR")

    def test_bad_list_does_not_initialize_live_ledger_or_lookup_key(self):
        get_env = self.cli.os.environ.get
        def checked_env(key, *args):
            if key == "OPENAI_API_KEY":
                self.fail("key lookup")
            return get_env(key, *args)
        with patch.object(self.cli, "SpendLedger", side_effect=AssertionError("ledger constructed")), \
             patch.object(self.cli.os.environ, "get", side_effect=checked_env):
            self.assertEqual(self.invoke(raw=mail(), list_path=self.base / "missing.txt", live=True)[0], 2)
        self.assertFalse((self.base / "ledger.sqlite3").exists())

    def test_exact_address_domain_and_display_name_positive_controls(self):
        for index, sender in enumerate(["buyer@customer.example.test", "other@trusted.example.test",
                                       '"Fictional Buyer" <buyer@customer.example.test>',
                                       "buyer@customer.example.test (Fictional Buyer)"]):
            with self.subTest(sender=sender):
                out = self.base / f"known-{index}"
                self.assertEqual(self.invoke(raw=mail(sender), out=out)[0], 0)
                self.assertEqual(self.record(out)["lane"], "order")

    def test_unknown_all_classifier_categories_stay_visible_and_free(self):
        for category in PAIRS:
            with self.subTest(category=category):
                out = self.base / category
                self.assertEqual(self.invoke(raw=mail("a@outside.example.test"), category=category, out=out)[0], 0)
                self.assertEqual(self.record(out)["reason_code"], "UNKNOWN_SENDER")
                self.assertFalse((out / "calls.jsonl").exists())

    def test_hint_off_is_byte_identical_to_existing_runner(self):
        raw = mail("a+tag@outside.example.test")
        self.assertEqual(self.invoke(raw=raw, hint=False)[0], 0)
        other = self.base / "other"
        run(self.drop, other, FakeProvider({sha256(raw).hexdigest(): decision("order")}))
        paths = sorted(p.relative_to(self.out) for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(paths, sorted(p.relative_to(other) for p in other.rglob("*") if p.is_file()))
        for path in paths:
            self.assertEqual((self.out / path).read_bytes(), (other / path).read_bytes())
        self.assertEqual(self.record()["lane"], "order")

    def test_known_sender_does_not_override_existing_review_rules(self):
        cases = [("change", mail(), "change_requested"), ("order", mail(attachment=False), "TEXT_ONLY_ORDER"),
                 ("order", mail(body=""), "unclear")]
        for index, (category, raw, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                out = self.base / f"review-{index}"
                self.assertEqual(self.invoke(raw=raw, category=category, out=out)[0], 0)
                self.assertEqual(self.record(out)["reason_code"], reason)

    def test_existing_outcomes_cannot_bypass_new_or_changed_policy(self):
        raw = mail("a@outside.example.test")
        self.assertEqual(self.invoke(raw=raw, hint=False)[0], 0)
        before = next((self.out / "records").glob("*.json")).read_bytes()
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(next((self.out / "records").glob("*.json")).read_bytes(), before)
        fresh = self.base / "fresh"
        self.assertEqual(self.invoke(raw=raw, out=fresh)[0], 0)
        before = next((fresh / "records").glob("*.json")).read_bytes()
        self.allow.write_text("outside.example.test\n")
        self.assertEqual(self.invoke(out=fresh)[0], 2)
        self.assertEqual(self.invoke(out=fresh, hint=False)[0], 2)
        self.assertEqual(next((fresh / "records").glob("*.json")).read_bytes(), before)

    def test_same_policy_replay_is_immutable_and_no_new_call(self):
        self.assertEqual(self.invoke(raw=mail())[0], 0)
        record = next((self.out / "records").glob("*.json"))
        before = record.read_bytes()
        self.allow.write_text("TRUSTED.EXAMPLE.TEST\nBUYER@CUSTOMER.EXAMPLE.TEST\ntrusted.example.test\n")
        code, stdout, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["reused"])
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(len((self.out / "calls.jsonl").read_text().splitlines()), 1)

    def test_classifier_schema_has_no_sender_reason(self):
        self.assertNotIn("UNKNOWN_SENDER", SCHEMA["properties"]["reason_code"]["enum"])

    def test_other_headers_and_body_cannot_supply_sender_identity(self):
        raw = mail("stranger@outside.example.test", body="buyer@customer.example.test")
        raw = (b"Reply-To: buyer@customer.example.test\nSender: buyer@customer.example.test\n"
               b"Return-Path: <buyer@customer.example.test>\n" + raw)
        self.assertEqual(self.invoke(raw=raw)[0], 0)
        self.assertEqual(self.record()["reason_code"], "UNKNOWN_SENDER")
        self.assertFalse((self.out / "calls.jsonl").exists())

    def test_unknown_empty_unsupported_and_duplicates_remain_recoverable(self):
        for index, raw in enumerate([mail("a@outside.example.test", body=""),
                                    mail("a@outside.example.test").replace(b"%PDF-", b"wrong")]):
            with self.subTest(index=index):
                out = self.base / f"unknown-{index}"
                (self.drop / "copy.eml").write_bytes(raw)
                self.assertEqual(self.invoke(raw=raw, out=out)[0], 0)
                records = [json.loads(p.read_text()) for p in (out / "records").glob("*.json")]
                self.assertEqual(len(records), 2)
                self.assertTrue(any(r["duplicate_of"] for r in records))
                for record in records:
                    self.assertEqual(record["reason_code"], "UNKNOWN_SENDER")
                    self.assertEqual(record["reader_files"], [])
                    self.assertEqual((out / record["original"]).read_bytes(), raw)
                    self.assertEqual(len(record["attachment_manifest"]), 1)
                self.assertFalse((out / "calls.jsonl").exists())

    def test_oversize_list_and_control_delimiters_refuse(self):
        for data in [b"trusted.example.test\n" * 4000,
                     b"trusted.example.test\vbuyer@customer.example.test",
                     b"trusted.example.test\f", b"trusted.example.test\x7f"]:
            with self.subTest(data=data[:32]):
                self.allow.write_bytes(data)
                self.assertEqual(self.invoke(raw=mail())[0], 2)
                self.assertFalse(self.out.exists())

    def test_bom_crlf_whitespace_and_case_list_positive(self):
        self.allow.write_bytes(b"\xef\xbb\xbf  BUYER@CUSTOMER.EXAMPLE.TEST \r\n\r\n\tTRUSTED.EXAMPLE.TEST\t\r\n")
        self.assertEqual(self.invoke(raw=mail())[0], 0)
        self.assertEqual(self.record()["lane"], "order")

    def test_env_parent_and_stream_list_never_opened(self):
        for path in [self.base / ".env.private" / "list.txt", self.base / ".ENVdir" / "list.txt",
                     self.base / ".ENVfictional. ", self.base / "list.txt:stream",
                     self.base / "list.txt::$DATA"]:
            with self.subTest(path=path.name):
                with patch.object(Path, "open", side_effect=AssertionError("must not open")):
                    self.assertEqual(self.invoke(list_path=path)[0], 2)

    def test_corrupt_policy_never_replays_or_calls_provider(self):
        self.assertEqual(self.invoke(raw=mail())[0], 0)
        (self.out / "sender-policy.json").write_bytes(b"{}")
        before = next((self.out / "records").glob("*.json")).read_bytes()
        with patch.object(FakeProvider, "classify", side_effect=AssertionError("no new call")):
            self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(next((self.out / "records").glob("*.json")).read_bytes(), before)

    def test_unknown_sender_never_reserves_even_with_live_provider(self):
        # No actual key/transport; a fictional literal is sufficient to exercise
        # the admission point before the live reservation code.
        from email_intake.ledger import SpendLedger
        from email_intake.providers import LiveProvider
        from email_intake.senders import load
        raw = mail("a@outside.example.test")
        (self.drop / "fictional.eml").write_bytes(raw)
        ledger = SpendLedger(self.base / "owned.sqlite3", initialize=True)
        provider = LiveProvider(enabled=True, api_key="fictional-not-a-key", ledger=ledger,
                                send=lambda *_: self.fail("transport called"))
        with patch.object(ledger, "reserve", side_effect=AssertionError("reservation attempted")):
            results = run(self.drop, self.out, provider, known_senders=load(self.allow))
        self.assertEqual(results[0]["reason_code"], "UNKNOWN_SENDER")
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_quoted_local_part_with_comment_cannot_inherit_trust(self):
        self.rejected(['"buyer"@customer.example.test (comment <trick>)',
                       '"buyer"(note)@customer.example.test'])

    def test_long_raw_from_matching_is_time_bounded(self):
        # A subprocess deadline keeps a future backtracking regression from
        # hanging the suite. Time only E3 matching, not stdlib header parsing.
        probe = '''
import time
from email import policy
from email.parser import Parser
from email_intake.senders import from_address
header = Parser(policy=policy.default).parsestr("From: a@trusted.example.test\\n\\n")["From"]
cases = ["(" + " " * 32000 + ") a@trusted.example.test",
         " " * 32000 + "<a@trusted.example.test",
         '"' + " " * 32000,
         "a@trusted.example.test (" + " " * 32000,
         " " * 32000 + "<a@trusted.example.test>"]
start = time.perf_counter()
for raw in cases:
    for _ in range(5):
        expected = "a@trusted.example.test" if raw == cases[-1] else None
        assert from_address(header, raw) == expected
print(time.perf_counter() - start)
'''
        result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                                capture_output=True, text=True, timeout=2, check=True)
        self.assertLess(float(result.stdout), 0.5)

    def test_resolved_short_name_env_components_never_opened(self):
        # Synthetic long names only; no .env file/directory is created or read.
        for resolved in [self.base / ".envfictional", self.base / ".envdir" / "list.txt"]:
            with self.subTest(resolved=resolved.name), \
                 patch.object(Path, "resolve", return_value=resolved), \
                 patch.object(Path, "open", side_effect=AssertionError("must not open")):
                with self.assertRaises(SenderListError):
                    load(self.allow)

    def test_symlink_components_never_opened(self):
        # Also covers machines where creating real symlinks needs a privilege.
        for component in [self.allow, self.base]:
            original = Path.is_symlink
            with self.subTest(component=component.name), \
                 patch.object(Path, "is_symlink", lambda path: path == component or original(path)), \
                 patch.object(Path, "open", side_effect=AssertionError("must not open")):
                with self.assertRaises(SenderListError):
                    load(self.allow)

    @unittest.skipUnless(hasattr(Path, "is_junction"), "Python lacks junction detection")
    def test_junction_components_never_opened(self):
        for component in [self.allow, self.base]:
            original = Path.is_junction
            with self.subTest(component=component.name), \
                 patch.object(Path, "is_junction", lambda path: path == component or original(path)), \
                 patch.object(Path, "open", side_effect=AssertionError("must not open")):
                with self.assertRaises(SenderListError):
                    load(self.allow)

    @unittest.skipUnless(os.name == "nt", "Windows junction probe")
    def test_real_junction_list_never_opened(self):
        import _winapi
        junction = self.base / "junction"
        _winapi.CreateJunction(str(self.base), str(junction))
        self.addCleanup(junction.rmdir)
        self.assertTrue(junction.is_junction())
        with patch.object(Path, "open", side_effect=AssertionError("must not open")):
            with self.assertRaises(SenderListError):
                load(junction / self.allow.name)

    @unittest.skipUnless(os.name == "nt", "Windows short-name probe")
    def test_real_short_name_resolves_to_long_name(self):
        import ctypes
        from ctypes import wintypes
        get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        count = get_short(str(self.allow), buffer, len(buffer))
        self.assertTrue(0 < count < len(buffer))
        short = Path(buffer.value)
        if str(short).lower() == str(self.allow).lower():
            self.skipTest("8.3 names unavailable on this volume")
        self.assertEqual(short.resolve(strict=True), self.allow)
        self.assertEqual(load(short), load(self.allow))

    def test_shared_domains_admit_any_supported_mailbox(self):
        self.allow.write_text("gmail.com\nco.uk\n", encoding="utf-8")
        known = load(self.allow)
        self.assertTrue(known.matches("anyone@gmail.com"))
        self.assertTrue(known.matches("anyone@co.uk"))
        self.assertFalse(known.matches("anyone@sub.co.uk"))


if __name__ == "__main__":
    unittest.main()
