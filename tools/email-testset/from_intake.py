"""Convert an email-intake runner --out folder into answers.jsonl for score.py.

Exit 0: answers.jsonl written; 2: anything missing, malformed, unknown or unsafe
(nothing is written). Offline, no model calls, deterministic: same inputs give the
same bytes. Rows follow the order of expected.jsonl.

The runner's local reason codes (CONFLICT, LIMIT, PDF_LIMIT, ...) are not in the
scorer's contract. Such a record always has category unsure and lane needs_a_look,
so it becomes {"category":"unsure","lane":"needs_a_look"} with reason_code omitted
(the scorer accepts the omission). No label is invented: a record the runner did
not classify never becomes an order or a not_an_order answer.

Product decisions (Carlos): an order is "Sure" (lane order) only when a real
attached document (disposition attachment, supported type) exists and the subject
is not a reply. A text-only order, or a reply, is shown as needs_a_look. Changes,
cancellations and quote requests are already needs_a_look in the contract.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import score
from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON, LANES

# Mirrors email_intake.contract.LOCAL_REASONS; a test keeps the two in step.
LOCAL_REASONS = frozenset({"REFUSED", "INCOMPLETE", "INVALID", "TRANSPORT_PENDING",
                           "PARSE_FAILED", "LIMIT", "CAP", "CONFLICT", "MISSING_KEY",
                           "LIVE_DISABLED", "LEDGER", "DUPLICATE", "PDF_LIMIT"})
ACCEPTED_VERSIONS = frozenset({"email-intake-v1"})
PARSER_VERSIONS = frozenset({"mime-v1"})
HASH_KINDS = frozenset({"sha256", "bounded_prefix_and_size"})
PROVIDERS = frozenset({"fake", "live"})
QUIET = "quiet_attachment_review"
MAX_RECORD_BYTES = 1024 * 1024

REQUIRED = frozenset({
    "version", "parser_version", "record_id", "intake_id", "source_size", "source_name",
    "original", "source_hash_kind", "human_product_approval_required", "reader_files",
    "needs_a_look", "duplicate_of", "related_intakes", "attachment_manifest", "provider",
    "category", "lane", "reason_code"})
OPTIONAL = frozenset({"sender", "subject", "message_id", "body", "body_segments", "classification"})
HEX64 = re.compile(r"[0-9a-f]{64}")
REPLY = re.compile(r"\s*re\s*:", re.IGNORECASE)


class ConvertError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ConvertError(message)


def clean_relative(value):
    """A stored path is None or a relative path with no parent or drive part, on either platform."""
    if value is None:
        return True
    if type(value) is not str or not value or "\x00" in value:
        return False
    parts = re.split(r"[\\/]", value)
    return not (value[0] in "\\/" or re.match(r"[A-Za-z]:", value) or ".." in parts or "" in parts)


def load_record(path):
    where = path.name
    need(HEX64.fullmatch(path.stem) and path.suffix == ".json", f"unexpected file in records: {where}")
    need(path.is_file() and not path.is_symlink(), f"{where}: not a regular file")
    need(path.stat().st_size <= MAX_RECORD_BYTES, f"{where}: record too large")
    try:
        record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=score.closed_object,
                            parse_constant=score.invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise ConvertError(f"{where}: not valid strict JSON ({exc})") from exc
    need(type(record) is dict, f"{where}: record must be an object")
    keys = set(record)
    need(REQUIRED <= keys, f"{where}: missing fields {sorted(REQUIRED - keys)}")
    need(keys <= REQUIRED | OPTIONAL, f"{where}: unknown fields {sorted(keys - REQUIRED - OPTIONAL)}")
    for name in ("version", "parser_version", "record_id", "intake_id", "source_name",
                 "source_hash_kind", "provider", "category", "lane", "reason_code"):
        need(type(record[name]) is str, f"{where}: {name} must be a string")
    need(record["version"] in ACCEPTED_VERSIONS, f"{where}: unsupported runner version")
    need(record["parser_version"] in PARSER_VERSIONS, f"{where}: unsupported parser version")
    need(record["record_id"] == path.stem, f"{where}: record_id does not match its file name")
    need(HEX64.fullmatch(record["intake_id"]) is not None, f"{where}: invalid intake_id")
    need(record["source_hash_kind"] in HASH_KINDS, f"{where}: unknown source_hash_kind")
    need(record["provider"] in PROVIDERS, f"{where}: unknown provider")
    need(type(record["source_size"]) is int and record["source_size"] >= 0, f"{where}: invalid source_size")
    need(clean_relative(record["original"]), f"{where}: invalid original path")
    name = record["source_name"]
    need(name.endswith(".eml") and not re.search(r"[\\/\x00]", name) and not re.match(r"[A-Za-z]:", name),
         f"{where}: source_name must be a bare .eml file name")
    for name_ in ("reader_files", "needs_a_look", "related_intakes", "attachment_manifest"):
        need(type(record[name_]) is list, f"{where}: {name_} must be a list")
    need(all(type(item) is str for item in record["needs_a_look"]), f"{where}: needs_a_look must hold strings")
    need(record["duplicate_of"] is None or HEX64.fullmatch(str(record["duplicate_of"])) is not None,
         f"{where}: invalid duplicate_of")
    need(all(type(f) is dict and clean_relative(f.get("file")) and f.get("file") is not None
             and type(f.get("derived")) is bool for f in record["reader_files"]),
         f"{where}: invalid reader_files")
    for attachment in record["attachment_manifest"]:
        need(type(attachment) is dict and type(attachment.get("supported")) is bool
             and type(attachment.get("disposition")) is str, f"{where}: invalid attachment manifest")
    if "subject" in record:
        need(type(record["subject"]) is str, f"{where}: subject must be a string")
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
    if record["duplicate_of"] is not None:
        need(record["reason_code"] == "DUPLICATE", f"{where}: duplicate record without DUPLICATE")


def sure_blocker(record):
    """Why an order must be shown as needs_a_look instead, or None."""
    has_document = any(a["supported"] and a["disposition"] == "attachment" for a in record["attachment_manifest"])
    if not has_document:
        return "text_only"
    if REPLY.match(record.get("subject", "")):
        return "reply"
    return None


def convert(out, expected):
    out = Path(out)
    need(out.is_dir() and not out.is_symlink(), "--out must be an existing runner output folder")
    need(not (out / ".intake-lock").exists(), "run in progress or interrupted (.intake-lock exists)")
    record_dir = out / "records"
    need(record_dir.is_dir() and not record_dir.is_symlink(), "records folder missing")
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
    rows, lanes = [], Counter()
    local, downgraded, kinds = Counter(), Counter(), Counter()
    quiet = 0
    for fixture_id, truth in expected.items():
        record = by_name[f"{fixture_id}.eml"]
        if record["source_hash_kind"] == "sha256":
            need(record["intake_id"] == truth["sha256"], f"{fixture_id}: record does not match the expected email bytes")
        else:
            need(record["reason_code"] == "LIMIT", f"{fixture_id}: oversized source without LIMIT")
        kind = triple_kind(record)
        check_consistency(record)
        if kind == "pending":
            row = {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"}
            local[record["reason_code"]] += 1
        else:
            row = {"id": fixture_id, "category": record["category"], "lane": record["lane"],
                   "reason_code": record["reason_code"]}
            if record["lane"] == "order":
                blocker = sure_blocker(record)
                if blocker:
                    downgraded[blocker] += 1
                    row = {"id": fixture_id, "category": "unsure", "lane": "needs_a_look"}
        quiet += record["lane"] == "not_an_order" and bool(record["needs_a_look"])
        kinds[kind] += 1
        lanes[row["lane"]] += 1
        rows.append(row)
    summary = {"emails": len(rows), "provider": next(iter({r["provider"] for r in by_name.values()})),
               "answers_by_lane": {lane: lanes.get(lane, 0) for lane in LANES},
               "classified_records": kinds["classified"], "pending_records": kinds["pending"],
               "local_reason_codes_omitted": dict(sorted(local.items())),
               "orders_downgraded_to_needs_a_look": dict(sorted(downgraded.items())),
               "quiet_attachment_review_not_in_scored_lane": quiet}
    return rows, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="runner --out folder")
    parser.add_argument("--expected", type=Path, required=True, help="expected.jsonl of the generated set")
    parser.add_argument("--answers", type=Path, required=True, help="new answers.jsonl to write")
    args = parser.parse_args(argv)
    try:
        need(not args.answers.exists(), "answers file already exists; choose a new path")
        expected = score.read_rows(args.expected, expected=True)
        rows, summary = convert(args.out, expected)
        text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n" for row in rows)
        with args.answers.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
