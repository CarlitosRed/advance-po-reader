"""Private annotation queues; predictions never become reference data implicitly.

Queue records retain immutable model/native observations. A separate, named
human review must verify every source page before benchmark labels are exported.
There is deliberately no training or model-update operation in this module.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import uuid


ROLES = {"vendor_product_code", "manufacturer_part_number", "customer_item_number", "unknown"}
PAGE_HASH_METHOD = "pdfium-rgb-scale-0.75-v1"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest_json(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value, *, exclusive=False):
    """Exclusive queue creation prevents reruns from replacing human corrections."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
        return
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha(value, field="sha256"):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError(f"{field} requires an exact lowercase SHA-256")
    return value


def _page(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("Source page numbers must be positive integers")
    return value


def _validate_record(record):
    if record.get("schema_version") != 1:
        raise ValueError("Unsupported annotation queue schema")
    document_sha = _sha(record["document"]["sha256"])
    expected_id = _digest_json(dict(document_sha256=document_sha, run_id=record.get("run_id")))
    if record.get("record_id") != expected_id:
        raise ValueError("Queue record identity does not match its document/run")
    prediction = record.get("raw_prediction")
    if not isinstance(prediction, dict) or _digest_json(prediction) != record.get("prediction_sha256"):
        raise ValueError("Saved raw prediction was changed; retain original model observations")
    extraction = prediction.get("extraction") or {}
    seen = set()
    for page in record.get("pages", []):
        number = _page(page.get("page"))
        if number in seen:
            raise ValueError("Queue source pages must be unique")
        seen.add(number)
        for key, original in (("raw_observations", extraction.get("pages") or []),
                              ("raw_extracted_lines", prediction.get("lines") or []),
                              ("failures", extraction.get("failures") or [])):
            if page.get(key) != [item for item in original if item.get("page") == number]:
                raise ValueError("Saved page observations were changed; retain original model evidence")
    if not seen:
        raise ValueError("Queue has no source page evidence")


def source_page_hashes(raw):
    """Same full-page RGB fingerprint contract as benchmark_vision inventory."""
    import pypdfium2 as pdfium
    from .rendering import PDFIUM_LOCK
    result = []
    with PDFIUM_LOCK, pdfium.PdfDocument(raw) as document:
        for page in document:
            try:
                bitmap = page.render(scale=0.75)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    try:
                        data = f"RGB:{image.width}:{image.height}:".encode() + image.tobytes()
                        result.append(sha256(data))
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    if not result:
        raise ValueError("The source PDF has no pages")
    return result


def _sources(payload):
    if not isinstance(payload, dict):
        raise ValueError("Saved inference result must be a JSON object")
    if isinstance(payload.get("results"), list):
        inventory = {item["sha256"]: item for item in payload.get("inventory", [])}
        for result in payload["results"]:
            yield result, result.get("prediction") or {}, inventory.get(result.get("sha256"), {})
    elif "sha256" in payload and ("lines" in payload or "extraction" in payload):
        yield payload, payload, payload
    else:
        raise ValueError("Expected a saved benchmark report or reader-session document")


def build_queue(payload, *, run_id=None, source_loader=None):
    """Return pending document records, optionally binding original PDF bytes.

    source_loader receives the result/document metadata and returns bytes or None.
    Benchmark inventory page fingerprints can bind pages without reopening PDFs.
    A session without source fingerprints stays pending until collected with its
    source PDF. Failed model pages remain in the queue and must also be reviewed.
    """
    run_id = run_id or payload.get("run_id") or payload.get("session_id") or _digest_json(payload)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a nonempty string")
    records = []
    for result, prediction, inventory in _sources(payload):
        document_sha = _sha(result.get("sha256") or prediction.get("sha256"))
        if prediction.get("sha256") and prediction["sha256"] != document_sha:
            raise ValueError("Prediction and benchmark source SHA-256 disagree")
        raw = source_loader(result) if source_loader else None
        hashes = inventory.get("page_fingerprints") or []
        for fingerprint in hashes:
            _sha(fingerprint, "source_page_sha256")
        if raw is not None:
            if sha256(raw) != document_sha:
                raise ValueError("Source PDF SHA-256 does not match the saved result")
            live_hashes = source_page_hashes(raw)
            if hashes and live_hashes != hashes:
                raise ValueError("Source PDF page fingerprints disagree with the saved inventory")
            hashes = live_hashes
        extraction = prediction.get("extraction") or {}
        observations = extraction.get("pages") or []
        failures = extraction.get("failures") or []
        page_numbers = set(range(1, len(hashes) + 1))
        for group in (inventory.get("pages") or [], prediction.get("pages") or [], observations, failures, prediction.get("lines") or []):
            for item in group:
                if item.get("page") is not None:
                    page_numbers.add(_page(item["page"]))
        if not page_numbers:
            raise ValueError("Saved result has no source page inventory; collect with the source PDF")
        if hashes and max(page_numbers) > len(hashes):
            raise ValueError("Saved extraction refers to a page outside the source PDF")
        provenance = {key: deepcopy(payload.get(key)) for key in
                      ("mode", "provider", "model", "model_digest", "prompt_version", "schema_version", "execution_settings", "created_utc")
                      if key in payload}
        provenance["architecture_version"] = prediction.get("architecture_version")
        provenance["extraction"] = {key: deepcopy(value) for key, value in extraction.items() if key not in ("pages", "failures")}
        page_records = []
        for page in sorted(page_numbers):
            observed = [deepcopy(item) for item in observations if item.get("page") == page]
            page_records.append(dict(page=page, source_page_sha256=hashes[page - 1] if len(hashes) >= page else None,
                                     source_page_hash_method=PAGE_HASH_METHOD if len(hashes) >= page else None,
                                     model_image_sha256=[item["image_sha256"] for item in observed if item.get("image_sha256")],
                                     raw_observations=observed,
                                     raw_extracted_lines=[deepcopy(line) for line in prediction.get("lines", []) if line.get("page") == page],
                                     failures=[deepcopy(item) for item in failures if item.get("page") == page]))
        record_id = _digest_json(dict(document_sha256=document_sha, run_id=run_id))
        records.append(dict(schema_version=1, record_id=record_id, run_id=run_id,
                            document=dict(sha256=document_sha, filename=result.get("filename") or prediction.get("filename"),
                                          archive_entry=result.get("archive_entry") or inventory.get("archive_entry"),
                                          leakage_group=result.get("leakage_group") or inventory.get("leakage_group")),
                            provenance=provenance, pages=page_records,
                            raw_prediction=deepcopy(prediction), prediction_sha256=_digest_json(prediction),
                            run_error=result.get("error"), review_status="pending",
                            corrected_expected=dict(po_number=None, lines=None), human_review=None))
    return records


def collect_queue(payload, output_dir, *, run_id=None, source_loader=None):
    """Idempotently save observations; preserve all existing human-review fields."""
    paths = []
    for record in build_queue(payload, run_id=run_id, source_loader=source_loader):
        path = Path(output_dir) / f"{record['record_id']}.json"
        if path.exists():
            existing = read_json(path)
            _validate_record(existing)
            if (existing.get("document") != record["document"] or existing.get("run_id") != record["run_id"] or
                    existing.get("prediction_sha256") != record["prediction_sha256"]):
                raise ValueError("This document/run already contains different observations; use a new run_id")
            if existing.get("review_status") == "pending":
                # Binding a missing source hash is allowed; raw observations and
                # any draft correction fields are never replaced on collection.
                existing_pages = {item["page"]: item for item in existing["pages"]}
                changed = False
                for item in record["pages"]:
                    previous = existing_pages.get(item["page"])
                    if previous is None:
                        existing["pages"].append(item)
                        changed = True
                    elif previous.get("source_page_sha256") and item.get("source_page_sha256") and previous["source_page_sha256"] != item["source_page_sha256"]:
                        raise ValueError("Existing source page SHA-256 does not match")
                    elif not previous.get("source_page_sha256") and item.get("source_page_sha256"):
                        previous["source_page_sha256"] = item["source_page_sha256"]
                        previous["source_page_hash_method"] = item["source_page_hash_method"]
                        changed = True
                if changed:
                    existing["pages"].sort(key=lambda item: item["page"])
                    write_json(path, existing)
        else:
            write_json(path, record, exclusive=True)
        paths.append(path)
    return paths


def approval_template(record):
    """Do not prefill expected values or claim any page has been reviewed."""
    return dict(schema_version=1, record_id=record["record_id"], document_sha256=record["document"]["sha256"],
                pages_reviewed=[], expected=dict(po_number=None, lines=None), notes=None)


def _optional_text(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be an exact source string or null")


def validate_expected(expected, pages):
    if not isinstance(expected, dict) or "po_number" not in expected or "lines" not in expected:
        raise ValueError("Approval requires explicit expected.po_number and expected.lines")
    _optional_text(expected["po_number"], "PO number")
    if not isinstance(expected["lines"], list):
        raise ValueError("Expected lines must be a complete human-reviewed list; null is unreviewed")
    for line in expected["lines"]:
        if not isinstance(line, dict) or _page(line.get("page")) not in pages:
            raise ValueError("Each expected line must refer to a reviewed source page")
        identifiers = line.get("identifiers")
        if not isinstance(identifiers, list):
            raise ValueError("Each expected line requires an identifiers list")
        for identifier in identifiers:
            if not isinstance(identifier, dict) or not isinstance(identifier.get("raw_value"), str) or not identifier["raw_value"].strip():
                raise ValueError("Reviewed identifiers require a nonempty raw_value string")
            if identifier.get("role") not in ROLES:
                raise ValueError("Reviewed identifier role is invalid")
            _optional_text(identifier.get("printed_label"), "Printed identifier label")
        if "quantity" not in line or "uom" not in line:
            raise ValueError("Each expected line requires explicit quantity and uom strings or null")
        _optional_text(line["quantity"], "Quantity")
        _optional_text(line["uom"], "Unit")
        if line["quantity"] is not None:
            try:
                number = Decimal(line["quantity"].strip())
                if not number.is_finite() or number <= 0:
                    raise InvalidOperation
            except InvalidOperation as error:
                raise ValueError("Quantity must be an exact positive finite numeric string, or null when unresolved") from error
        _optional_text(line.get("expected_catalog_product_id"), "Catalog product ID")
    return expected


def _validate_review(record, approval, reviewer):
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A human reviewer name is required")
    if approval.get("schema_version") != 1 or approval.get("record_id") != record.get("record_id"):
        raise ValueError("Approval must identify this exact queue record")
    if approval.get("document_sha256") != record["document"]["sha256"]:
        raise ValueError("Approval document SHA-256 does not match")
    pages = {item["page"]: item for item in record["pages"]}
    reviewed = approval.get("pages_reviewed")
    if not isinstance(reviewed, list) or len(reviewed) != len(pages):
        raise ValueError("Every source page must be explicitly reviewed, including continuation/terms pages")
    seen = set()
    for item in reviewed:
        if not isinstance(item, dict):
            raise ValueError("Each reviewed page requires page, source_page_sha256 and source_page_hash_method")
        page = _page(item.get("page"))
        if page in seen or page not in pages:
            raise ValueError("Reviewed pages must identify every source page exactly once")
        seen.add(page)
        fingerprint = _sha(item.get("source_page_sha256"), "source_page_sha256")
        if pages[page].get("source_page_sha256") != fingerprint or item.get("source_page_hash_method") != PAGE_HASH_METHOD:
            raise ValueError("Reviewed source page SHA-256 or fingerprint method does not match")
        if pages[page].get("source_page_hash_method") != PAGE_HASH_METHOD:
            raise ValueError("Queue pages are not bound to verified source fingerprints")
    validate_expected(approval.get("expected"), seen)
    _optional_text(approval.get("notes"), "Review notes")


def approve_record(record_path, approval, *, reviewer, source_pdf):
    """Accept only explicit review, tied to freshly rechecked source PDF bytes."""
    record = read_json(record_path)
    _validate_record(record)
    raw = source_pdf if isinstance(source_pdf, bytes) else Path(source_pdf).read_bytes()
    if sha256(raw) != record["document"]["sha256"]:
        raise ValueError("Source PDF SHA-256 does not match this queue record")
    live_hashes = source_page_hashes(raw)
    pages = sorted(record["pages"], key=lambda item: item["page"])
    if [item["page"] for item in pages] != list(range(1, len(live_hashes) + 1)):
        raise ValueError("Queue page inventory does not cover the entire source PDF")
    if [item.get("source_page_sha256") for item in pages] != live_hashes:
        raise ValueError("Source page SHA-256 does not match; collect again with the original PDF")
    _validate_review(record, approval, reviewer)
    if record.get("review_status") == "approved":
        if record.get("corrected_expected") == approval["expected"]:
            return record
        raise ValueError("This record already has approved corrections; they cannot be overwritten")
    if record.get("review_status") != "pending":
        raise ValueError("Only pending records can be approved")
    record["review_status"] = "approved"
    record["corrected_expected"] = deepcopy(approval["expected"])
    record["human_review"] = dict(reviewer=reviewer, approved_utc=datetime.now(timezone.utc).isoformat(),
                                 method="Human visual review of all original PDF pages; explicit correction import",
                                 pages_reviewed=deepcopy(approval["pages_reviewed"]), notes=approval.get("notes"))
    write_json(record_path, record)
    return record


def export_gold(records):
    """Export approved records only; reject pending, partial or conflicting truth."""
    documents = {}
    for record in records:
        _validate_record(record)
        if record.get("review_status") != "approved" or not isinstance(record.get("human_review"), dict):
            raise ValueError("Unreviewed predictions cannot be exported as gold labels")
        review = record["human_review"]
        approval = dict(schema_version=1, record_id=record["record_id"], document_sha256=record["document"]["sha256"],
                        pages_reviewed=review.get("pages_reviewed"), expected=record.get("corrected_expected"), notes=review.get("notes"))
        _sha(record["document"]["sha256"])
        _validate_review(record, approval, review.get("reviewer"))
        source = record["document"]
        label = dict(filename=source.get("filename"), archive_entry=source.get("archive_entry"), sha256=source["sha256"],
                     leakage_group=source.get("leakage_group"), review_status="visually_verified",
                     evidence=dict(method=review["method"], reviewer=review["reviewer"], approved_utc=review["approved_utc"],
                                   pages_reviewed=sorted(item["page"] for item in review["pages_reviewed"]),
                                   source_pages=deepcopy(review["pages_reviewed"]), notes=review.get("notes"), record_id=record["record_id"]),
                     expected=deepcopy(record["corrected_expected"]))
        previous = documents.get(source["sha256"])
        if previous and previous["expected"] != label["expected"]:
            raise ValueError("Conflicting approved labels for identical source document bytes")
        documents[source["sha256"]] = label
    if not documents:
        raise ValueError("No approved reference documents supplied")
    return dict(schema_version=1, scope="Explicit human-reviewed source labels for development evaluation; no training performed.",
                documents=list(documents.values()))
