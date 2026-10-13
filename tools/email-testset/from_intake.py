"""Convert an email-intake runner --out folder into answers.jsonl for score.py.

Exit 0: answers.jsonl written; 2: anything missing, malformed, unknown, unsafe or
not provably this run's record for the expected email (nothing is written). Offline,
no model calls, deterministic: same inputs give the same bytes. Rows follow the
order of expected.jsonl.

The answer is the runner's own final category and lane, unchanged. The only
adaptation is vocabulary: the runner's local reason codes (CONFLICT, LIMIT,
PDF_LIMIT, TEXT_ONLY_ORDER, ...) are not in the scorer's contract. Such a record
always has category unsure and lane needs_a_look, so it becomes
{"category":"unsure","lane":"needs_a_look"} with reason_code omitted (the scorer
accepts the omission). No label is invented and none is changed: a record the
runner did not classify never becomes an order or a not_an_order answer, and
text-only, reply or attachment policies belong to the runner, not to this glue.

Every record is checked against the exact shape the runner writes (types, nested
entries, stored paths, identifiers) and against the expected file and this run
before any answer is produced. A record the expected data cannot identify (an
oversized source keeps only a bounded-prefix hash) is rejected, never substituted.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

import score
from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON, LANES

# Mirrors email_intake.contract.LOCAL_REASONS; a test keeps the two in step.
LOCAL_REASONS = frozenset({"REFUSED", "INCOMPLETE", "INVALID", "TRANSPORT_PENDING",
                           "PARSE_FAILED", "LIMIT", "CAP", "CONFLICT", "MISSING_KEY",
                           "LIVE_DISABLED", "LEDGER", "DUPLICATE", "PDF_LIMIT", "TEXT_ONLY_ORDER"})
ACCEPTED_VERSIONS = frozenset({"email-intake-v1"})
PARSER_VERSIONS = frozenset({"mime-v1"})
HASH_KINDS = frozenset({"sha256", "bounded_prefix_and_size"})
PROVIDERS = frozenset({"fake", "live"})
PRE_PARSE_REASONS = frozenset({"LIMIT", "PARSE_FAILED"})
QUIET = "quiet_attachment_review"
MAX_RECORD_BYTES = 1024 * 1024
MAX_EMAIL = 2 * 1024 * 1024  # email_intake.parser.MAX_EMAIL
EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}  # parser.SUPPORTED
ROOT_ENTRIES = frozenset({"records", "sources", "calls.jsonl", "quiet-digest.jsonl", ".intake-guard"})
LOCK_NAME = ".intake-lock"

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
    return all(portable_component(part) for part in parts) and "/".join(parts) == expected


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


def check_attachment(item, index, iid, where):
    need(type(item) is dict and set(item) == ATTACHMENT_KEYS, f"{where}: invalid attachment manifest entry")
    need(item["attachment_id"] == f"a{index + 1:03}", f"{where}: attachment ids are not sequential")
    need(type(item["filename"]) is str and item["filename"] != "" and type(item["media_type"]) is str,
         f"{where}: invalid attachment name or type")
    need(type(item["byte_length"]) is int and item["byte_length"] >= 0, f"{where}: invalid attachment size")
    need(hex64(item["sha256"]), f"{where}: invalid attachment hash")
    need(item["disposition"] in ("attachment", "inline"), f"{where}: invalid attachment disposition")
    need(type(item["supported"]) is bool, f"{where}: invalid attachment supported flag")
    need(not item["supported"] or item["media_type"] in EXTENSIONS, f"{where}: supported attachment of unknown type")
    need(stored_path_is(item["retained_file"], f"sources/{iid}/{item['attachment_id']}.bin"),
         f"{where}: invalid retained_file path")


def check_reader_files(record, where):
    iid, body = record["intake_id"], record["body"]
    by_id = {a["attachment_id"]: a for a in record["attachment_manifest"]}
    seen, derived = set(), 0
    for entry in record["reader_files"]:
        need(type(entry) is dict and entry.get("human_selection_required") is True, f"{where}: invalid reader_files entry")
        need(hex64(entry.get("sha256")), f"{where}: invalid reader file hash")
        if entry.get("derived") is True:
            need(set(entry) == {"file", "sha256", "derived", "source_text_sha256", "human_selection_required"},
                 f"{where}: invalid derived reader file")
            need(stored_path_is(entry["file"], f"sources/{iid}/derived-body.pdf"), f"{where}: invalid reader file path")
            need(entry["source_text_sha256"] == sha256(body.encode("utf-8")).hexdigest(),
                 f"{where}: derived reader file does not match the body")
            derived += 1
            need(derived == 1, f"{where}: two derived reader files")
        else:
            need(set(entry) == {"file", "attachment_id", "sha256", "derived", "human_selection_required"}
                 and entry["derived"] is False, f"{where}: invalid reader file")
            attachment = by_id.get(entry["attachment_id"]) if type(entry["attachment_id"]) is str else None
            need(attachment is not None and attachment["supported"] and attachment["sha256"] == entry["sha256"]
                 and entry["attachment_id"] not in seen, f"{where}: reader file does not match an attachment")
            seen.add(entry["attachment_id"])
            extension = EXTENSIONS[attachment["media_type"]]
            need(stored_path_is(entry["file"], f"sources/{iid}/{entry['attachment_id']}{extension}"),
                 f"{where}: invalid reader file path")


def check_classification(value, where):
    need(type(value) is dict and set(value) == {"category", "lane", "reason_code"}
         and all(type(v) is str for v in value.values()), f"{where}: invalid classification")
    pair = (value["category"], value["lane"], value["reason_code"])
    ok = (pair[0] in CATEGORY_LANE and pair[1:] == (CATEGORY_LANE[pair[0]], CATEGORY_REASON[pair[0]])) or (
        pair[:2] == ("unsure", "needs_a_look") and pair[2] in LOCAL_REASONS)
    need(ok, f"{where}: inconsistent classification {pair}")
    return pair


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
    need(type(record["body"]) is str, f"{where}: body must be a string")
    need(record["message_id"] is None or (type(record["message_id"]) is str and MESSAGE_ID.fullmatch(record["message_id"])),
         f"{where}: message_id must be an angle-bracket id or null")
    need(record["body_segments"] == body_segments(record["body"]), f"{where}: body_segments do not match the body")
    for index, item in enumerate(record["attachment_manifest"]):
        check_attachment(item, index, iid, where)
    check_reader_files(record, where)
    classified = check_classification(record["classification"], where)
    final = (record["category"], record["lane"], record["reason_code"])
    if final != classified:
        # The only two runner overrides of a classifier result: both keep category unsure / lane needs_a_look.
        ok = classified == ("order", "order", "new_order") and final[:2] == ("unsure", "needs_a_look") and (
            (final[2] == "TEXT_ONLY_ORDER" and not record["attachment_manifest"]) or final[2] == "PDF_LIMIT")
        need(ok, f"{where}: outcome {final} differs from the classification {classified}")
    if final[1] == "order":
        # The runner turns an order without any attachment into TEXT_ONLY_ORDER and always keeps reader files for one.
        need(bool(record["attachment_manifest"]) and bool(record["reader_files"]),
             f"{where}: order record without its attachments or reader files")
    if NOTE_KEY in record:
        need(final[2] == "TEXT_ONLY_ORDER" and record[NOTE_KEY] == TEXT_ONLY_NOTE,
             f"{where}: unexpected note")
    else:
        need(final[2] != "TEXT_ONLY_ORDER", f"{where}: text-only order without its note")


def load_record(path):
    where = path.name
    need(re.fullmatch(r"[0-9a-f]{64}\.json", where) is not None, f"unexpected file in records: {where}")
    need(path.is_file() and not is_alias(path), f"{where}: not a regular file")
    need(path.stat().st_size <= MAX_RECORD_BYTES, f"{where}: record too large")
    try:
        record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=score.closed_object,
                            parse_constant=score.invalid_constant)
    except RecursionError as exc:
        raise ConvertError(f"{where}: JSON nested too deeply") from exc
    except (ValueError, UnicodeError) as exc:
        raise ConvertError(f"{where}: not valid strict JSON ({exc})") from exc
    need(type(record) is dict, f"{where}: record must be an object")
    try:
        check_shape(record, path)
    except (TypeError, KeyError, AttributeError, IndexError) as exc:  # a shape the checks did not anticipate fails closed
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
    need((record["duplicate_of"] is not None) == (record["reason_code"] == "DUPLICATE"),
         f"{where}: duplicate_of and the DUPLICATE reason disagree")


def convert(out, expected):
    out = Path(out)
    need(out.is_dir() and not is_alias(out), "--out must be an existing runner output folder (not a symlink or junction)")
    need(not (out / LOCK_NAME).exists(), "run in progress or interrupted (.intake-lock exists)")
    stray = sorted(entry.name for entry in out.iterdir() if entry.name not in ROOT_ENTRIES)
    need(not stray, f"unexpected entries in the runner folder: {stray[:10]}")
    record_dir = out / "records"
    need(record_dir.is_dir() and not is_alias(record_dir), "records folder missing")
    by_name = {}
    for path in sorted(record_dir.iterdir()):
        record = load_record(path)
        need(record["source_name"] not in by_name, f"two records for {record['source_name']}")
        by_name[record["source_name"]] = record
    need(len({r["provider"] for r in by_name.values()}) <= 1, "records from more than one provider in one folder")
    ids = set(expected)
    names = {f"{i}.eml" for i in ids}
    unknown = sorted(set(by_name) - names)
    need(not unknown, f"records for emails not in expected.jsonl: {unknown[:10]}")
    missing = sorted(names - set(by_name))
    need(not missing, f"{len(missing)} expected emails have no record (run unfinished?): {missing[:10]}")
    by_record_id = {r["record_id"]: r for r in by_name.values()}
    intake_ids = {r["intake_id"] for r in by_name.values()}
    rows, lanes = [], Counter()
    local, kinds = Counter(), Counter()
    quiet = 0
    for fixture_id, truth in expected.items():
        record = by_name[f"{fixture_id}.eml"]
        where = f"{fixture_id}.eml"
        need(record["source_hash_kind"] == "sha256",
             f"{where}: oversized-source record cannot be bound to the expected email (only a bounded-prefix hash is kept)")
        need(record["intake_id"] == truth["sha256"], f"{fixture_id}: record does not match the expected email bytes")
        kind = triple_kind(record)
        check_consistency(record)
        original = by_record_id.get(record["duplicate_of"])
        need(record["duplicate_of"] is None or (original is not None and original is not record
                                                and original["intake_id"] == record["intake_id"]),
             f"{where}: duplicate_of is not a record of this run")
        need(set(record["related_intakes"]) <= intake_ids, f"{where}: related_intakes name emails outside this run")
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
               "quiet_attachment_review_not_in_scored_lane": quiet}
    return rows, summary


def publish(target, text):
    """Write the complete file beside the target, then link it into place; never leave a partial answers file."""
    target = Path(target)
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)  # fails if the target exists: never overwrites
        except FileExistsError as exc:
            raise ConvertError("answers file already exists; choose a new path") from exc
        except OSError:
            need(not target.exists(), "answers file already exists; choose a new path")
            os.replace(temp, target)
    finally:
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
