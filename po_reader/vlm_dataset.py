"""Private, source-bound VLM datasets; candidates never become approved labels.

The builder runs no model and has no training operation. It retains source PDFs,
full-page images and native evidence separately from draft visual transcriptions.
An approved export requires an explicit human release of every original page.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile

from .model_provider import (EXTRACTION_INSTRUCTIONS, EXTRACTION_PROMPT_VERSION,
                             PAGE_EXTRACTION_SCHEMA, SCHEMA_VERSION, validate_schema)
from .rendering import PDFIUM_LOCK
from .review_collection import PAGE_HASH_METHOD, source_page_hashes


DATASET_VERSION = "po-vlm-candidates-v1"
RENDER_SCALE = 3
RENDER_METHOD = "pdfium-rgb-scale-3-png-v1"
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_ZIP_ENTRIES = 10000
NEAR_DUPLICATE_DISTANCE = 4


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def value_digest(value):
    return digest(canonical_bytes(value))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    Path(path).write_text("".join(canonical_bytes(row).decode("utf-8") + "\n" for row in rows), encoding="utf-8")


def _hash(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"{name} must be an exact lowercase SHA-256")
    return value


def page_id(source_sha256, page):
    _hash(source_sha256, "source_sha256")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("Page numbers start at 1")
    return f"{source_sha256}-p{page:03d}"


def _asset(root, relative):
    path = (Path(root) / relative).resolve()
    if Path(root).resolve() not in path.parents:
        raise ValueError("Dataset asset escaped its private root")
    return path


def _save_immutable(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Existing evidence differs; use a new output directory: {path.name}")
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def archive_documents(zip_path):
    """No archive member name becomes an extraction path, including ../ names."""
    docs = {}
    ignored = []
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        entries = sorted(archive.infolist(), key=lambda e: (e.filename.casefold(), e.filename, e.header_offset))
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError("ZIP exceeds the bounded entry limit")
        for entry in entries:
            if entry.is_dir():
                continue
            if not entry.filename.lower().endswith(".pdf"):
                ignored.append(dict(archive_entry=entry.filename, size_bytes=entry.file_size))
                continue
            if entry.file_size > MAX_PDF_BYTES:
                raise ValueError("PDF exceeds the 100 MiB limit")
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("ZIP PDFs exceed the 1 GiB aggregate limit")
            raw = archive.read(entry)
            sha = digest(raw)
            alias = dict(archive_entry=entry.filename,
                         filename=PurePosixPath(entry.filename.replace("\\", "/")).name,
                         zip_crc32=f"{entry.CRC:08x}", zip_header_offset=entry.header_offset)
            if sha in docs:
                docs[sha]["aliases"].append(alias)
            else:
                docs[sha] = dict(source_sha256=sha, size_bytes=len(raw), aliases=[alias], raw=raw)
    if not docs:
        raise ValueError("The ZIP contains no PDFs")
    return sorted(docs.values(), key=lambda d: (d["aliases"][0]["archive_entry"].casefold(), d["source_sha256"])), ignored


def _dhash(image):
    """64-bit visual fingerprint; near-duplicate candidates affect splits only."""
    from PIL import Image
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.get_flattened_data()) if hasattr(small, "get_flattened_data") else list(small.getdata())
    result = 0
    for row in range(8):
        for col in range(8):
            result = (result << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    small.close()
    return f"{result:016x}"


def render_document(raw, source_sha256, work_dir, *, write_assets=True):
    import pypdfium2 as pdfium
    fingerprints = source_page_hashes(raw)
    pages = []
    with PDFIUM_LOCK, pdfium.PdfDocument(raw) as document:
        for number in range(1, len(document) + 1):
            source_page = document[number - 1]
            try:
                identifier = page_id(source_sha256, number)
                bitmap = source_page.render(scale=RENDER_SCALE)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    try:
                        stream = io.BytesIO()
                        image.save(stream, format="PNG")
                        png = stream.getvalue()
                        width, height = image.size
                        perceptual = _dhash(image)
                        rgb_sha = digest(f"RGB:{width}:{height}:".encode() + image.tobytes())
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                text_page = source_page.get_textpage()
                try:
                    native_text = text_page.get_text_range()
                finally:
                    text_page.close()
                text_raw = native_text.encode("utf-8")
                image_path = f"images/{identifier}.png"
                native_path = f"native/{identifier}.txt"
                if write_assets:
                    _save_immutable(_asset(work_dir, image_path), png)
                    _save_immutable(_asset(work_dir, native_path), text_raw)
                pages.append(dict(page_id=identifier, source_sha256=source_sha256, page=number,
                                  source_page_sha256=fingerprints[number - 1], source_page_hash_method=PAGE_HASH_METHOD,
                                  image_path=image_path, image_sha256=digest(png), image_rgb_sha256=rgb_sha,
                                  render_method=RENDER_METHOD, dpi=216, width=width, height=height,
                                  native_text_path=native_path, native_text_sha256=digest(text_raw),
                                  native_text_chars=len(native_text), visual_dhash64=perceptual))
            finally:
                source_page.close()
    if not pages:
        raise ValueError("The source PDF has no pages")
    return pages


def prepare(zip_path, work_dir):
    """Inventory immutable originals and render pages. Failures stay in denominator."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    docs, ignored = archive_documents(zip_path)
    for index, doc in enumerate(docs, 1):
        raw = doc.pop("raw")
        doc["document_id"] = f"D{index:02d}"
        doc["source_path"] = f"sources/{doc['source_sha256']}.pdf"
        _save_immutable(_asset(work_dir, doc["source_path"]), raw)
        try:
            doc["pages"] = render_document(raw, doc["source_sha256"], work_dir)
            doc["inventory_error"] = None
        except Exception as error:
            doc["pages"] = []
            doc["inventory_error"] = f"{type(error).__name__}: {error}"
    inventory = dict(schema_version=1, dataset_version=DATASET_VERSION,
                     archive=dict(filename=Path(zip_path).name, sha256=digest(Path(zip_path).read_bytes())),
                     render_method=RENDER_METHOD, documents=docs, ignored_entries=ignored,
                     counts=dict(pdf_entries=sum(len(d["aliases"]) for d in docs), unique_documents=len(docs),
                                 pages=sum(len(d["pages"]) for d in docs),
                                 failed_documents=sum(bool(d["inventory_error"]) for d in docs)))
    write_json(work_dir / "dataset-inventory.json", inventory)
    (work_dir / "annotations").mkdir(exist_ok=True)
    return inventory


def load_annotations(annotation_dir, pages):
    """Strict candidates keyed by source page or matching image content hash."""
    by_id = {p["page_id"]: p for p in pages}
    by_image = defaultdict(list)
    for page in pages:
        by_image[page["image_sha256"]].append(page)
    result = {}
    image_targets = {}
    for path in sorted(Path(annotation_dir).glob("*.json")):
        item = read_json(path)
        if not isinstance(item, dict):
            raise ValueError(f"Annotation must be an object: {path.name}")
        if item.get("review_status") not in ("pending_human_review", "unreviewed"):
            raise ValueError("Candidate files cannot declare human approval; use separate review forms")
        image_sha = _hash(item.get("image_sha256"), "image_sha256")
        if "source_sha256" in item or "page" in item:
            identifier = page_id(item.get("source_sha256"), item.get("page"))
            matched = [by_id.get(identifier)]
            if matched[0] is None:
                raise ValueError("Annotation identifies a page outside the corpus")
        elif item.get("source_page_id"):
            matched = [by_id.get(item["source_page_id"])]
            if matched[0] is None:
                raise ValueError("Annotation identifies a page outside the corpus")
        else:
            matched = by_image.get(image_sha, [])
            if not matched:
                raise ValueError("Annotation image hash is absent from the corpus")
        target = item.get("target")
        status = item.get("page_status") or ("candidate" if target is not None else "unresolved")
        if status not in ("candidate", "unresolved", "non_extractable"):
            raise ValueError("Unknown page_status")
        if status == "candidate":
            validate_schema(target, PAGE_EXTRACTION_SCHEMA)
            target_sha = value_digest(target)
            if image_sha in image_targets and image_targets[image_sha] != target_sha:
                raise ValueError("Conflicting candidate targets for identical PNG image bytes")
            image_targets[image_sha] = target_sha
        elif target is not None:
            raise ValueError("Unresolved/non_extractable pages cannot supply supervised targets")
        family = item.get("layout_family")
        if family is not None and (not isinstance(family, str) or not family.strip()):
            raise ValueError("layout_family must be a nonempty string or null")
        if not isinstance(item.get("annotation_origin"), str) or not item["annotation_origin"].strip():
            raise ValueError("Every candidate requires an annotation_origin")
        if not isinstance(item.get("notes", []), list) or any(not isinstance(n, str) for n in item.get("notes", [])):
            raise ValueError("Annotation notes must be a list of strings")
        for page in matched:
            if page["image_sha256"] != image_sha:
                raise ValueError("Annotation image SHA-256 does not match its source page")
            copy = deepcopy(item)
            copy.update(source_sha256=page["source_sha256"], page=page["page"], page_status=status)
            copy["candidate_sha256"] = value_digest(target)
            copy["annotation_file_sha256"] = digest(path.read_bytes())
            previous = result.get(page["page_id"])
            if previous and canonical_bytes(previous) != canonical_bytes(copy):
                raise ValueError("Conflicting candidate annotations for the same page")
            result[page["page_id"]] = copy
    return result


def group_documents(documents, annotations):
    """Connected exact/near-page and declared-layout families stay in one split."""
    parents = list(range(len(documents)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parents[max(left, right)] = min(left, right)

    exact = {}
    family_seen = {}
    flattened = []
    links = []
    for index, doc in enumerate(documents):
        for page in doc["pages"]:
            fingerprint = page["source_page_sha256"]
            if fingerprint in exact:
                other_index, other_page = exact[fingerprint]
                union(index, other_index)
                links.append(dict(left=page["page_id"], right=other_page, reason="identical_source_page_pixels"))
            else:
                exact[fingerprint] = index, page["page_id"]
            family = annotations.get(page["page_id"], {}).get("layout_family")
            if family:
                if family in family_seen:
                    union(index, family_seen[family])
                else:
                    family_seen[family] = index
            flattened.append((index, page))
    for offset, (index, page) in enumerate(flattened):
        for other_index, other in flattened[:offset]:
            if index == other_index or page["source_page_sha256"] == other["source_page_sha256"]:
                continue
            aspect = page["width"] / page["height"]
            other_aspect = other["width"] / other["height"]
            if abs(aspect / other_aspect - 1) > 0.02:
                continue
            distance = (int(page["visual_dhash64"], 16) ^ int(other["visual_dhash64"], 16)).bit_count()
            if distance <= NEAR_DUPLICATE_DISTANCE:
                union(index, other_index)
                links.append(dict(left=page["page_id"], right=other["page_id"], reason="near_duplicate_visual_candidate",
                                  dhash_hamming_distance=distance))
    components = defaultdict(list)
    for index, doc in enumerate(documents):
        components[find(index)].append(doc["source_sha256"])
    groups = {}
    for members in components.values():
        identifier = "group-" + value_digest(sorted(members))[:16]
        bucket = int(digest(("po-vlm-proposed-split-v1:" + identifier).encode())[:8], 16) % 100
        split = "train" if bucket < 80 else "validation" if bucket < 90 else "test"
        groups[identifier] = dict(source_sha256=sorted(members), proposed_split=split)
        for doc in documents:
            if doc["source_sha256"] in members:
                doc["leakage_group"] = identifier
                doc["proposed_split"] = split
                for page in doc["pages"]:
                    page["leakage_group"] = identifier
                    page["proposed_split"] = split
    return dict(method="Connected document groups: exact 54 DPI RGB page hashes, 64-bit dHash candidates (distance <= 4, aspect within 2%), declared layout families.",
                limitation="dHash is conservative split hygiene, not proof of duplicate semantic content; groups may be overmerged.",
                split_policy="Deterministic hash assignment, proposed 80/10/10; small corpus may have empty splits. No measured generalization claim.",
                groups=groups, page_links=links,
                declared_layout_families=sorted(family_seen))


def message_row(page, target, *, status, review=None):
    validate_schema(target, PAGE_EXTRACTION_SCHEMA)
    return dict(id=page["page_id"], images=[page["image_path"]], messages=[
        dict(role="system", content=EXTRACTION_INSTRUCTIONS),
        dict(role="user", content=[dict(type="image", image=page["image_path"]),
                                  dict(type="text", text="Read every visible business field and row on this page. Return only strict JSON in the provided page extraction schema.")]),
        dict(role="assistant", content=canonical_bytes(target).decode("utf-8"))],
        metadata=dict(source_sha256=page["source_sha256"], page=page["page"], image_sha256=page["image_sha256"],
                      source_page_sha256=page["source_page_sha256"], candidate_sha256=value_digest(target),
                      label_status=status, training_eligible=status == "human_approved_released",
                      leakage_group=page["leakage_group"], proposed_split=page["proposed_split"],
                      schema_version=SCHEMA_VERSION, prompt_version=EXTRACTION_PROMPT_VERSION,
                      human_review=review))


def unique_rows(rows):
    """Avoid overweighting exact reprints while retaining every source occurrence."""
    groups = {}
    for row in rows:
        key = row["metadata"]["image_sha256"]
        if key not in groups:
            groups[key] = deepcopy(row)
            groups[key]["metadata"]["duplicate_source_pages"] = []
        elif (row["messages"][-1]["content"] != groups[key]["messages"][-1]["content"] or
              row["metadata"]["leakage_group"] != groups[key]["metadata"]["leakage_group"] or
              row["metadata"]["proposed_split"] != groups[key]["metadata"]["proposed_split"]):
            raise ValueError("Identical image examples have conflicting targets or split groups")
        groups[key]["metadata"]["duplicate_source_pages"].append(dict(source_sha256=row["metadata"]["source_sha256"],
            page=row["metadata"]["page"], page_id=row["id"], human_review=deepcopy(row["metadata"]["human_review"])))
    return list(groups.values())


def review_template(document, annotations):
    """Blank human decisions; identifiers bind evidence without preapproving targets."""
    return dict(schema_version=1, document_sha256=document["source_sha256"], reviewer=None,
                reviewed_utc=None, release_for_training=False, source_document_review_complete=False,
                pages=[dict(page=p["page"], source_page_sha256=p["source_page_sha256"],
                            source_page_hash_method=PAGE_HASH_METHOD, image_sha256=p["image_sha256"],
                            candidate_sha256=annotations.get(p["page_id"], {}).get("candidate_sha256", value_digest(None)),
                            decision=None, approved_target=None, notes=[]) for p in document["pages"]])


def _dataset_readme(manifest):
    counts = manifest["counts"]
    return f"""# Private VLM candidate dataset

This folder contains {counts['unique_documents']} unique original PDFs ({counts['pdf_entries']} ZIP entries), {counts['pages']} rendered pages and {counts['draft_examples']} draft examples. Sources are retained byte for byte. This is a reviewable training-format dataset, not approved training data. No model was trained or contacted.

- `manifest.json`: all source aliases and all pages, including unlabeled, unresolved and non-extractable pages; exact/near duplicate groups and proposed splits.
- `sources/<sha256>.pdf`: immutable original PDFs named by SHA-256, never ZIP paths.
- `images/<sha256>-pNNN.png`: 216 DPI RGB PNG pages; image SHA-256 and source fingerprints in the manifest.
- `native/<sha256>-pNNN.txt`: native PDF text as separate corroborating evidence, with its own SHA-256. It is not the assistant target.
- `evidence/<sha256>-pNNN.json`: retained preparatory native text, word positions and layout extraction where provided, hashed separately from the candidate labels.
- `labels/candidates/<sha256>-pNNN.json`: unapproved source-bound transcriptions and provenance; strict PAGE_EXTRACTION_SCHEMA targets only.
- `draft/all.jsonl`, `draft/train.jsonl`, `draft/validation.jsonl`, `draft/test.jsonl`: Qwen-style system/user/assistant messages, relative image paths and strict JSON assistant content. Candidate rows have training_eligible=false.
- `draft/unique-all.jsonl` and `draft/unique-<split>.jsonl`: optional preferred eventual training views with one example per identical PNG; metadata retains every source page occurrence. The full views retain all pages for audit. Approved releases also provide optional unique views.
- `review/templates/<sha256>.json`: blank human review forms. Copy to `review/completed/`, inspect every original PDF page, complete reviewer/time and decisions, provide full corrected strict JSON targets, then explicitly set release_for_training and source_document_review_complete true.
- `approved/`: initially empty JSONL files. Only `export-approved` can populate an export directory from completed human reviews.

Human decisions are `approve` (unchanged candidate), `correct` (complete corrected target) or `exclude` (no supervised example; blank/illegible pages may be excluded). Every original page must have an explicit decision. Review forms require exact document, rendered image, low-resolution source-page and candidate-target hashes. Changed evidence, incomplete review, conflicting labels, absent release and unexpected schema fields stop the export. A timestamp must include a timezone. A reviewer name is a recorded declaration of human review; software cannot prove the human inspected the page.

Targets preserve printed raw strings. Catalog matching decisions do not belong in these extraction targets. Existing project evaluation labels are not imported or released to training. Continuation/terms pages may have valid targets with zero product rows; unresolved/non-extractable pages have no supervised draft rows.

Splits are proposed group-safe assignments. Exact pixels, conservative near-page candidates and declared layout families connect whole documents. With a small corpus there may be too few independent groups or empty splits. All aliases and duplicate pages stay together. Draft counts are not measured model accuracy, approved label counts or evidence of generalization. Future calibration and approved training remain separate decisions.

All PDFs, images, native text, targets and human corrections are private. Keep this entire folder under the ignored `output/` directory. Commit only reusable builder/tests/documentation. Rendering uses PDFium scale=3 (216 DPI); source fingerprints use the existing review_collection scale=0.75 contract. No external service or model is needed.
"""


def build(zip_path, work_dir, output_dir, annotation_dir=None):
    """Rerender from retained ZIP bytes; import candidates only after hash matching."""
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Dataset output must be empty; preserve existing reviews and use a new directory")
    inventory = prepare(zip_path, work_dir)
    documents = deepcopy(inventory["documents"])
    pages = [page for doc in documents for page in doc["pages"]]
    annotations = load_annotations(annotation_dir or Path(work_dir) / "annotations", pages)
    groups = group_documents(documents, annotations)
    rows = []
    for page in pages:
        annotation = annotations.get(page["page_id"])
        page["page_status"] = annotation["page_status"] if annotation else "unlabeled"
        page["review_status"] = "pending_human_review"
        page["training_eligible"] = False
        page["layout_family"] = annotation.get("layout_family") if annotation else None
        page["candidate_sha256"] = annotation["candidate_sha256"] if annotation else value_digest(None)
        if annotation:
            label_path = f"labels/candidates/{page['page_id']}.json"
            write_json(_asset(output_dir, label_path), annotation)
            page["candidate_path"] = label_path
            page["candidate_file_sha256"] = digest(_asset(output_dir, label_path).read_bytes())
            if annotation["page_status"] == "candidate":
                rows.append(message_row(page, annotation["target"], status="candidate_unreviewed"))
        # Preserve the preparatory native extraction/layout record independently
        # of visual targets, when provided by a corpus inspection workflow.
        evidence_relative = f"evidence/{page['page_id']}.json"
        evidence_path = _asset(work_dir, evidence_relative)
        if evidence_path.exists():
            evidence = read_json(evidence_path)
            if evidence.get("source_sha256") != page["source_sha256"] or evidence.get("page") != page["page"] or evidence.get("image_sha256") != page["image_sha256"]:
                raise ValueError("Preparatory native evidence is bound to different source/image bytes")
            page["native_evidence_path"] = evidence_relative
            page["native_evidence_sha256"] = digest(evidence_path.read_bytes())
    for doc in documents:
        for relative in [doc["source_path"], *[p[key] for p in doc["pages"] for key in ("image_path", "native_text_path", "native_evidence_path") if key in p]]:
            destination = _asset(output_dir, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_asset(work_dir, relative), destination)
        if doc["pages"]:
            write_json(output_dir / "review" / "templates" / f"{doc['source_sha256']}.json", review_template(doc, annotations))
    deduplicated = unique_rows(rows)
    counts = dict(inventory["counts"], draft_examples=len(rows), unique_draft_examples=len(deduplicated), approved_examples=0,
                  page_status=dict(Counter(p["page_status"] for p in pages)), leakage_groups=len(groups["groups"]))
    manifest = dict(schema_version=1, dataset_version=DATASET_VERSION, archive=inventory["archive"],
                    render_method=RENDER_METHOD, target_schema_version=SCHEMA_VERSION,
                    extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                    label_policy="Candidates pending human review. No training performed. Approved export requires explicit release.",
                    documents=documents, ignored_entries=inventory["ignored_entries"], grouping=groups, counts=counts)
    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "page-extraction-schema.json", PAGE_EXTRACTION_SCHEMA)
    for directory in ("draft", "approved", "review/completed"):
        (output_dir / directory).mkdir(parents=True, exist_ok=True)
    for split in ("all", "train", "validation", "test"):
        write_jsonl(output_dir / "draft" / f"{split}.jsonl", rows if split == "all" else [r for r in rows if r["metadata"]["proposed_split"] == split])
        write_jsonl(output_dir / "draft" / f"unique-{split}.jsonl", deduplicated if split == "all" else [r for r in deduplicated if r["metadata"]["proposed_split"] == split])
        write_jsonl(output_dir / "approved" / f"{split}.jsonl", [])
        write_jsonl(output_dir / "approved" / f"unique-{split}.jsonl", [])
    (output_dir / "README.md").write_text(_dataset_readme(manifest), encoding="utf-8")
    validate_dataset(output_dir)
    return manifest


def validate_dataset(dataset_dir):
    """Independently rehash every saved source, image, native text and target."""
    dataset_dir = Path(dataset_dir)
    manifest = read_json(dataset_dir / "manifest.json")
    if manifest.get("dataset_version") != DATASET_VERSION:
        raise ValueError("Unsupported dataset version")
    expected_rows = {}
    page_records = {}
    saved_annotations = {}
    image_targets = {}
    for doc in manifest["documents"]:
        source = _asset(dataset_dir, doc["source_path"]).read_bytes()
        if digest(source) != doc["source_sha256"]:
            raise ValueError("Saved source PDF SHA-256 mismatch")
        if doc.get("inventory_error"):
            continue
        live_pages = render_document(source, doc["source_sha256"], dataset_dir, write_assets=False)
        if len(doc["pages"]) != len(live_pages):
            raise ValueError("Manifest omitted source pages")
        for number, page in enumerate(doc["pages"], 1):
            if page["page_id"] != page_id(doc["source_sha256"], number) or page["page"] != number:
                raise ValueError("Manifest source page identity mismatch")
            live = live_pages[number - 1]
            if page["source_page_sha256"] != live["source_page_sha256"] or page["source_page_hash_method"] != PAGE_HASH_METHOD:
                raise ValueError("Source page fingerprint mismatch")
            for field in ("image_sha256", "image_rgb_sha256", "render_method", "dpi", "width", "height", "visual_dhash64", "native_text_sha256", "native_text_chars"):
                if page.get(field) != live[field]:
                    raise ValueError(f"Manifest {field} differs from freshly rendered original source evidence")
            if page["leakage_group"] != doc["leakage_group"] or page["proposed_split"] != doc["proposed_split"]:
                raise ValueError("Documents cannot leak across proposed splits")
            if page["training_eligible"] is not False or page["review_status"] != "pending_human_review":
                raise ValueError("Candidate manifest cannot mark pages eligible for training")
            for relative, sha in ((page["image_path"], page["image_sha256"]), (page["native_text_path"], page["native_text_sha256"])):
                if digest(_asset(dataset_dir, relative).read_bytes()) != sha:
                    raise ValueError("Dataset image/native evidence SHA-256 mismatch")
            if page.get("native_evidence_path") and digest(_asset(dataset_dir, page["native_evidence_path"]).read_bytes()) != page["native_evidence_sha256"]:
                raise ValueError("Preparatory native evidence SHA-256 mismatch")
            if page.get("candidate_path"):
                label_path = _asset(dataset_dir, page["candidate_path"])
                if digest(label_path.read_bytes()) != page["candidate_file_sha256"]:
                    raise ValueError("Candidate file changed after dataset creation")
                candidate = read_json(label_path)
                if candidate.get("review_status") not in ("pending_human_review", "unreviewed"):
                    raise ValueError("Candidate labels cannot declare human approval")
                if candidate["image_sha256"] != page["image_sha256"] or candidate["source_sha256"] != doc["source_sha256"] or candidate["page"] != number:
                    raise ValueError("Candidate evidence identity mismatch")
                if value_digest(candidate["target"]) != page["candidate_sha256"]:
                    raise ValueError("Candidate target SHA-256 mismatch")
                if candidate["page_status"] != page["page_status"] or candidate.get("layout_family") != page["layout_family"]:
                    raise ValueError("Candidate status/layout differs from the manifest")
                saved_annotations[page["page_id"]] = candidate
                if page["page_status"] == "candidate":
                    image_sha, target_sha = page["image_sha256"], value_digest(candidate["target"])
                    if image_sha in image_targets and image_targets[image_sha] != target_sha:
                        raise ValueError("Conflicting candidate targets for identical PNG image bytes")
                    image_targets[image_sha] = target_sha
                    expected_rows[page["page_id"]] = message_row(page, candidate["target"], status="candidate_unreviewed")
                elif candidate["target"] is not None:
                    raise ValueError("Unresolved/non_extractable candidate has a supervised target")
            page_records[page["page_id"]] = page
    actual_rows = [json.loads(line) for line in (dataset_dir / "draft" / "all.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len(actual_rows) != len(expected_rows) or {r["id"] for r in actual_rows} != set(expected_rows):
        raise ValueError("Draft examples do not cover exactly the candidate pages")
    for row in actual_rows:
        if row != expected_rows[row["id"]]:
            raise ValueError("Draft row differs from its bound candidate and message contract")
        target = json.loads(row["messages"][-1]["content"])
        validate_schema(target, PAGE_EXTRACTION_SCHEMA)
    for split in ("train", "validation", "test"):
        actual = [json.loads(line) for line in (dataset_dir / "draft" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        expected = [r for r in actual_rows if r["metadata"]["proposed_split"] == split]
        if actual != expected:
            raise ValueError("Draft split rows differ from the group-safe all-page file")
    expected_unique = unique_rows(actual_rows)
    for split in ("all", "train", "validation", "test"):
        actual = [json.loads(line) for line in (dataset_dir / "draft" / f"unique-{split}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        expected = expected_unique if split == "all" else [r for r in expected_unique if r["metadata"]["proposed_split"] == split]
        if actual != expected:
            raise ValueError("Unique draft rows differ from their identical-image source occurrences")
        for prefix in ("", "unique-"):
            if (dataset_dir / "approved" / f"{prefix}{split}.jsonl").read_text(encoding="utf-8").strip():
                raise ValueError("Candidate dataset approved placeholders must remain empty; use a separate released export")
    recomputed = group_documents(deepcopy(manifest["documents"]), saved_annotations)
    if recomputed != manifest["grouping"]:
        raise ValueError("Proposed split groups differ from original evidence/layout families")
    if manifest["counts"]["draft_examples"] != len(actual_rows) or manifest["counts"]["unique_draft_examples"] != len(expected_unique) or manifest["counts"]["approved_examples"] != 0:
        raise ValueError("Dataset example counts differ from saved draft records")
    return dict(valid=True, counts=manifest["counts"])


def _reviewed_date(value):
    if not isinstance(value, str):
        raise ValueError("Human review requires a timezone-qualified reviewed_utc timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid human review timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("Human review timestamp requires a timezone")


def export_approved(dataset_dir, review_dir, output_dir):
    """Fail closed, before writing, if any supplied completed review is invalid."""
    validate_dataset(dataset_dir)
    dataset_dir, output_dir = Path(dataset_dir), Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Approved export output must be empty; never overwrite prior releases")
    manifest = read_json(dataset_dir / "manifest.json")
    documents = {doc["source_sha256"]: doc for doc in manifest["documents"]}
    reviews = sorted(Path(review_dir).glob("*.json"))
    if not reviews:
        raise ValueError("No completed human reviews supplied; approved export remains empty")
    rows = []
    reviewed_documents = set()
    review_forms = []
    for review_path in reviews:
        payload = read_json(review_path)
        if isinstance(payload, dict) and isinstance(payload.get("reviews"), list):
            if payload.get("schema_version") != 1:
                raise ValueError("Unsupported review bundle schema")
            if payload.get("archive_sha256") is not None and payload["archive_sha256"] != manifest["archive"]["sha256"]:
                raise ValueError("Review bundle archive SHA-256 differs from the dataset")
            review_forms.extend((review_path, form) for form in payload["reviews"])
        else:
            review_forms.append((review_path, payload))
    for review_path, review in review_forms:
        if not isinstance(review, dict):
            raise ValueError("Human review must be an object")
        sha = _hash(review.get("document_sha256"), "document_sha256")
        if review.get("schema_version") != 1 or sha not in documents or sha in reviewed_documents:
            raise ValueError("Review must identify exactly one known original document")
        doc = documents[sha]
        if doc.get("inventory_error"):
            raise ValueError("Unrendered source documents cannot be released")
        if review.get("release_for_training") is not True or review.get("source_document_review_complete") is not True:
            raise ValueError("Explicit human completion and release_for_training are required")
        if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            raise ValueError("A named human reviewer is required")
        _reviewed_date(review.get("reviewed_utc"))
        inspected = review.get("pages")
        if not isinstance(inspected, list) or len(inspected) != len(doc["pages"]):
            raise ValueError("Human review must explicitly cover every original page")
        seen = set()
        for item in inspected:
            number = item.get("page")
            if not isinstance(number, int) or isinstance(number, bool) or number in seen or not 1 <= number <= len(doc["pages"]):
                raise ValueError("Every original page must be reviewed exactly once")
            seen.add(number)
            page = doc["pages"][number - 1]
            for field in ("source_page_sha256", "image_sha256", "candidate_sha256"):
                if item.get(field) != page[field]:
                    raise ValueError(f"Human review {field} does not match retained evidence")
            if item.get("source_page_hash_method") != PAGE_HASH_METHOD:
                raise ValueError("Human review source fingerprint method differs")
            decision = item.get("decision")
            if decision not in ("approve", "correct", "exclude"):
                raise ValueError("Every page requires approve, correct or exclude")
            target = item.get("approved_target")
            if decision == "exclude":
                if target is not None:
                    raise ValueError("Excluded pages must have no supervised target")
                continue
            validate_schema(target, PAGE_EXTRACTION_SCHEMA)
            if decision == "approve" and (page["page_status"] != "candidate" or value_digest(target) != page["candidate_sha256"]):
                raise ValueError("Approve requires the complete unchanged candidate; use correct for edits")
            evidence = dict(reviewer=review["reviewer"], reviewed_utc=review["reviewed_utc"],
                            method="Explicit human visual review and release of every original PDF page",
                            decision=decision, review_file_sha256=digest(review_path.read_bytes()),
                            original_candidate_sha256=page["candidate_sha256"])
            rows.append(message_row(page, target, status="human_approved_released", review=evidence))
        reviewed_documents.add(sha)
    if not rows:
        raise ValueError("Human reviews contain no approved supervised targets")
    # Identical source pixels must not receive incompatible released targets.
    duplicate_targets = {}
    for row in rows:
        key = row["metadata"]["source_page_sha256"]
        target = row["messages"][-1]["content"]
        if key in duplicate_targets and duplicate_targets[key] != target:
            raise ValueError("Conflicting approved targets for identical source page pixels")
        duplicate_targets[key] = target
    output_dir.mkdir(parents=True, exist_ok=True)
    deduplicated = unique_rows(rows)
    for row in rows:
        source_image = dataset_dir / row["images"][0]
        destination = output_dir / row["images"][0]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source_image, destination)
    for split in ("all", "train", "validation", "test"):
        write_jsonl(output_dir / f"{split}.jsonl", rows if split == "all" else [r for r in rows if r["metadata"]["proposed_split"] == split])
        write_jsonl(output_dir / f"unique-{split}.jsonl", deduplicated if split == "all" else [r for r in deduplicated if r["metadata"]["proposed_split"] == split])
    release = dict(schema_version=1, dataset_version=DATASET_VERSION, human_approved_examples=len(rows),
                   unique_human_approved_examples=len(deduplicated),
                   reviewed_documents=sorted(reviewed_documents), source_dataset_manifest_sha256=digest((dataset_dir / "manifest.json").read_bytes()),
                   policy="Explicit human review release only. No training performed. Group-safe proposed splits remain experimental.")
    write_json(output_dir / "release.json", release)
    return release
