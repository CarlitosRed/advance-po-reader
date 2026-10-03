"""Inventory a PDF ZIP and measure native or vision extraction without cart writes.

Gold comes only from independently reviewed labels. Null expectations are never
counted as correct, and model output is never copied into the gold template.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import sys
import time
import zipfile

from po_reader.catalog import DB, ROOT, load_catalog
from po_reader.engine import analyze, read_pages
from po_reader.rendering import PDFIUM_LOCK


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_archive(path):
    """Read members in memory; ZIP names are never used as filesystem paths."""
    documents = []
    with zipfile.ZipFile(path) as archive:
        for entry in sorted(archive.infolist(), key=lambda e: (e.filename.casefold(), e.header_offset)):
            if entry.is_dir() or not entry.filename.casefold().endswith(".pdf"):
                continue
            if entry.file_size > 100 * 1024 * 1024:
                raise ValueError(f"PDF exceeds the 100 MiB benchmark limit: {entry.filename}")
            raw = archive.read(entry)
            documents.append(dict(archive_entry=entry.filename,
                                  filename=PurePosixPath(entry.filename.replace("\\", "/")).name,
                                  sha256=digest(raw), size_bytes=len(raw), raw=raw))
    if not documents:
        raise ValueError("The ZIP has no PDF entries")
    return documents


def page_fingerprints(raw):
    """Hash full rendered RGB pixels at a fixed resolution, not PDF metadata.

    Shared pages conservatively connect documents for split assignment. This also
    connects two different POs with an identical terms page, which is deliberate.
    """
    import pypdfium2 as pdfium
    fingerprints = []
    with PDFIUM_LOCK, pdfium.PdfDocument(raw) as document:
        for page in document:
            try:
                bitmap = page.render(scale=0.75)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    try:
                        data = f"RGB:{image.width}:{image.height}:".encode() + image.tobytes()
                        fingerprints.append(digest(data))
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    return fingerprints


def group_duplicates(documents):
    """Connected components of identical bytes or shared rendered pages."""
    parents = list(range(len(documents)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(a, b):
        left, right = find(a), find(b)
        if left != right:
            parents[max(left, right)] = min(left, right)

    seen = {}
    page_refs = defaultdict(list)
    raw_refs = defaultdict(list)
    for index, doc in enumerate(documents):
        raw_refs[doc["sha256"]].append(doc["archive_entry"])
        for key in [("document", doc["sha256"]), *[("page", p) for p in doc.get("page_fingerprints", [])]]:
            if key in seen:
                union(index, seen[key])
            else:
                seen[key] = index
        for page, fingerprint in enumerate(doc.get("page_fingerprints", []), 1):
            page_refs[fingerprint].append(dict(archive_entry=doc["archive_entry"], page=page))
    groups = defaultdict(list)
    for index, doc in enumerate(documents):
        group = f"leakage-{find(index)+1:03d}"
        doc["leakage_group"] = group
        groups[group].append(doc["archive_entry"])
    return dict(method="document SHA-256 and identical RGB page pixels at PDFium scale 0.75; keep connected groups in one split",
                groups=dict(groups),
                byte_duplicate_documents=[dict(sha256=key, entries=refs) for key, refs in raw_refs.items() if len(refs) > 1],
                rendered_duplicate_pages=[dict(fingerprint=key, references=refs) for key, refs in page_refs.items() if len(refs) > 1],
                duplicate_page_occurrences=sum(len(refs)-1 for refs in page_refs.values() if len(refs) > 1))


def inventory_documents(documents):
    for doc in documents:
        try:
            pages = read_pages(doc["raw"])
            doc["pages"] = [dict(page=p["page"], width=p["width"], height=p["height"],
                                 text_chars=len(p["text"]), independent_text_chars=len(p["independent_text"]),
                                 word_count=len(p["words"]), image_count=p["image_count"],
                                 classification=p["classification"]) for p in pages]
            doc["page_fingerprints"] = page_fingerprints(doc["raw"])
        except Exception as error:
            doc["inventory_error"] = str(error)
    return group_duplicates(documents)


def gold_template(documents):
    return dict(schema_version=1,
                scope="Unverified template only. Independently inspect source pages before entering any expectations.",
                documents=[dict(filename=d["filename"], archive_entry=d["archive_entry"], sha256=d["sha256"],
                                leakage_group=d["leakage_group"], review_status="unverified",
                                evidence=dict(method=None, pages_reviewed=[], notes=None),
                                expected=dict(po_number=None, lines=None)) for d in documents])


def load_gold(path):
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("documents"), list):
        raise ValueError("Gold requires schema_version=1 and a documents list")
    labels = {}
    for item in data["documents"]:
        sha = item.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Each gold document requires its exact lowercase SHA-256")
        if sha in labels and labels[sha].get("expected") != item.get("expected"):
            raise ValueError("Conflicting gold labels for the same document bytes")
        if sha in labels and labels[sha].get("review_status") == "visually_verified":
            # A duplicate alias/template must not downgrade independent review
            # or replace the evidence attached to the stronger existing label.
            continue
        labels[sha] = item
    return labels


def scalar(value):
    return value.get("value") if isinstance(value, dict) else value


def identifier_pairs(line):
    identifiers = line.get("identifiers")
    if isinstance(identifiers, list):
        return tuple(sorted(set((str(item["raw_value"]).strip(), str(item.get("role") or "unknown"))
                                for item in identifiers if item.get("raw_value") is not None)))
    return tuple(sorted(set((str(line[field]).strip(), role)
                            for field, role in (("vendor_id", "vendor_product_code"), ("customer_id", "customer_item_number"), ("supplier_id", "unknown"))
                            if line.get(field) is not None)))


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
        return str(number.normalize()) if number.is_finite() else None
    except InvalidOperation:
        return None


def line_signature(line, *, roles=True, fields=False):
    pairs = identifier_pairs(line)
    ids = pairs if roles else tuple(sorted(set(value for value, _ in pairs)))
    if fields:
        # Case and spacing are presentation differences only. No EA/PK conversion.
        qty = numeric(line.get("quantity"))
        unit = str(line.get("uom") or "").strip().upper() or None
        if fields == "quantity":
            return ids, qty
        if fields == "uom":
            return ids, unit
        return ids, qty, unit
    return ids


def agreements(expected, actual, **signature_options):
    left = Counter(line_signature(row, **signature_options) for row in expected)
    right = Counter(line_signature(row, **signature_options) for row in actual)
    return sum((left & right).values())


def score_document(label, prediction):
    """Count independent source expectations, preserving leading zeros/suffixes.

    Exact signatures are multiset comparisons, so row order does not affect the
    score and repeated/extra extracted rows reduce precision. No approximate
    matching manufactures correctness for identifiers that differ by one letter.
    """
    if not label or label.get("review_status") != "visually_verified":
        return dict(scored=False, reason="No visually verified labels for these document bytes")
    expected = label.get("expected") or {}
    expected_lines = expected.get("lines")
    actual = [line for line in prediction.get("lines", []) if line.get("kind", "product") == "product"]
    result = dict(scored=True, po_number_scored=expected.get("po_number") is not None,
                  po_number_correct=(str(scalar(prediction.get("order_number")) or "").strip() == expected["po_number"])
                  if expected.get("po_number") is not None else None,
                  lines_scored=expected_lines is not None)
    if expected_lines is None:
        return result
    if not isinstance(expected_lines, list):
        raise ValueError("Gold expected.lines must be null or a complete product-line list")
    id_labels = [row for row in expected_lines if identifier_pairs(row)]
    quantity_labels = [row for row in id_labels if numeric(row.get("quantity")) is not None]
    unit_labels = [row for row in id_labels if row.get("uom") is not None]
    full_labels = [row for row in quantity_labels if row.get("uom") is not None]
    result.update(expected_product_lines=len(expected_lines), extracted_product_lines=len(actual),
                  expected_raw_id_labels=len(id_labels), expected_quantity_labels=len(quantity_labels),
                  expected_uom_labels=len(unit_labels), expected_full_line_labels=len(full_labels),
                  exact_raw_id_rows=agreements(id_labels, actual, roles=False),
                  exact_id_and_role_rows=agreements(id_labels, actual),
                  exact_id_quantity_rows=agreements(quantity_labels, actual, roles=False, fields="quantity"),
                  exact_id_uom_rows=agreements(unit_labels, actual, roles=False, fields="uom"),
                  exact_id_quantity_uom_rows=agreements(full_labels, actual, roles=False, fields=True),
                  exact_id_role_quantity_uom_rows=agreements(full_labels, actual, fields=True))
    denominator = len(full_labels)
    recovered = result["exact_id_quantity_uom_rows"]
    role_recovered = result["exact_id_role_quantity_uom_rows"]
    result.update(exact_line_recall=recovered / denominator if denominator else None,
                  exact_line_precision=recovered / len(actual) if actual else None,
                  exact_raw_line_recall=recovered / denominator if denominator else None,
                  exact_raw_line_precision=recovered / len(actual) if actual else None,
                  exact_role_line_recall=role_recovered / denominator if denominator else None,
                  exact_role_line_precision=role_recovered / len(actual) if actual else None,
                  complete_document_correct=(role_recovered == denominator == len(expected_lines) == len(actual) and
                                             result["po_number_correct"] is True))
    known_catalog = [row for row in expected_lines if row.get("expected_catalog_product_id") is not None]
    result["catalog_product_labels"] = len(known_catalog)
    # A printed identifier proves extraction, not membership in the website DB.
    result["catalog_decision_scored"] = bool(known_catalog)
    if known_catalog:
        lookup = {line_signature(row, roles=False): row["expected_catalog_product_id"] for row in known_catalog}
        decisions = [row for row in actual if line_signature(row, roles=False) in lookup]
        result["correct_catalog_decisions"] = sum((row.get("match") or {}).get("product_id") ==
                                                  lookup[line_signature(row, roles=False)] for row in decisions)
        result["wrong_automatic_match_decisions"] = sum((row.get("match") or {}).get("status") == "matched" and
                                                       (row.get("match") or {}).get("product_id") != lookup[line_signature(row, roles=False)]
                                                       for row in decisions)
    return result


def summarize_scores(results, documents, labels):
    scores = [result["score"] for result in results if result.get("score", {}).get("scored")]
    line_scores = [score for score in scores if score.get("lines_scored")]
    expected = sum(score["expected_product_lines"] for score in line_scores)
    fully_labeled = sum(score["expected_full_line_labels"] for score in line_scores)
    extracted = sum(score["extracted_product_lines"] for score in line_scores)
    exact = sum(score["exact_id_quantity_uom_rows"] for score in line_scores)
    exact_roles = sum(score["exact_id_role_quantity_uom_rows"] for score in line_scores)
    labeled = {d["sha256"] for d in documents if labels.get(d["sha256"], {}).get("review_status") == "visually_verified"}
    return dict(total_pdf_entries=len(documents), independently_labeled_unique_documents=len(labeled),
                selected_pdf_entries=len(results), processed_predictions=sum("prediction" in r for r in results),
                failed_predictions=sum("error" in r for r in results), scored_documents=len(scores),
                partial_predictions=sum(r.get("prediction", {}).get("status") == "partial" or
                                        bool(r.get("prediction", {}).get("extraction", {}).get("failures")) for r in results),
                failed_model_pages=sum(len(r.get("prediction", {}).get("extraction", {}).get("failures", [])) for r in results),
                po_numbers_scored=sum(bool(s.get("po_number_scored")) for s in scores),
                exact_po_numbers=sum(s.get("po_number_correct") is True for s in scores),
                expected_product_lines=expected, extracted_product_lines_on_labeled_documents=extracted,
                expected_raw_id_labels=sum(s["expected_raw_id_labels"] for s in line_scores),
                expected_quantity_labels=sum(s["expected_quantity_labels"] for s in line_scores),
                expected_uom_labels=sum(s["expected_uom_labels"] for s in line_scores),
                expected_full_line_labels=fully_labeled,
                exact_raw_id_rows=sum(s["exact_raw_id_rows"] for s in line_scores),
                exact_id_and_role_rows=sum(s["exact_id_and_role_rows"] for s in line_scores),
                exact_id_quantity_rows=sum(s["exact_id_quantity_rows"] for s in line_scores),
                exact_id_uom_rows=sum(s["exact_id_uom_rows"] for s in line_scores),
                exact_id_quantity_uom_rows=exact,
                exact_id_role_quantity_uom_rows=exact_roles,
                exact_line_recall=exact / fully_labeled if fully_labeled else None,
                exact_line_precision=exact / extracted if extracted else None,
                exact_raw_line_recall=exact / fully_labeled if fully_labeled else None,
                exact_raw_line_precision=exact / extracted if extracted else None,
                exact_role_line_recall=exact_roles / fully_labeled if fully_labeled else None,
                exact_role_line_precision=exact_roles / extracted if extracted else None,
                line_metric_definitions=dict(exact_line_recall="Legacy alias of exact_raw_line_recall: raw identifiers, quantity and unit; identifier roles excluded.",
                                             exact_line_precision="Legacy alias of exact_raw_line_precision: raw identifiers, quantity and unit; identifier roles excluded.",
                                             exact_role_line_recall="Exact identifiers, their source roles, quantity and unit divided by fully labeled rows.",
                                             exact_role_line_precision="Exact identifiers, their source roles, quantity and unit divided by extracted product rows."),
                complete_labeled_documents_correct=sum(bool(s.get("complete_document_correct")) for s in line_scores),
                catalog_product_labels=sum(s["catalog_product_labels"] for s in line_scores),
                catalog_accuracy_claim="Unavailable unless independent website catalog labels are supplied; source IDs alone are insufficient.")


def compact_prediction(document):
    return {key: document.get(key) for key in ("filename", "sha256", "profile", "status", "source_type", "company", "shipping", "order_number",
                                              "lines", "warnings", "extraction", "architecture_version") if key in document}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


class ProgressProvider:
    """Expose page progress without changing provider results or request data."""

    def __init__(self, provider):
        self.provider = provider

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def extract_page(self, image, page_number, native_text=""):
        start = time.monotonic()
        print(f"  extracting page {page_number}", file=sys.stderr, flush=True)
        try:
            value = self.provider.extract_page(image, page_number, native_text)
        except Exception as error:
            print(f"  page {page_number} failed after {time.monotonic()-start:.1f}s: {error}", file=sys.stderr, flush=True)
            raise
        print(f"  page {page_number} extracted in {time.monotonic()-start:.1f}s", file=sys.stderr, flush=True)
        return value

    def compare(self, line, candidates):
        print(f"  comparing catalog candidates for {line.get('line_id')}", file=sys.stderr, flush=True)
        return self.provider.compare(line, candidates)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="zip_path", type=Path, default=Path("data") / "Full Data Set.zip")
    parser.add_argument("--mode", choices=("inventory", "native", "vision"), default="inventory")
    parser.add_argument("--provider", choices=("openai", "ollama"), default="ollama")
    parser.add_argument("--pipeline", choices=("single", "cascade"), default="single")
    parser.add_argument("--adjudicator-model", default="gpt-oss:20b")
    parser.add_argument("--no-semantic", action="store_true")
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--extraction-only", action="store_true", help="Use an empty candidate catalog to measure visual extraction separately")
    parser.add_argument("--model", help="Required in vision mode; choose explicitly for a reproducible run")
    parser.add_argument("--base-url")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-labeled", action="store_true", help="Process only visually verified document SHAs")
    parser.add_argument("--label-file", type=Path)
    parser.add_argument("--catalog", type=Path, default=DB)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.mode == "vision" and not args.model:
        parser.error("--model is required in vision mode")
    if args.mode == "vision" and args.provider == "openai" and args.pipeline == "cascade":
        parser.error("--pipeline cascade requires the local Ollama provider; use --pipeline single with OpenAI")
    if args.mode == "vision" and args.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is not configured; no API request was sent")
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        documents = read_archive(args.zip_path)
        duplicates = inventory_documents(documents)
        labels = load_gold(args.label_file)
        selected = [d for d in documents if not args.only_labeled or labels.get(d["sha256"], {}).get("review_status") == "visually_verified"]
        if args.limit:
            selected = selected[:args.limit]
        provider = None
        catalog = None
        if args.mode != "inventory":
            catalog = {} if args.extraction_only else load_catalog(args.catalog)
        if args.mode == "vision":
            # Inventory/native never import providers and never initialize an API client.
            from po_reader.model_provider import build_provider
            from po_reader.vision import analyze_vision
            if args.provider == "ollama" and args.pipeline == "cascade":
                from po_reader.infrastructure import build_stack
                provider = ProgressProvider(build_stack(extractor_model=args.model, adjudicator_model=args.adjudicator_model,
                        base_url=args.base_url, timeout=args.timeout,
                        semantic=not args.no_semantic and not args.extraction_only,
                        reranker=not args.no_reranker and not args.extraction_only))
            else:
                provider = ProgressProvider(build_provider(args.provider, args.model, base_url=args.base_url, timeout=args.timeout))
        results = []
        if args.mode != "inventory":
            for index, doc in enumerate(selected, 1):
                print(f"[{index}/{len(selected)}] {args.mode}: {doc['filename']}", file=sys.stderr, flush=True)
                start = time.monotonic()
                result = dict(filename=doc["filename"], archive_entry=doc["archive_entry"], sha256=doc["sha256"],
                              leakage_group=doc["leakage_group"])
                try:
                    prediction = (analyze_vision(doc["raw"], doc["filename"], catalog, provider) if args.mode == "vision"
                                  else analyze(doc["raw"], doc["filename"], catalog))
                    result["prediction"] = compact_prediction(prediction)
                    result["score"] = score_document(labels.get(doc["sha256"]), prediction)
                    if prediction.get("extraction", {}).get("failures"):
                        print(json.dumps(dict(filename=doc["filename"], page_failures=prediction["extraction"]["failures"])),
                              file=sys.stderr, flush=True)
                except Exception as error:
                    result["error"] = str(error)
                    # A failed labeled prediction counts as missing fields and
                    # rows; excluding it would inflate measured accuracy.
                    result["score"] = score_document(labels.get(doc["sha256"]), dict(lines=[]))
                result["elapsed_seconds"] = round(time.monotonic()-start, 3)
                results.append(result)
        report = dict(schema_version=1, mode=args.mode, source_zip=str(args.zip_path.resolve()),
                      source_zip_sha256=digest(args.zip_path.read_bytes()),
                      provider=args.provider if args.mode == "vision" else None, model=args.model if args.mode == "vision" else None,
                      pipeline=args.pipeline if args.mode == "vision" else None, extraction_only=args.extraction_only,
                      catalog_path=str(args.catalog.resolve()) if catalog is not None else None,
                      catalog_products=len(catalog) if catalog is not None else None,
                      scope="Extraction shadow evaluation. No cart writes. Results are accuracy only for independently labeled documents; repeated pages are grouped for splits.",
                      summary=summarize_scores(results, documents, labels),
                      total_pages=sum(len(d.get("pages", [])) for d in documents), duplicates=duplicates,
                      inventory=[{key: value for key, value in d.items() if key != "raw"} for d in documents], results=results,
                      unknown_label_shas=sorted(set(labels)-{d["sha256"] for d in documents}))
        report["summary"]["selected_pdf_entries"] = len(selected)
        report["summary"]["inventory_failures"] = sum("inventory_error" in d for d in documents)
        template_path = args.output_dir / "vision-gold-template.json"
        report_path = args.output_dir / f"vision-benchmark-{args.mode}.json"
        # Preserve a reviewed template if someone started annotation in this file.
        if not template_path.exists():
            write_json(template_path, gold_template(documents))
        write_json(report_path, report)
    except (ValueError, OSError, zipfile.BadZipFile, ImportError) as error:
        parser.error(str(error))
    print(json.dumps(dict(report=str(report_path), gold_template=str(template_path),
                          total_pages=report["total_pages"], summary=report["summary"]), indent=2))
    return 1 if (any("error" in result for result in results) or report["summary"]["inventory_failures"] or
                 report["summary"]["failed_model_pages"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
