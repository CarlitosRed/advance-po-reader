"""Prepare, validate and explicitly release private VLM dataset artifacts."""
import argparse
import json
from pathlib import Path
import sys

from po_reader.vlm_dataset import build, export_approved, prepare, validate_dataset


def private_output(path):
    """CLI-created corpus artifacts must stay under the project's ignored output/."""
    private_root = Path(__file__).resolve().parent / "output"
    resolved = Path(path).resolve()
    if resolved == private_root or private_root in resolved.parents:
        return resolved
    raise ValueError("Private dataset/work/release paths must be inside this project's ignored output/ directory")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "validate", "export-approved"))
    parser.add_argument("--zip", dest="zip_path", type=Path, default=Path("data/corpora/full-data-set.zip"))
    parser.add_argument("--work-dir", type=Path, default=Path("output/vlm-dataset-work"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/vlm-dataset"))
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--approved-output", type=Path, default=Path("output/vlm-dataset-approved-release"))
    args = parser.parse_args(argv)
    try:
        args.work_dir = private_output(args.work_dir)
        args.output_dir = private_output(args.output_dir)
        args.approved_output = private_output(args.approved_output)
        if args.command == "prepare":
            result = prepare(args.zip_path, args.work_dir)
            result = dict(inventory=str(args.work_dir / "dataset-inventory.json"), counts=result["counts"])
        elif args.command == "build":
            result = build(args.zip_path, args.work_dir, args.output_dir, args.annotations)
            result = dict(dataset=str(args.output_dir), counts=result["counts"])
        elif args.command == "validate":
            result = validate_dataset(args.output_dir)
        else:
            result = export_approved(args.output_dir, args.reviews or args.output_dir / "review/completed", args.approved_output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Dataset operation stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
