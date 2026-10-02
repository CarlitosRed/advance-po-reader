"""Collect saved inference observations and import explicit human PDF reviews.

Examples:
  python collect_review.py collect --result output/vision-benchmark-vision.json
  python collect_review.py template --record output/review-data/queue/RECORD.json
  python collect_review.py approve --record ... --approval-file ... --reviewer "Carlos Redondo" --source-pdf ...
  python collect_review.py export --record ... --output output/review-data/approved-labels.json

Approval files require the queue record/document identities, all reviewed page
fingerprints, and a complete independently reviewed expected product-line list.
The template leaves corrected values null and reviewed pages empty on purpose.
"""
import argparse
import json
from pathlib import Path
import zipfile

from po_reader.review_collection import (approval_template, approve_record, collect_queue,
                                         export_gold, read_json, sha256, write_json)


ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "output" / "review-data"


def _private_output(path):
    """All generated observations, corrections and labels stay under ignored output."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to((ROOT / "output").resolve()):
        raise ValueError("Review data must be written under the private, ignored project output directory")
    return resolved


def source_loader(args, payload, result_path):
    archive_path = args.source_zip or payload.get("source_zip")
    source_dir = args.source_dir
    def load(result):
        if source_dir:
            # Only a basename is taken from untrusted saved-result metadata.
            filename = str(result.get("filename") or "").replace("\\", "/").split("/")[-1]
            candidate = Path(source_dir) / filename
            if candidate.is_file():
                return candidate.read_bytes()
            raise ValueError(f"Original PDF not found in source directory: {filename}")
        if archive_path:
            with zipfile.ZipFile(archive_path) as archive:
                entry = result.get("archive_entry")
                if entry:
                    if archive.getinfo(entry).file_size > 100 * 1024 * 1024:
                        raise ValueError("Source PDF exceeds the 100 MiB review limit")
                    return archive.read(entry)
                matches = [archive.read(item) for item in archive.infolist()
                           if not item.is_dir() and item.filename.lower().endswith(".pdf") and item.file_size <= 100 * 1024 * 1024]
                matches = [raw for raw in matches if sha256(raw) == result.get("sha256")]
                if not matches:
                    raise ValueError("Original PDF SHA-256 not found in source ZIP")
                return matches[0]
        # Reader sessions keep original source.pdf alongside review.json.
        filename = payload.get("source_file")
        if filename and Path(filename).name == filename:
            candidate = result_path.parent / filename
            if candidate.is_file():
                return candidate.read_bytes()
        return None
    return load


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Persist predictions in a pending annotation queue")
    collect.add_argument("--result", type=Path, required=True)
    collect.add_argument("--output-dir", type=Path, default=PRIVATE / "queue")
    collect.add_argument("--run-id", help="Optional explicit run identity; reruns preserve existing corrections")
    collect.add_argument("--source-dir", type=Path)
    collect.add_argument("--source-zip", type=Path)
    template = commands.add_parser("template", help="Create an empty approval form without copying predictions")
    template.add_argument("--record", type=Path, required=True)
    template.add_argument("--output", type=Path)
    approve = commands.add_parser("approve", help="Import reviewed values after checking original PDF and page hashes")
    approve.add_argument("--record", type=Path, required=True)
    approve.add_argument("--approval-file", type=Path, required=True)
    approve.add_argument("--reviewer", required=True, help="Name of the human who visually reviewed every source page")
    source = approve.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-pdf", type=Path)
    source.add_argument("--source-zip", type=Path)
    export = commands.add_parser("export", help="Export approved labels in benchmark_vision schema")
    export.add_argument("--record", type=Path, action="append", required=True)
    export.add_argument("--output", type=Path, default=PRIVATE / "approved-labels.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            payload = read_json(args.result)
            paths = collect_queue(payload, _private_output(args.output_dir), run_id=args.run_id,
                                  source_loader=source_loader(args, payload, args.result))
            result = dict(queue_records=[str(path) for path in paths], review_status="pending", training_performed=False)
        elif args.command == "template":
            target = _private_output(args.output or PRIVATE / "approval-forms" / (args.record.stem + ".json"))
            write_json(target, approval_template(read_json(args.record)), exclusive=True)
            result = dict(approval_form=str(target), instruction="Visually inspect all original pages, enter exact expected values, then explicitly approve.")
        elif args.command == "approve":
            _private_output(args.record)
            source_pdf = args.source_pdf
            if args.source_zip:
                record = read_json(args.record)
                with zipfile.ZipFile(args.source_zip) as archive:
                    entry = record["document"].get("archive_entry")
                    if not entry:
                        raise ValueError("Queue has no archive_entry; provide --source-pdf")
                    if archive.getinfo(entry).file_size > 100 * 1024 * 1024:
                        raise ValueError("Source PDF exceeds the 100 MiB review limit")
                    source_pdf = archive.read(entry)
            record = approve_record(args.record, read_json(args.approval_file), reviewer=args.reviewer, source_pdf=source_pdf)
            result = dict(record=str(args.record), review_status=record["review_status"], reviewer=record["human_review"]["reviewer"], training_performed=False)
        else:
            labels = export_gold([read_json(path) for path in args.record])
            target = _private_output(args.output)
            # Existing stronger labels are never silently replaced.
            if target.exists() and read_json(target) != labels:
                raise ValueError("Approved label output already exists with different data; choose a new output filename")
            if not target.exists():
                write_json(target, labels, exclusive=True)
            result = dict(approved_label_file=str(target), approved_documents=len(labels["documents"]), training_performed=False)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
