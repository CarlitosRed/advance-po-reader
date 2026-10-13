"""Local retention, replay links, quiet digest and manual reader preparation."""
from hashlib import sha256
import json
import os
from pathlib import Path

from . import VERSION
from .body_pdf import render
from .contract import decision, pending
from .ledger import safe_path
from .locking import exclusive
from .parser import MAX_EMAIL, SUPPORTED, ParseError, parse
from .providers import FakeProvider


def write_once(path, data):
    safe_path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("CONFLICT")
        return
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save_json(path, value):
    write_once(path, (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode())


def append_json(path, value):
    safe_path(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def summary(record, *, reused=False):
    return {k: record[k] for k in ("intake_id", "lane", "category", "reason_code")} | {
        "reader_file_count": len(record["reader_files"]), "needs_a_look_count": len(record["needs_a_look"]),
        "provider": record.get("provider", "unknown"), "reused": reused} | (
        {"note": record["note"]} if "note" in record else {})


def run(drop, out, provider=None, *, break_lock=False, report=None, known_senders=None):
    drop, out = safe_path(drop), safe_path(out)
    if not drop.is_dir() or out == drop or out in drop.parents or drop in out.parents:
        raise ValueError("CONFLICT")
    out.mkdir(parents=True, exist_ok=True)
    provider = provider or FakeProvider()
    records, results = [], []
    with exclusive(out, break_lock=break_lock):
        # Outcomes are immutable. A changed policy must use a new output folder;
        # otherwise an old Sure could bypass the enabled hint on replay.
        policy_path = safe_path(out / "sender-policy.json")
        if known_senders is not None:
            policy = {"version": 1, "sha256": known_senders.fingerprint}
            if not policy_path.exists() and any((out / "records").glob("*.json")):
                raise ValueError("CONFLICT")
            save_json(policy_path, policy)
        elif policy_path.exists():
            raise ValueError("CONFLICT")
        record_dir = safe_path(out / "records")
        record_dir.mkdir(exist_ok=True)
        for path in sorted(record_dir.glob("*.json")):
            safe_path(path)
            records.append(json.loads(path.read_text(encoding="utf-8")))
        skipped = 0
        for path in sorted(drop.iterdir()):
            if path.name.lower().startswith(".env"):
                continue
            if path.suffix.lower() != ".eml":
                skipped += int(path.is_file())
                continue
            safe_path(path)
            if not path.is_file():
                continue
            size = path.stat().st_size
            with path.open("rb") as stream:
                raw = stream.read(MAX_EMAIL + 1)
            oversized = len(raw) > MAX_EMAIL or size > MAX_EMAIL
            # For overlimit inputs this is explicitly a bounded prefix digest;
            # the original stays in the drop folder and is never sent to a provider.
            iid = sha256(raw + (str(size).encode() if oversized else b"")).hexdigest()
            record_id = sha256((iid + path.name).encode()).hexdigest()
            record_path = safe_path(record_dir / (record_id + ".json"))
            if record_path.exists():
                # Immutable per-source outcome: a later --live run cannot silently
                # turn a prior fake result into a model result or repeat a paid call.
                previous = next(r for r in records if r["record_id"] == record_id)
                results.append(summary(previous, reused=True))
                continue
            folder = safe_path(out / "sources" / iid)
            folder.mkdir(parents=True, exist_ok=True)
            original = folder / "original.eml"
            if not oversized:
                write_once(original, raw)
            record = {"version": VERSION, "parser_version": "mime-v1", "record_id": record_id,
                      "intake_id": iid, "source_size": size, "source_name": path.name,
                      "original": str(original.relative_to(out)) if not oversized else None,
                      "source_hash_kind": "bounded_prefix_and_size" if oversized else "sha256",
                      "human_product_approval_required": True, "reader_files": [],
                      "needs_a_look": [], "duplicate_of": None, "related_intakes": [],
                      "attachment_manifest": [], "provider": "live" if provider.live else "fake"}
            parsed = None
            try:
                if oversized:
                    raise ParseError("LIMIT")
                parsed = parse(raw, sender_hint=known_senders is not None)
                record.update(parsed.record())
                for a in parsed.attachments:
                    # Retain every attachment, including archives/macros, as opaque
                    # .bin evidence. No extractor, archive opener or renderer runs.
                    target = folder / (a["attachment_id"] + ".bin")
                    write_once(target, parsed.payloads[a["attachment_id"]])
                    a["retained_file"] = str(target.relative_to(out))
                exact = next((r for r in records if r["intake_id"] == iid), None)
                message_id_conflict = parsed.message_id is not None and any(
                    r["intake_id"] != iid and r.get("message_id") == parsed.message_id for r in records)
                related = [r["intake_id"] for r in records if r["intake_id"] != iid and (
                    (parsed.message_id is not None and r.get("message_id") == parsed.message_id)
                    or bool({a["sha256"] for a in parsed.attachments} &
                            {a["sha256"] for a in r["attachment_manifest"]}))]
                record["related_intakes"] = sorted(set(related))
                empty_body = not parsed.body.strip()
                unsupported = any(not a["supported"] for a in parsed.attachments)
                unknown_sender = known_senders is not None and not known_senders.matches(parsed.sender_address)
                if unknown_sender:
                    result, audit = pending("UNKNOWN_SENDER"), None
                    if exact:
                        record["duplicate_of"] = exact["record_id"]
                elif exact:
                    record["duplicate_of"] = exact["record_id"]
                    result, audit = pending("DUPLICATE"), None
                elif message_id_conflict:
                    result, audit = pending("CONFLICT"), None
                elif empty_body or unsupported:
                    # No usable classifier text or unsupported evidence: require
                    # review before a reservation or provider call can occur.
                    result, audit = decision("unsure"), None
                else:
                    result, audit = provider.classify(parsed, iid)
                record["classification"] = result.copy()
                if audit is not None:
                    append_json(out / "calls.jsonl", {"intake_id": iid, **audit})
                if result["lane"] == "order" and not parsed.attachments:
                    result = pending("TEXT_ONLY_ORDER")
                    record["note"] = ("This order is in the email text only. Phase 1 reads attachments only; "
                                      "please check the email text.")
                record.update(result)
                # A blank body is normal for a document-only message. Keep its
                # supported files selectable, while its unseen contents still
                # require review. Duplicates/conflicts/unsupported mixtures do not.
                attachment_only = (empty_body and not unsupported and not exact
                                   and not message_id_conflict and not unknown_sender)
                if result["lane"] == "order" or attachment_only:
                    if parsed.attachments:
                        for a in parsed.attachments:
                            extension = SUPPORTED[a["media_type"]][0]
                            target = folder / (a["attachment_id"] + extension)
                            write_once(target, parsed.payloads[a["attachment_id"]])
                            record["reader_files"].append({"file": str(target.relative_to(out)),
                                "attachment_id": a["attachment_id"], "sha256": a["sha256"],
                                "derived": False, "human_selection_required": True})
                    # The body remains a source candidate even when the message
                    # also carries a supported document or signature image.
                    if parsed.body.strip():
                        try:
                            data = render(parsed.body)
                            target = folder / "derived-body.pdf"
                            write_once(target, data)
                            record["reader_files"].append({"file": str(target.relative_to(out)),
                                "sha256": sha256(data).hexdigest(), "derived": True,
                                "source_text_sha256": sha256(parsed.body.encode()).hexdigest(),
                                "human_selection_required": True})
                        except (ValueError, UnicodeError):
                            record.update(pending("PDF_LIMIT"))
            except ParseError as exc:
                record.update(pending(str(exc)))
            if record["lane"] == "needs_a_look":
                record["needs_a_look"] = [record["reason_code"]]
            # Every quiet email with ANY attachment enters the recoverable net,
            # including inline attachments. The digest contains no source prose.
            if record["lane"] == "not_an_order" and record["attachment_manifest"]:
                append_json(out / "quiet-digest.jsonl", {
                    "intake_id": iid, "record_id": record_id, "lane": record["lane"],
                    "reason_code": record["reason_code"], "status": "unresolved",
                    "attachment_digests": [a["sha256"] for a in record["attachment_manifest"]]})
                record["needs_a_look"] = ["quiet_attachment_review"]
            save_json(record_path, record)
            records.append(record)
            results.append(summary(record))
        if skipped and report is not None:
            report({"skipped_non_eml_files": skipped})
    return results
