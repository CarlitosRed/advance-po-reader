"""Tests for the second fictional set (`--profile po-inbox`) and the unchanged default profile."""

import copy
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from collections import Counter
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools" / "email-testset"
sys.path.insert(0, str(TOOLS))
import generate  # noqa: E402
import score  # noqa: E402
from email_testset_contract import (  # noqa: E402
    CATEGORY_LANE, KNOWN_SENDER_CASES, LANE_REASONS, MUTATIONS, PO_INBOX_MUTATIONS, SENDER_CASES, sender_is_known,
)
sys.path.pop(0)

SEED = 20261012


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def run_generator(*args):
    return subprocess.run([sys.executable, str(TOOLS / "generate.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def hash_tree(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.iterdir())}


class PoInboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-po-inbox-")
        cls.root = Path(cls.temp.name)
        cls.generated = cls.root / "set"
        cls.expected = generate.generate(SEED, cls.generated, "po-inbox")
        cls.truth = {row["id"]: row for row in cls.expected}
        cls.perfect = [{key: row[key] for key in ("id", "category", "lane")} for row in cls.expected]
        cls.known = (cls.generated / "known-senders.txt").read_text(encoding="ascii").splitlines()
        print("\nPO-inbox coverage table (seed %d):\n%s" % (SEED, generate.coverage_table(cls.expected)))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def parse(self, row):
        return BytesParser(policy=policy.default).parsebytes((self.generated / f"{row['id']}.eml").read_bytes())

    def run_score(self, answers, expected=None):
        with tempfile.TemporaryDirectory(dir=self.root) as dirname:
            labels, predictions = Path(dirname) / "expected.jsonl", Path(dirname) / "answers.jsonl"
            write_jsonl(labels, self.expected if expected is None else expected)
            write_jsonl(predictions, answers)
            return subprocess.run([sys.executable, str(TOOLS / "score.py"), "--expected", str(labels),
                                   "--answers", str(predictions)], capture_output=True, text=True, encoding="utf-8", timeout=30)

    # --- done-when 1: determinism, volume, coverage ---------------------------------

    def test_same_seed_is_byte_identical_across_two_fresh_processes(self):
        first, second = self.root / "proc-a", self.root / "proc-b"
        for out in (first, second):
            result = run_generator("--seed", str(SEED), "--out", str(out), "--profile", "po-inbox")
            self.assertEqual(result.returncode, 0, result.stderr)
        hashes = hash_tree(first)
        self.assertEqual(hashes, hash_tree(second))
        self.assertEqual(hashes, hash_tree(self.generated))
        self.assertEqual(len(hashes), 147 + 2)  # emails + expected.jsonl + known-senders.txt

    def test_different_seed_changes_bytes_but_not_coverage(self):
        rows = generate.generate(17, self.root / "other-seed", "po-inbox")
        self.assertNotEqual(rows, self.expected)
        for field in ("category", "lane", "sender_case"):
            self.assertEqual(Counter(r[field] for r in rows), Counter(r[field] for r in self.expected), field)

    def test_at_least_100_orders_and_about_85_percent_of_the_mix(self):
        orders = [row for row in self.expected if row["category"] == "order"]
        self.assertGreaterEqual(len(orders), 100)
        self.assertGreaterEqual(sum(row["number_of_orders"] for row in self.expected), 100)
        self.assertTrue(0.83 <= len(orders) / len(self.expected) <= 0.88, len(orders) / len(self.expected))
        self.assertEqual(len({row["id"] for row in self.expected}), len(self.expected))

    def test_every_category_sender_case_lane_reason_and_tag_is_covered(self):
        categories = Counter(row["category"] for row in self.expected)
        self.assertEqual(set(categories), set(CATEGORY_LANE))
        self.assertEqual(Counter({c: n for c, n in categories.items() if c != "order"}),
                         Counter(change=3, cancellation=3, status_question=3, quote_request=3, spam=2,
                                 invoice=2, other_business=3, unsure=2))
        cases = Counter(row["sender_case"] for row in self.expected)
        orders_by_case = Counter(row["sender_case"] for row in self.expected if row["category"] == "order")
        for case in SENDER_CASES:
            self.assertGreaterEqual(cases[case], 5, case)
            self.assertGreaterEqual(orders_by_case[case], 5, case)
        reasons = Counter(row.get("lane_reason") for row in self.expected)
        for reason in LANE_REASONS:
            self.assertGreaterEqual(reasons[reason], 3, reason)
        tags = Counter(tag for row in self.expected for tag in row["mutation_tags"])
        for tag in PO_INBOX_MUTATIONS:
            self.assertGreaterEqual(tags[tag], 3, tag)
        for tag in ("pdf_only_order", "png_scan_standin", "inline_image", "multiple_orders", "body_only_order"):
            self.assertGreaterEqual(tags[tag], 5, tag)
        self.assertEqual({row["language"] for row in self.expected}, {"en", "es", "en-es"})

    def test_coverage_table_is_printed_by_the_cli(self):
        result = run_generator("--seed", str(SEED), "--out", str(self.root / "cli-table"), "--profile", "po-inbox")
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected_line in ("category      order", "lane          needs_a_look", "sender case   display_name_trick",
                              "lane reason   text_only_order", "tag           recap_in_body"):
            self.assertIn(expected_line, result.stdout)
        self.assertEqual(result.stdout.splitlines()[1:], generate.coverage_table(self.expected).splitlines())

    # --- done-when 1: default profile unchanged -------------------------------------

    def test_default_profile_output_hashes_are_unchanged_versus_origin_main(self):
        golden = json.loads((HERE / "default_profile_hashes.json").read_text(encoding="utf-8"))
        out = self.root / "default-again"
        rows = generate.generate(golden["seed"], out)
        self.assertEqual(len(rows), 200)
        # Same bytes whether `profile` is omitted or spelled out, and via a fresh process.
        explicit = generate.generate(golden["seed"], self.root / "default-explicit", "default")
        self.assertEqual(rows, explicit)
        result = run_generator("--seed", str(golden["seed"]), "--out", str(self.root / "default-cli"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("Generated 200 fictional emails; 120 order emails, 150 new orders."))
        self.assertEqual(sorted(path.name for path in out.iterdir()), sorted([f"{r}.eml" for r in golden["emails"]] + ["expected.jsonl"]))
        # PNG bytes depend on the zlib build; the frozen hashes come from zlib 1.3.1.
        for directory in (out, self.root / "default-cli"):
            for fixture_id, digest in golden["emails"].items():
                path = directory / f"{fixture_id}.eml"
                if zlib.ZLIB_VERSION == golden["zlib_version"] or b"image/png" not in path.read_bytes():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, fixture_id)
            if zlib.ZLIB_VERSION == golden["zlib_version"]:
                self.assertEqual(hashlib.sha256((directory / "expected.jsonl").read_bytes()).hexdigest(), golden["expected_jsonl_sha256"])
        self.assertNotIn("sender", rows[0])
        self.assertNotIn("known-senders.txt", [path.name for path in out.iterdir()])

    def test_unknown_profile_and_occupied_directory_are_refused(self):
        with self.assertRaises(ValueError):
            generate.generate(1, self.root / "nope", "bogus")
        with self.assertRaises(ValueError):
            generate.generate(1, self.generated, "po-inbox")
        self.assertEqual(run_generator("--seed", "1", "--out", str(self.root / "x"), "--profile", "bogus").returncode, 2)
        result = run_generator("--seed", "1", "--out", str(self.generated), "--profile", "po-inbox")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_generation_does_not_require_network_or_environment(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch.dict("os.environ", {}, clear=True):
            generate.generate(88, self.root / "offline", "po-inbox")

    # --- done-when 1: the scorer accepts the new expected.jsonl ---------------------

    def test_scorer_accepts_new_expected_rows_and_perfect_answers(self):
        for row in self.expected:
            score.validate_row(copy.deepcopy(row), expected=True)
        result = self.run_score(self.perfect)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["emails"], report["true_order_emails"]), (147, 126))
        self.assertEqual((report["lost_order_emails"], report["lost_orders"]), (0, 0))
        self.assertEqual(report["order_or_needs_a_look_recall"], 1.0)
        self.assertEqual(report["order_precision"], 1.0)
        self.assertTrue(report["pass_bar_met"])
        # Direct recall equals the share of orders the set expects in the Sure lane.
        sure = sum(1 for row in self.expected if row["category"] == "order" and row["lane"] == "order")
        self.assertAlmostEqual(report["order_recall"], sure / 126)

    def test_losing_a_text_only_order_is_still_a_lost_order(self):
        answers = copy.deepcopy(self.perfect)
        index = next(i for i, row in enumerate(self.expected) if row.get("lane_reason") == "text_only_order")
        answers[index].update(category="spam", lane="no")
        result = self.run_score(answers)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["lost_orders"], 1)

    def test_scorer_contract_for_the_default_profile_stays_strict(self):
        bad_answers = [dict(id="a", category="invoice", lane="needs_a_look"), dict(id="a", category="spam", lane="needs_a_look"),
                       dict(id="a", category="order", lane="not_an_order"), dict(id="a", category="unsure", lane="order")]
        for answer in bad_answers:
            with self.assertRaises(score.InvalidInput, msg=answer):
                score.validate_row(dict(answer), expected=False)
        for answer in (dict(id="a", category="order", lane="needs_a_look"), dict(id="a", category="status_question", lane="needs_a_look")):
            score.validate_row(dict(answer), expected=False)

    def test_new_optional_fields_fail_closed(self):
        sample = next(r for r in self.expected if r.get("lane_reason") == "unknown_sender")
        plain = next(r for r in self.expected if r["category"] == "order" and "lane_reason" not in r)
        multi = next(r for r in self.expected if "attachment_roles" in r and len(r["attachment_roles"]) == 3)
        edits = [
            (sample, "lane", "order"), (sample, "lane_reason", "text_only_order"), (sample, "lane_reason", "bogus"),
            (sample, "known_sender", True), (sample, "sender_case", "known_address"), (sample, "sender_case", "nope"),
            (sample, "sender", "not an address"), (sample, "known_sender", "yes"),
            (plain, "lane_reason", "unknown_sender"), (plain, "lane", "needs_a_look"),
            (multi, "attachment_roles", {}), (multi, "attachment_roles", {"x.pdf": "order"}),
            (multi, "attachment_roles", {name: "other" for name in multi["attachment_roles"]}),
            (multi, "attachment_roles", {name: ("logo_image" if role == "order" else role) for name, role in multi["attachment_roles"].items()}),
        ]
        for row, field, value in edits:
            with self.subTest(field=field, value=value):
                broken = copy.deepcopy(row)
                broken[field] = value
                with self.assertRaises(score.InvalidInput):
                    score.validate_row(broken, expected=True)
        row = copy.deepcopy(sample)
        del row["sender_case"]
        with self.assertRaises(score.InvalidInput):
            score.validate_row(row, expected=True)
        row = copy.deepcopy(sample)
        row["surprise"] = 1
        with self.assertRaises(score.InvalidInput):
            score.validate_row(row, expected=True)

    # --- known-senders file and the reference rule -----------------------------------

    def test_known_senders_file_is_fictional_one_entry_per_line(self):
        raw = (self.generated / "known-senders.txt").read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"\r", raw)
        self.assertNotIn(b"\xef\xbb\xbf", raw)
        entries = raw.decode("ascii").splitlines()
        self.assertEqual(entries, generate.known_senders_text().splitlines())
        self.assertEqual(len(entries), len(set(entries)))
        self.assertTrue(any("@" in entry for entry in entries) and any("@" not in entry for entry in entries))
        for entry in entries:
            self.assertEqual(entry, entry.strip())
            self.assertRegex(entry, r"^(?:[a-z0-9.+-]+@)?[a-z0-9-]+\.example\.test$")

    def test_sender_rule_examples(self):
        entries = ["buyer@taller-nemul.example.test", "opra-trading.example.test"]
        for address, known in (
            ("buyer@taller-nemul.example.test", True), ("BUYER@TALLER-NEMUL.example.test", True),
            ("buyer+po7@taller-nemul.example.test", True), ("anyone@opra-trading.example.test", True),
            ("anyone@OPRA-TRADING.example.test", True), ("buyer@mail.taller-nemul.example.test", False),
            ("buyer@taller-nemul.example.test.relay.example.test", False), ("buyer@taller-nernul.example.test", False),
            ("anyone@billing.opra-trading.example.test", False), ("other@taller-nemul.example.test", False),
            ("orders@quick-parts.example.test", False),
        ):
            self.assertEqual(sender_is_known(address, entries), known, address)

    # --- every email: parses, labels match what is visible ---------------------------

    def test_every_email_parses_and_sender_labels_match_the_reference_rule(self):
        for row in self.expected:
            with self.subTest(fixture=row["id"]):
                payload = (self.generated / f"{row['id']}.eml").read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])
                message = BytesParser(policy=policy.default).parsebytes(payload)
                for part in message.walk():
                    self.assertEqual(part.defects, [])
                self.assertTrue(str(message["Message-ID"]).endswith("@mail.example.test>"))
                (sender,) = message["From"].addresses
                self.assertEqual(sender.addr_spec, row["sender"])
                self.assertEqual(sender_is_known(sender.addr_spec, self.known), row["known_sender"])
                self.assertEqual(row["known_sender"], row["sender_case"] in KNOWN_SENDER_CASES)
                (recipient,) = message["To"].addresses
                self.assertEqual(recipient.addr_spec, "po@velora.example.test")
                for address in re.findall(rb"[A-Za-z0-9._+-]+@([A-Za-z0-9.-]+)", payload):
                    self.assertTrue(address.lower().endswith(b".example.test"), address)
                case = row["sender_case"]
                if case == "display_name_trick":
                    self.assertIn("@", sender.display_name)
                    self.assertTrue(sender_is_known(sender.display_name, self.known))
                if case == "case_variant":
                    self.assertNotEqual(sender.addr_spec, sender.addr_spec.lower())
                if case == "plus_address":
                    self.assertIn("+", sender.username)
                if case == "subdomain_trick":
                    self.assertNotIn(sender.domain, self.known)
                # Expected lane follows the written rules.
                if row["category"] == "order":
                    text_only = "text_only_order" in row["mutation_tags"]
                    want = "needs_a_look" if text_only or not row["known_sender"] else "order"
                    self.assertEqual(row["lane"], want)
                elif row["category"] in ("change", "cancellation", "quote_request", "unsure", "status_question"):
                    self.assertEqual(row["lane"], "needs_a_look")
                else:
                    self.assertEqual(row["lane"], "not_an_order")

    def test_order_scenarios_are_visible_in_the_messages(self):
        seen = Counter()
        for row in self.expected:
            message = self.parse(row)
            body_part = message.get_body(preferencelist=("plain",))
            body = body_part.get_content() if body_part else ""
            attachments = {part.get_filename(): part for part in message.iter_attachments()}
            tags = set(row["mutation_tags"])
            sources = row["where_order"]
            if row["category"] != "order":
                self.assertEqual(sources, {"body": False, "attachments": []})
                self.assertNotRegex(body, r"(?:NEW PURCHASE ORDER|ORDEN DE COMPRA NUEVA)")
                self.assertFalse(any("PURCHASE ORDER" in (p.get_payload(decode=True) or b"").decode("latin-1") for p in attachments.values()))
                if row["category"] == "invoice":
                    self.assertEqual(len(attachments), 1)
                else:
                    self.assertEqual(attachments, {})
                continue
            self.assertEqual(set(sources["attachments"]), {n for n, role in row.get("attachment_roles", {}).items() if role == "order"})
            self.assertTrue(set(row.get("attachment_roles", {})) == set(attachments))
            for name in sources["attachments"]:
                text = attachments[name].get_payload(decode=True)
                self.assertIn(b"FICT-", text) if name.endswith(".pdf") else self.assertEqual(attachments[name].get_content_type(), "image/png")
            if "text_only_order" in tags:
                seen["text_only"] += 1
                self.assertEqual(attachments, {})
                self.assertEqual(row["number_of_orders"], 1)
                self.assertRegex(body, r"(?:NEW PURCHASE ORDER|ORDEN DE COMPRA NUEVA|PURCHASE ORDER) FIC-")
            else:
                self.assertEqual(row["number_of_orders"], len(sources["attachments"]))
            if "empty_body" in tags:
                seen["empty_body"] += 1
                self.assertEqual(body.strip(), "")
                self.assertEqual(len(attachments), 1)
                self.assertFalse(sources["body"])
            if "cover_note" in tags:
                seen["cover_note"] += 1
                self.assertNotIn("FIC-", body)
                self.assertFalse(sources["body"])
            if "recap_in_body" in tags:
                seen["recap"] += 1
                self.assertTrue(sources["body"] and len(sources["attachments"]) == 1)
                self.assertEqual(row["number_of_orders"], 1)
                po = sources["attachments"][0].removesuffix(".pdf")
                self.assertIn(po, body)
                self.assertIn(b"FICT-", attachments[sources["attachments"][0]].get_payload(decode=True))
            if "multi_attachment" in tags and "multiple_orders" not in tags:
                seen["po_packing_logo"] += 1
                roles = row["attachment_roles"]
                self.assertEqual(sorted(roles.values()), ["logo_image", "order", "packing_list"])
                self.assertEqual(row["number_of_orders"], 1)
                for name, role in roles.items():
                    payload = attachments[name].get_payload(decode=True)
                    if role == "packing_list":
                        self.assertNotIn(b"PURCHASE ORDER", payload)
                        self.assertNotIn(b"ORDEN DE COMPRA", payload)
                    if role == "logo_image":
                        width, height = struct.unpack(">II", payload[16:24])
                        self.assertLess(len(payload), 5 * 1024)
                        self.assertLess(max(width, height), 100)
                        self.assertEqual(attachments[name].get_content_type(), "image/png")
            if "multiple_orders" in tags:
                seen["multi_po"] += 1
                self.assertGreaterEqual(row["number_of_orders"], 2)
            if "png_scan_standin" in tags:
                seen["png"] += 1
        self.assertEqual(seen, Counter(text_only=14, empty_body=44, cover_note=24, recap=16, po_packing_logo=16, multi_po=6, png=6))

    def test_all_pdfs_have_valid_xref_and_pngs_have_valid_crcs(self):
        pdfs = pngs = 0
        for row in self.expected:
            for attachment in self.parse(row).iter_attachments():
                payload = attachment.get_payload(decode=True)
                if attachment.get_content_type() == "application/pdf":
                    startxref = int(re.search(rb"startxref\n(\d+)\n", payload).group(1))
                    self.assertEqual(payload[startxref:startxref + 4], b"xref")
                    self.assertTrue(payload.startswith(b"%PDF-1.4\n") and payload.endswith(b"%%EOF\n"))
                    pdfs += 1
                else:
                    self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
                    pos = 8
                    while pos < len(payload):
                        size = struct.unpack(">I", payload[pos:pos + 4])[0]
                        kind, data = payload[pos + 4:pos + 8], payload[pos + 8:pos + 8 + size]
                        self.assertEqual(struct.unpack(">I", payload[pos + 8 + size:pos + 12 + size])[0], zlib.crc32(kind + data))
                        pos += 12 + size
                    self.assertEqual(pos, len(payload))
                    pngs += 1
        self.assertGreater(pdfs, 100)
        self.assertGreater(pngs, 20)

    def test_mutation_vocabulary_of_the_old_profile_is_untouched(self):
        self.assertEqual(len(MUTATIONS), 22)
        self.assertFalse(set(MUTATIONS) & set(PO_INBOX_MUTATIONS))
        for row in self.expected:
            self.assertTrue(set(row["mutation_tags"]) <= set(MUTATIONS) | set(PO_INBOX_MUTATIONS))


if __name__ == "__main__":
    unittest.main()
