# Private PDF-to-VLM dataset

The October 1, 2026 dataset request prepares image/JSON examples from the retained ZIP. It does not run training or change model weights. The first saved dataset contains assistant visual transcriptions pending human review; these are not approved reference labels.

`build_vlm_dataset.py` inventories the live archive, preserves original PDF bytes under SHA-256 filenames, renders full RGB pages at 216 DPI, retains native text separately, and binds candidate targets to source-page and rendered-image hashes. Targets follow the existing `PAGE_EXTRACTION_SCHEMA` and preserve printed raw strings independently of catalog matching. Missing values remain null; uncertain handwriting or identifier roles remain explicit.

Prepare and build a new dataset after candidate annotations exist:

```powershell
& .\.venv\Scripts\python.exe build_vlm_dataset.py prepare
& .\.venv\Scripts\python.exe build_vlm_dataset.py build --output-dir output/vlm-dataset
& .\.venv\Scripts\python.exe build_vlm_dataset.py validate --output-dir output/vlm-dataset
& .\.venv\Scripts\python.exe build_vlm_review.py --dataset-dir output/vlm-dataset --output output/vlm-dataset/review.html
```

Use a new output directory for subsequent builds. The builder refuses to replace a populated dataset or prior release. Candidate annotation files belong in the ignored `output/vlm-dataset-work/annotations/` directory and contain:

```json
{
  "source_sha256": "<exact original PDF SHA-256>",
  "page": 1,
  "image_sha256": "<exact rendered PNG SHA-256>",
  "layout_family": "<observed buyer or template family>",
  "annotation_origin": "codex_visual_transcription",
  "review_status": "pending_human_review",
  "page_status": "candidate",
  "target": "<complete PAGE_EXTRACTION_SCHEMA object>",
  "notes": []
}
```

The example above describes the envelope; `target` must be an object, not the illustrative string. `unresolved` and `non_extractable` page statuses require a null target and produce no supervised draft example. Every source page stays in the manifest, including failed or unlabeled pages. Terms and continuation pages can be complete zero-row targets.

The dataset README explains the portable JSONL messages and image paths. Full audit views preserve all page occurrences. Deduplicated views retain one example per exact image and all source references. Proposed splits keep exact repeated pages, conservative visual near-duplicate candidates, and declared layout families together. A small corpus can have empty validation/test splits; counts do not establish extraction accuracy or generalization.

Open `review.html` in a browser. It embeds the page images, so it also works offline. Review each original page, correct every target field, enter the actual human reviewer name, and save the page review. Every page in a document must receive a decision before that document can be released. Download a progress backup to retain incomplete work, or explicitly select the release declaration and download complete document reviews. The browser cannot prove that a person read the source; the release is a named human declaration bound to the retained evidence.

Copy the downloaded review bundle to `output/vlm-dataset/review/completed/` and run:

```powershell
& .\.venv\Scripts\python.exe build_vlm_dataset.py export-approved --output-dir output/vlm-dataset --approved-output output/vlm-dataset-approved-release
```

The exporter validates document completion, reviewer and time, source/image/target hashes, the complete corrected schema, and duplicate consistency before writing any released examples. It refuses pending templates and incomplete or altered evidence. Existing evaluation labels are preserved separately and are not automatically released for training. Training requires its own later decision after sufficient approved data and held-out evaluation exist.

Keep source PDFs, images, native text, candidate labels, review corrections, JSONL files, and dataset ZIPs inside ignored `data/` or `output/` directories. Only the reusable builder, review generator, tests, and general documentation belong in Git.
