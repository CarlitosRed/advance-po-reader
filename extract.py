"""Local, evidence-first PDF extraction baseline; no network or OCR calls."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber
from pypdf import PdfReader
import pypdfium2 as pdfium

POSTCODE = re.compile(r"\b(?:GIR\s?0AA|[A-Z]{1,2}[0-9][A-Z0-9]?\s?[0-9][A-Z]{2})\b", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+44\s*(?:\(0\)\s*)?|0)(?:[\d ()-]{8,20})\d(?!\w)")
COUNTRY = re.compile(r"\b(?:United Kingdom|Great Britain|England|Scotland|Wales|Northern Ireland|Ireland|UK|GB|United States|USA)\b", re.I)
EIRCODE = re.compile(r"\b[A-Z][0-9]{2}\s?[A-Z0-9]{4}\b", re.I)


def candidates(text):
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        for field, pattern in (("postcode", POSTCODE), ("eircode", EIRCODE), ("phone", PHONE), ("country", COUNTRY)):
            for match in pattern.finditer(line):
                result.append({"field": field, "raw_value": match.group(), "line": number,
                               "evidence": line, "status": "review_needed", "address_role": None})
    return result


def extract(path, output, render=False):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    folder = output / (path.stem + "-" + digest[:8])
    folder.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(path)
    result = {"filename": path.name, "sha256": digest, "size_bytes": len(raw),
              "status": "review_needed", "pages": [],
              "warnings": ["Candidates are not assigned shipping/billing fields; review page evidence."]}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            layout = page.extract_text(layout=True) or ""
            independent = reader.pages[i].extract_text() or ""
            classification = "text_layer_present" if text.strip() else "no_extractable_text_ocr_review_required"
            entry = {"page": i + 1, "classification": classification,
                     "width": page.width, "height": page.height,
                     "character_count": len(page.chars), "image_count": len(page.images),
                     "text": text, "layout_text": layout, "pypdf_text": independent,
                     "words": page.extract_words(), "candidates": candidates(text)}
            if not text.strip():
                result["warnings"].append(f"Page {i+1}: OCR required or unsupported text encoding; no inferred fields.")
            if page.images:
                result["warnings"].append(f"Page {i+1}: embedded images may contain text absent from extraction; visual/OCR review required.")
            result["pages"].append(entry)
            (folder / f"page-{i+1:03}.txt").write_text(text, encoding="utf-8")
            (folder / f"page-{i+1:03}-layout.txt").write_text(layout, encoding="utf-8")
    if render:
        document = pdfium.PdfDocument(path)
        for i in range(len(document)):
            page = document[i]
            bitmap = page.render(scale=1.5)
            bitmap.to_pil().save(folder / f"page-{i+1:03}.png")
            bitmap.close()
            page.close()
        document.close()
    (folder / "extraction.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"filename": path.name, "sha256": digest, "pages": len(result["pages"]),
            "classifications": [p["classification"] for p in result["pages"]],
            "candidate_count": sum(len(p["candidates"]) for p in result["pages"]),
            "output": str(folder), "status": "review_needed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path("data/originals"))
    parser.add_argument("--output", type=Path, default=Path("output/extractions"))
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    files = sorted(args.input.glob("*.pdf")) if args.input.is_dir() else [args.input]
    if not files:
        parser.error("No PDF files found")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for path in files:
        try:
            entry = extract(path, args.output, args.render)
        except Exception as error:
            entry = {"filename": path.name, "status": "failed", "error": str(error)}
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=True))
    (args.output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if any(r["status"] == "failed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
