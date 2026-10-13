"""Convert an email-intake runner --out folder into answers.jsonl for score.py.

Exit 0: answers.jsonl written; 2: anything missing, malformed, unknown, unsafe or
not provably this run's record for the expected email (nothing is written). Offline,
no model calls, deterministic: same inputs give the same bytes. Rows follow the
order of expected.jsonl.

The answer is the runner's own final category and lane, unchanged. The only
adaptation is vocabulary: the runner's local reason codes (CONFLICT, LIMIT,
PDF_LIMIT, TEXT_ONLY_ORDER, UNKNOWN_SENDER, ...) are not in the scorer's contract. Such a record
always has category unsure and lane needs_a_look, so it becomes
{"category":"unsure","lane":"needs_a_look"} with reason_code omitted (the scorer
accepts the omission). No label is invented and none is changed: a record the
runner did not classify never becomes an order or a not_an_order answer, and
text-only, reply or attachment policies belong to the runner, not to this glue.

Every record is checked against the exact shape the runner writes (types, nested
entries, stored paths, identifiers), against the parser's output domain and bounds,
against the runner's routing (the classification it could have recorded, the final
outcome, and the complete reader-file list it prepares), against the other records
of the folder (duplicates, related emails, message-id conflicts) and against the
expected file before any answer is produced. A record the expected data cannot
identify (an oversized source keeps only a bounded-prefix hash) is rejected, never
substituted. Values that depend only on the source bytes (sender, subject, body
text, file names, sizes, digests) are checked against the parser's domain, not
re-derived: the runner folder does not prove them.

The answers file is written to a fresh, uniquely named temporary file and then
hard-linked into place, which refuses an existing file. Where hard links are not
available the converter refuses (exit 2) instead of risking another writer's file.
"""

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))  # the producer package, after this tool's own folder

import score  # noqa: E402
from email_intake import VERSION as RUNNER_VERSION  # noqa: E402
from email_intake.body_pdf import render  # noqa: E402
from email_intake.contract import LOCAL_REASONS, PAIRS  # noqa: E402
from email_intake.ledger import INPUT_BOUND  # noqa: E402
from email_intake.parser import (MAX_ATTACHMENTS, MAX_BODY, MAX_EMAIL, SAFE_EXTENSIONS,  # noqa: E402
                                 SUPPORTED, Parsed)
from email_intake.providers import request_for  # noqa: E402
from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON, LANES  # noqa: E402

ACCEPTED_VERSIONS = frozenset({RUNNER_VERSION})
PARSER_VERSIONS = frozenset({"mime-v1"})  # email_intake.runner writes this literal
HASH_KINDS = frozenset({"sha256", "bounded_prefix_and_size"})
PROVIDERS = frozenset({"fake", "live"})
# Reasons a record can carry when the runner stopped before parsed fields existed:
# every ParseError the parser raises, plus the runner's own LIMIT for an oversized source.
PRE_PARSE_REASONS = frozenset({"LIMIT", "PARSE_FAILED"})
# Pending reasons each provider's classify() can return (a test derives them from the producer source).
# FakeProvider: contract.validate() -> INVALID / CONFLICT. LiveProvider: its own early exits,
# ledger errors (LEDGER, CAP, TRANSPORT_PENDING), unpack() and validate().
PROVIDER_PENDING = {
    "fake": frozenset({"INVALID", "CONFLICT"}),
    "live": frozenset({"LIVE_DISABLED", "MISSING_KEY", "LEDGER", "LIMIT", "CAP", "TRANSPORT_PENDING",
                       "INCOMPLETE", "INVALID", "REFUSED", "CONFLICT"}),
}
# LiveProvider returns one of these before any request when the request is over INPUT_BOUND.
LIVE_BEFORE_SIZE = frozenset({"LIVE_DISABLED", "MISSING_KEY", "LEDGER", "LIMIT"})
QUIET = "quiet_attachment_review"
MAX_RECORD_BYTES = 1024 * 1024
EXTENSIONS = {media: value[0] for media, value in SUPPORTED.items()}
SENDER_POLICY = "sender-policy.json"  # email_intake.runner, written by a --known-senders run
ROOT_ENTRIES = frozenset({"records", "sources", "calls.jsonl", "quiet-digest.jsonl", ".intake-guard", SENDER_POLICY})
LOCK_NAME = ".intake-lock"
# The runner's own hold for a sender outside the --known-senders list (only in a folder with SENDER_POLICY).
UNKNOWN_SENDER = "UNKNOWN_SENDER"
MAX_POLICY_BYTES = 4096

BASE = frozenset({
    "version", "parser_version", "record_id", "intake_id", "source_size", "source_name",
    "original", "source_hash_kind", "human_product_approval_required", "reader_files",
    "needs_a_look", "duplicate_of", "related_intakes", "attachment_manifest", "provider",
    "category", "lane", "reason_code"})
# Written together once the email parsed; absent together for a record that stopped before that.
PARSED = frozenset({"sender", "subject", "message_id", "body", "body_segments", "classification"})
NOTE_KEY = "note"
TEXT_ONLY_NOTE = ("This order is in the email text only. Phase 1 reads attachments only; "
                  "please check the email text.")  # email_intake.runner; a test keeps it in step
ATTACHMENT_KEYS = frozenset({"attachment_id", "filename", "media_type", "byte_length", "sha256",
                             "disposition", "supported", "retained_file"})
HEX64 = re.compile(r"[0-9a-f]{64}")
MESSAGE_ID = re.compile(r"<[^\s<>@]+@[^\s<>@]+>")
DEVICE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)
BAD_COMPONENT_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class ConvertError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ConvertError(message)


def hex64(value):
    return type(value) is str and HEX64.fullmatch(value) is not None


def portable_component(name):
    """One path component valid on Windows and POSIX: no stream colon, device name or trailing dot/space."""
    return (bool(name) and BAD_COMPONENT_CHARS.search(name) is None and not name.endswith((" ", "."))
            and DEVICE.fullmatch(name) is None)


def stored_path_is(value, expected):
    """A stored runner path equals the one the runner derives (either separator), with only valid components."""
    if type(value) is not str or not value:
        return False
    parts = re.split(r"[\\/]", value)
    return (len(set(re.findall(r"[\\/]", value))) <= 1 and all(portable_component(part) for part in parts)
            and "/".join(parts) == expected)


def cli_path_ok(path):
    path = Path(path)
    if path.drive and not path.root:
        return False
    return all(portable_component(part) for part in path.parts[1 if path.anchor else 0:])


def is_alias(path):
    """A symlink or Windows reparse point (junction) at the path or any ancestor, as the runner's safe_path."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (os.path.lexists(item) and getattr(os.lstat(item), "st_file_attributes", 0) & 1024):
            return True
    return False


def body_segments(body):
    """The runner's quoted/newest split of a body (email_intake.parser), for an exact match."""
    segments = []
    for line in body.splitlines(keepends=True):
        kind = "quoted" if line.lstrip().startswith(">") else "newest"
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["text"] += line
        else:
            segments.append({"kind": kind, "text": line})
    return segments


def media_type_ok(value):
    """email.message.Message.get_content_type(): the lower-cased text before ';' with exactly one '/'.

    The parser refuses message/* parts, so they never reach a manifest."""
    return (type(value) is str and value == value.strip().lower() and ";" not in value
            and value.count("/") == 1 and not value.startswith("message/"))


def disposition_ok(value):
    """parser: part.get_content_disposition() or "attachment": any lower-cased token before ';', never empty."""
    return type(value) is str and value != "" and value == value.strip().lower() and ";" not in value


def extension_of(name):
    """The parser's extension of an (untrusted) attachment file name."""
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_attachment(item, index, iid, where):
    need(type(item) is dict and set(item) == ATTACHMENT_KEYS, f"{where}: invalid attachment manifest entry")
    need(item["attachment_id"] == f"a{index + 1:03}", f"{where}: attachment ids are not sequential")
    need(type(item["filename"]) is str and item["filename"] != "", f"{where}: invalid attachment name")
    need(media_type_ok(item["media_type"]), f"{where}: invalid attachment media type")
    need(type(item["byte_length"]) is int and item["byte_length"] >= 0, f"{where}: invalid attachment size")
    need(hex64(item["sha256"]), f"{where}: invalid attachment hash")
    need(disposition_ok(item["disposition"]), f"{where}: invalid attachment disposition")
    need(type(item["supported"]) is bool, f"{where}: invalid attachment supported flag")
    if item["supported"]:
        # parser: supported needs a known media type, its magic bytes and a safe file extension.
        need(item["media_type"] in SUPPORTED and extension_of(item["filename"]) in SAFE_EXTENSIONS
             and item["byte_length"] >= len(SUPPORTED[item["media_type"]][1]),
             f"{where}: attachment marked supported that the parser would not support")
    need(stored_path_is(item["retained_file"], f"sources/{iid}/{item['attachment_id']}.bin"),
         f"{where}: invalid retained_file path")


def check_classification(value, where):
    need(type(value) is dict and set(value) == {"category", "lane", "reason_code"}
         and all(type(v) is str for v in value.values()), f"{where}: invalid classification")
    pair = (value["category"], value["lane"], value["reason_code"])
    ok = (pair[0] in CATEGORY_LANE and pair[1:] == (CATEGORY_LANE[pair[0]], CATEGORY_REASON[pair[0]])) or (
        pair[:2] == ("unsure", "needs_a_look") and pair[2] in LOCAL_REASONS)
    need(ok, f"{where}: inconsistent classification {pair}")
    return pair


def decided(category):
    return (category, *PAIRS[category])


def held(reason):
    return ("unsure", "needs_a_look", reason)


def request_too_large(record):
    """LiveProvider's admission check: the serialized request over INPUT_BOUND returns LIMIT before any call."""
    parsed = Parsed(record["sender"], record["subject"], record["message_id"], record["body"],
                    record["body_segments"], record["attachment_manifest"], {})
    return len(json.dumps(request_for(parsed, record["intake_id"]), ensure_ascii=True).encode()) > INPUT_BOUND


def check_outcome(record, message_id_conflict, sender_policy=False):
    """Replay the runner's routing of a parsed record (email_intake/runner.py run()) and require equality.

    Producer invariants, in the runner's order:
    1. classification: UNKNOWN_SENDER for a sender outside the known-senders list (only in a folder the
       runner marked with sender-policy.json; the list itself is not in the folder, so which senders are
       unknown is not re-derived); DUPLICATE for a duplicate; CONFLICT for a message-id conflict;
       unsure/unclear for an empty body or any unsupported attachment (no provider call); otherwise a
       provider result.
    2. final outcome: TEXT_ONLY_ORDER (with its note) for an order without attachments; else the classification.
    3. reader files, only for an order or an attachment-only email (empty body, all supported, no duplicate,
       conflict or unknown sender): every attachment in manifest order, then the derived body PDF for a
       non-empty body, or PDF_LIMIT (no derived file) when that body cannot be rendered.
    """
    where, iid = record["source_name"], record["intake_id"]
    body, attachments = record["body"], record["attachment_manifest"]
    empty_body = not body.strip()
    unsupported = any(not a["supported"] for a in attachments)
    duplicate = record["duplicate_of"] is not None
    classified = check_classification(record["classification"], where)
    unknown_sender = classified == held(UNKNOWN_SENDER)
    if unknown_sender:
        need(sender_policy, f"{where}: {UNKNOWN_SENDER} in a folder without {SENDER_POLICY} (no known-senders run)")
    elif duplicate:
        need(classified == held("DUPLICATE"), f"{where}: duplicate whose classification is not DUPLICATE")
    elif message_id_conflict:
        need(classified == held("CONFLICT"), f"{where}: message-id conflict whose classification is not CONFLICT")
    elif empty_body or unsupported:
        need(classified == decided("unsure"),
             f"{where}: classification {classified} for an email the runner never sends to a provider")
    else:
        provider = record["provider"]
        need(classified[2] not in LOCAL_REASONS or classified[2] in PROVIDER_PENDING[provider],
             f"{where}: classification {classified} that the {provider} provider cannot return")
        if provider == "live":
            too_large = request_too_large(record)
            need(classified[2] in LIVE_BEFORE_SIZE if too_large else classified[2] != "LIMIT",
                 f"{where}: classification {classified} disagrees with the live request size bound")
    final, note, reader = classified, False, []
    if classified[1] == "order" and not attachments:
        final, note = held("TEXT_ONLY_ORDER"), True
    attachment_only = (empty_body and not unsupported and not duplicate and not message_id_conflict
                       and not unknown_sender)
    if final[1] == "order" or attachment_only:
        for a in attachments:
            reader.append({"file": f"sources/{iid}/{a['attachment_id']}{EXTENSIONS[a['media_type']]}",
                           "attachment_id": a["attachment_id"], "sha256": a["sha256"], "derived": False,
                           "human_selection_required": True})
        if body.strip():
            try:
                data = render(body)
            except (ValueError, UnicodeError):
                final = held("PDF_LIMIT")
            else:
                reader.append({"file": f"sources/{iid}/derived-body.pdf", "sha256": sha256(data).hexdigest(),
                               "derived": True, "source_text_sha256": sha256(body.encode()).hexdigest(),
                               "human_selection_required": True})
    outcome = (record["category"], record["lane"], record["reason_code"])
    need(outcome == final, f"{where}: outcome {outcome} is not the runner's outcome {final} for this record")
    if note:
        need(record.get(NOTE_KEY) == TEXT_ONLY_NOTE, f"{where}: text-only order without its note")
    else:
        need(NOTE_KEY not in record, f"{where}: unexpected note")
    actual = record["reader_files"]
    need(len(actual) == len(reader), f"{where}: reader_files has {len(actual)} entries; the runner prepares {len(reader)}")
    for got, want in zip(actual, reader):
        need(type(got) is dict and set(got) == set(want), f"{where}: invalid reader_files entry")
        for key, value in want.items():
            same = stored_path_is(got[key], value) if key == "file" else (type(got[key]) is type(value) and got[key] == value)
            need(same, f"{where}: reader_files entry field {key} is not what the runner prepares")


def check_shape(record, path):
    where = path.name
    keys = set(record)
    need(BASE <= keys, f"{where}: missing fields {sorted(BASE - keys)}")
    unknown = keys - BASE - PARSED - {NOTE_KEY}
    need(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    parsed = bool(keys & PARSED)
    need(not parsed or PARSED <= keys, f"{where}: partial parsed fields, missing {sorted(PARSED - keys)}")
    for name in ("version", "parser_version", "record_id", "intake_id", "source_name",
                 "source_hash_kind", "provider", "category", "lane", "reason_code"):
        need(type(record[name]) is str, f"{where}: {name} must be a string")
    need(record["version"] in ACCEPTED_VERSIONS, f"{where}: unsupported runner version")
    need(record["parser_version"] in PARSER_VERSIONS, f"{where}: unsupported parser version")
    need(record["source_hash_kind"] in HASH_KINDS, f"{where}: unknown source_hash_kind")
    need(record["provider"] in PROVIDERS, f"{where}: unknown provider")
    need(hex64(record["intake_id"]), f"{where}: invalid intake_id")
    name = record["source_name"]
    need(name.endswith(".eml") and portable_component(name) and not re.search(r"[\\/]", name),
         f"{where}: source_name must be a bare .eml file name")
    need(record["record_id"] == path.stem, f"{where}: record_id does not match its file name")
    need(record["record_id"] == sha256((record["intake_id"] + name).encode()).hexdigest(),
         f"{where}: record_id is not derived from intake_id and source_name")
    need(type(record["source_size"]) is int and record["source_size"] >= 0, f"{where}: invalid source_size")
    need(record["human_product_approval_required"] is True, f"{where}: human_product_approval_required must be true")
    for field in ("reader_files", "needs_a_look", "related_intakes", "attachment_manifest"):
        need(type(record[field]) is list, f"{where}: {field} must be a list")
    need(all(type(item) is str for item in record["needs_a_look"]), f"{where}: needs_a_look must hold strings")
    need(record["duplicate_of"] is None or hex64(record["duplicate_of"]), f"{where}: invalid duplicate_of")
    need(all(hex64(item) and item != record["intake_id"] for item in record["related_intakes"])
         and record["related_intakes"] == sorted(set(record["related_intakes"])), f"{where}: invalid related_intakes")
    iid = record["intake_id"]
    if record["source_hash_kind"] == "sha256":
        need(record["source_size"] <= MAX_EMAIL, f"{where}: sha256 record larger than the runner limit")
        need(stored_path_is(record["original"], f"sources/{iid}/original.eml"), f"{where}: invalid original path")
    else:
        need(record["original"] is None and record["source_size"] > MAX_EMAIL and not parsed
             and record["reason_code"] == "LIMIT", f"{where}: oversized source without the LIMIT shape")
    if not parsed:
        need(record["reason_code"] in PRE_PARSE_REASONS and (record["category"], record["lane"]) == ("unsure", "needs_a_look")
             and not (record["reader_files"] or record["attachment_manifest"] or record["related_intakes"]
                      or record["duplicate_of"] or NOTE_KEY in record),
             f"{where}: record without parsed fields is not a pre-parse refusal")
        return
    for field in ("sender", "subject"):
        need(type(record[field]) is str and record[field] != "", f"{where}: {field} must be a non-empty string")
    body = record["body"]
    need(type(body) is str, f"{where}: body must be a string")
    # parser: the body is stripped and refused (LIMIT, no parsed fields) above MAX_BODY UTF-8 bytes.
    need(body == body.strip(), f"{where}: body is not the parser's stripped text")
    need(len(body.encode("utf-8")) <= MAX_BODY, f"{where}: body over the parser limit of {MAX_BODY} bytes")
    need(record["message_id"] is None or (type(record["message_id"]) is str and MESSAGE_ID.fullmatch(record["message_id"])),
         f"{where}: message_id must be an angle-bracket id or null")
    need(record["body_segments"] == body_segments(body), f"{where}: body_segments do not match the body")
    need(len(record["attachment_manifest"]) <= MAX_ATTACHMENTS,
         f"{where}: more attachments than the parser limit of {MAX_ATTACHMENTS}")
    for index, item in enumerate(record["attachment_manifest"]):
        check_attachment(item, index, iid, where)
    # Decoded attachment bytes never exceed the source bytes they were decoded from.
    need(sum(a["byte_length"] for a in record["attachment_manifest"]) <= record["source_size"],
         f"{where}: attachments larger than the source email")
    check_classification(record["classification"], where)
    stored = [record["original"]] + [a["retained_file"] for a in record["attachment_manifest"]] + [
        entry.get("file") for entry in record["reader_files"] if type(entry) is dict]
    separators = {char for value in stored if type(value) is str for char in value if char in "\\/"}
    need(len(separators) <= 1, f"{where}: stored paths mix both path separators (no runner writes that)")


def load_record(path):
    where = path.name
    need(re.fullmatch(r"[0-9a-f]{64}\.json", where) is not None, f"unexpected file in records: {where}")
    need(path.is_file() and not is_alias(path), f"{where}: not a regular file")
    need(path.stat().st_size <= MAX_RECORD_BYTES, f"{where}: record too large")
    return record_from_text(path.read_text(encoding="utf-8"), path)


def record_from_text(text, path):
    """Strict JSON plus every single-record check, for the text of the record file at `path`."""
    where = path.name
    try:
        record = json.loads(text, object_pairs_hook=score.closed_object, parse_constant=score.invalid_constant)
    except RecursionError as exc:
        raise ConvertError(f"{where}: JSON nested too deeply") from exc
    except (ValueError, UnicodeError) as exc:
        raise ConvertError(f"{where}: not valid strict JSON ({exc})") from exc
    need(type(record) is dict, f"{where}: record must be an object")
    try:
        check_shape(record, path)
    except (TypeError, KeyError, AttributeError, IndexError, UnicodeError) as exc:  # unanticipated shapes fail closed
        raise ConvertError(f"{where}: malformed record ({exc.__class__.__name__})") from exc
    return record


def triple_kind(record):
    """'classified' for a contract pair, 'pending' for a local reason; anything else is an error."""
    category, lane, reason = record["category"], record["lane"], record["reason_code"]
    where = record["source_name"]
    need(lane in LANES, f"{where}: unknown lane {lane!r}")
    if category in CATEGORY_LANE:
        if (lane, reason) == (CATEGORY_LANE[category], CATEGORY_REASON[category]):
            return "classified"
        if (category, lane) == ("unsure", "needs_a_look") and reason in LOCAL_REASONS:
            return "pending"
    raise ConvertError(f"{where}: inconsistent category/lane/reason ({category!r}, {lane!r}, {reason!r})")


def check_consistency(record):
    lane, listed, where = record["lane"], record["needs_a_look"], record["source_name"]
    attached = bool(record["attachment_manifest"])
    if lane == "needs_a_look":
        need(listed == [record["reason_code"]], f"{where}: needs_a_look list disagrees with the lane")
    elif lane == "not_an_order":
        need(listed == ([QUIET] if attached else []), f"{where}: quiet-net list disagrees with the lane")
    else:
        need(listed == [], f"{where}: order record has a needs_a_look entry")
    # The runner sets duplicate_of for every later copy of an email: DUPLICATE, or UNKNOWN_SENDER when the
    # sender hold comes first.
    if record["duplicate_of"] is None:
        need(record["reason_code"] != "DUPLICATE", f"{where}: duplicate_of and the DUPLICATE reason disagree")
    else:
        need(record["reason_code"] in ("DUPLICATE", UNKNOWN_SENDER), f"{where}: duplicate_of and the DUPLICATE reason disagree")


def content_of(record):
    """What the parser derives from the source bytes; equal bytes (equal intake_id) parse equally."""
    if "body" not in record:
        return None
    manifest = [dict(a, retained_file=a["retained_file"].replace("\\", "/")) for a in record["attachment_manifest"]]
    return ([record[k] for k in ("sender", "subject", "message_id", "body")], manifest, record["source_size"])


def related(a, b):
    """The runner's relation: the same non-null message id, or a shared attachment digest."""
    mid = a.get("message_id")
    return (mid is not None and mid == b.get("message_id")) or bool(
        {x["sha256"] for x in a["attachment_manifest"]} & {x["sha256"] for x in b["attachment_manifest"]})


def check_run(records):
    """Cross-record producer invariants; returns {record_id: message-id conflict} for check_outcome.

    The runner processes records one at a time against every earlier record of the folder:
    - the first record of an intake_id is never a duplicate; every later one points at an EARLIER record of
      the same intake_id (in one run that is the first record; a later run into the same folder can point
      at an earlier duplicate, because it looks records up in file-name order), so following duplicate_of
      from any copy reaches the first record without a cycle;
    - related_intakes lists every earlier related intake and nothing else, so of two related first records
      exactly one lists the other, and the "lists" relation among first records has no cycle;
    - a later copy sees at least what the copy it points at saw;
    - the sender hold (UNKNOWN_SENDER) depends only on the email bytes: all copies agree;
    - a message-id conflict is a non-null message id shared with a listed intake.
    """
    by_intake = defaultdict(list)
    for record in records:
        by_intake[record["intake_id"]].append(record)
    firsts = {}
    for iid, group in by_intake.items():
        contents = [content_of(r) for r in group]
        need(all(c == contents[0] for c in contents), f"{group[0]['source_name']}: records of the same email bytes disagree")
        if contents[0] is None:
            continue  # stopped before parsing: never a duplicate, never related
        need(len({r["classification"]["reason_code"] == UNKNOWN_SENDER for r in group}) == 1,
             f"{group[0]['source_name']}: copies of the same email disagree about the sender hold")
        originals = [r for r in group if r["duplicate_of"] is None]
        need(len(originals) == 1, f"{group[0]['source_name']}: duplicate_of is not a record of this run "
                                  f"(the same email needs exactly one original, found {len(originals)})")
        firsts[iid] = original = originals[0]
        by_id = {r["record_id"]: r for r in group}
        for record in group:
            if record is original:
                continue
            target = by_id.get(record["duplicate_of"])
            need(target is not None and target is not record,
                 f"{record['source_name']}: duplicate_of is not a record of this run with the same email")
            need(set(target["related_intakes"]) <= set(record["related_intakes"]),
                 f"{record['source_name']}: duplicate lists fewer related_intakes than the copy it points at")
            seen, step = {record["record_id"]}, target
            while step is not original:
                need(step["record_id"] not in seen, f"{record['source_name']}: duplicate_of records point at each other")
                seen.add(step["record_id"])
                step = by_id.get(step["duplicate_of"])
                need(step is not None, f"{record['source_name']}: duplicate_of is not a record of this run with the same email")
    for record in records:
        for other in record["related_intakes"]:
            need(other in by_intake and related(record, by_intake[other][0]),
                 f"{record['source_name']}: related_intakes name an email that is not related")
    listed = {iid: set(first["related_intakes"]) for iid, first in firsts.items()}
    ordered = sorted(firsts)
    for index, a in enumerate(ordered):
        for b in ordered[index + 1:]:
            if related(firsts[a], firsts[b]):
                need((b in listed[a]) != (a in listed[b]),
                     f"{firsts[a]['source_name']}: related_intakes of two related emails are not one-directional")
    remaining = dict(listed)  # a first record lists only earlier first records: the relation must be acyclic
    while remaining:
        ready = [iid for iid, before in remaining.items() if not (before & set(remaining))]
        need(ready, "related_intakes form a cycle that no processing order produces")
        for iid in ready:
            del remaining[iid]
    conflict = {}
    for record in records:
        mid = record.get("message_id")
        conflict[record["record_id"]] = mid is not None and any(
            by_intake[other][0].get("message_id") == mid for other in record["related_intakes"])
    return conflict


def convert(out, expected):
    out = Path(out)
    need(out.is_dir() and not is_alias(out), "--out must be an existing runner output folder (not a symlink or junction)")
    need(not (out / LOCK_NAME).exists(), "run in progress or interrupted (.intake-lock exists)")
    stray = sorted(entry.name for entry in out.iterdir() if entry.name not in ROOT_ENTRIES)
    need(not stray, f"unexpected entries in the runner folder: {stray[:10]}")
    record_dir = out / "records"
    need(record_dir.is_dir() and not is_alias(record_dir), "records folder missing")
    sender_policy = (out / SENDER_POLICY).exists() or (out / SENDER_POLICY).is_symlink()
    if sender_policy:
        load_sender_policy(out / SENDER_POLICY)
    return convert_records([load_record(path) for path in sorted(record_dir.iterdir())], expected,
                           sender_policy=sender_policy)


def load_sender_policy(path):
    """The runner's marker of a --known-senders run: exactly {"version": 1, "sha256": <64 hex>}."""
    need(path.is_file() and not is_alias(path), f"{SENDER_POLICY}: not a regular file")
    need(path.stat().st_size <= MAX_POLICY_BYTES, f"{SENDER_POLICY}: too large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=score.closed_object,
                           parse_constant=score.invalid_constant)
    except RecursionError as exc:
        raise ConvertError(f"{SENDER_POLICY}: JSON nested too deeply") from exc
    except (ValueError, UnicodeError) as exc:
        raise ConvertError(f"{SENDER_POLICY}: not valid strict JSON ({exc})") from exc
    need(type(value) is dict and set(value) == {"version", "sha256"} and type(value["version"]) is int
         and value["version"] == 1 and hex64(value["sha256"]), f"{SENDER_POLICY}: not the runner's sender policy")


def convert_records(loaded, expected, *, sender_policy=False):
    """Every cross-record and expected-file check on records that passed load_record, then the answers.

    sender_policy: the folder holds the runner's sender-policy.json (a --known-senders run)."""
    by_name = {}
    for record in loaded:
        need(record["source_name"] not in by_name, f"two records for {record['source_name']}")
        by_name[record["source_name"]] = record
    need(len({r["provider"] for r in by_name.values()}) <= 1, "records from more than one provider in one folder")
    ids = set(expected)
    names = {f"{i}.eml" for i in ids}
    unknown = sorted(set(by_name) - names)
    need(not unknown, f"records for emails not in expected.jsonl: {unknown[:10]}")
    missing = sorted(names - set(by_name))
    need(not missing, f"{len(missing)} expected emails have no record (run unfinished?): {missing[:10]}")
    for fixture_id, truth in expected.items():
        record = by_name[f"{fixture_id}.eml"]
        need(record["source_hash_kind"] == "sha256",
             f"{fixture_id}.eml: oversized-source record cannot be bound to the expected email (only a bounded-prefix hash is kept)")
        need(record["intake_id"] == truth["sha256"], f"{fixture_id}: record does not match the expected email bytes")
    records = [by_name[f"{fixture_id}.eml"] for fixture_id in expected]
    for record in records:
        triple_kind(record)
        check_consistency(record)
    conflict = check_run(records)
    for record in records:
        if "body" in record:
            check_outcome(record, conflict[record["record_id"]], sender_policy)
    rows, lanes = [], Counter()
    local, kinds = Counter(), Counter()
    quiet = 0
    for fixture_id in expected:
        record = by_name[f"{fixture_id}.eml"]
        kind = triple_kind(record)
        if kind == "pending":
            row = {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"}
            local[record["reason_code"]] += 1
        else:
            row = {"id": fixture_id, "category": record["category"], "lane": record["lane"],
                   "reason_code": record["reason_code"]}
        quiet += record["lane"] == "not_an_order" and bool(record["needs_a_look"])
        kinds[kind] += 1
        lanes[row["lane"]] += 1
        rows.append(row)
    summary = {"emails": len(rows), "provider": next(iter({r["provider"] for r in by_name.values()})),
               "answers_by_lane": {lane: lanes.get(lane, 0) for lane in LANES},
               "classified_records": kinds["classified"], "pending_records": kinds["pending"],
               "local_reason_codes_omitted": dict(sorted(local.items())),
               "quiet_attachment_review_not_in_scored_lane": quiet, "sender_policy": sender_policy}
    return rows, summary


def publish(target, text):
    """Write the complete file beside the target, then hard-link it into place.

    Never leaves a partial answers file, never replaces an existing file (the link refuses one atomically)
    and never deletes a file this call did not create: the temporary name is unique and opened with
    exclusive creation, and only a temporary file this call created is removed. Without hard-link
    support there is no atomic no-overwrite publication here, so the call refuses instead.
    """
    target = Path(target)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    created = False
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:  # FileExistsError: not ours, untouched
            created = True
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)  # fails if the target exists: never overwrites
        except FileExistsError as exc:
            raise ConvertError("answers file already exists; choose a new path") from exc
        except OSError as exc:
            raise ConvertError("cannot publish the answers file without overwrite risk here "
                               "(no hard-link support); choose a folder on a local NTFS or POSIX disk") from exc
    finally:
        if created:
            try:
                temp.unlink()
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="runner --out folder")
    parser.add_argument("--expected", type=Path, required=True, help="expected.jsonl of the generated set")
    parser.add_argument("--answers", type=Path, required=True, help="new answers.jsonl to write")
    args = parser.parse_args(argv)
    try:
        need(cli_path_ok(args.out), "--out is not a plain folder path (stream, device or drive-relative form)")
        need(cli_path_ok(args.answers) and not is_alias(args.answers.parent),
             "--answers is not a plain file path (stream, device, drive-relative form or aliased folder)")
        need(not args.answers.exists(), "answers file already exists; choose a new path")
        expected = score.read_rows(args.expected, expected=True)
        rows, summary = convert(args.out, expected)
        text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n" for row in rows)
        publish(args.answers, text)
    except RecursionError:
        print("ERROR: JSON nested too deeply", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
