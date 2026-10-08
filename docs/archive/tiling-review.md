# Tiling article review and retained ideas

Reviewed October 1, 2026: [Aman Kumar's article](https://medium.com/@amankrr/how-building-a-pdf-viewer-taught-me-more-than-any-classroom-ever-could-fdebe41b8482), published December 7, 2025.

The article discusses rendering only visible rectangular page regions, with caching, cleanup and optional nearby prefetching. Those are useful viewer performance ideas. It contains a simplified inline JavaScript example; no implementation repository is linked in the article. Its example is conceptual, not a verified drop-in PDF.js API call. The numerical memory/latency claims are not benchmarks for this project and have not been adopted as performance promises.

Rendering and extraction are different operations. Tiling can reduce pixel buffer size and improve source review responsiveness. It does not turn PI into PO, verify a product ID, or guarantee OCR accuracy. Text extraction must cover all relevant pages, including off-screen content; it must never depend on which viewer tiles are visible.

## Adopted in logic now

- Reading and interpreting a PDF does not render all its pages by default.
- `po_reader/rendering.py` provides source-region rendering on demand at an explicit resolution, using PDFium's actual crop API.
- Its bounded LRU cache uses document SHA-256, page number, region and scale as its key, so different files or zoom resolutions cannot reuse stale regions.
- Rendering is serialized with a process-wide lock, and PDFium handles are explicitly closed. PDFium is not thread-safe; future parallel rendering should use processes or retain locking.
- A pixel budget prevents a full high-resolution page from silently allocating an oversized bitmap. Cache accounting conservatively budgets uncompressed RGBA pixels.
- Source bounding boxes remain in PDF coordinates, independently of rendering scale.

## Reserved for the UI/UX stage

Viewport/tile planning, zoom/device-pixel-ratio/rotation-aware transforms, cancellation of obsolete tasks, overlapping seams, low-resolution page placeholders, text/annotation layers, and measured tile size/prefetch budgets belong in the later viewer. Add rotation/crop-box fixtures before using region rendering on arbitrary rotated pages. Avoid adding hundreds of cached pages by default.

OCR region processing can reuse on-demand rendering, but OCR tiles need overlap and word/row deduplication. Cutting through a product code or table row can reduce accuracy. Do not OCR only visible tiles. OCR has not been implemented in this logic version.

Primary implementation references: [PDFium Python API](https://pypdfium2.readthedocs.io/en/stable/python_api.html) and [PDF.js page API](https://mozilla.github.io/pdf.js/api/draft/module-pdfjsLib-PDFPageProxy.html). PDF.js uses viewport/canvas rendering parameters, rather than the article's simplified x/y/width/height signature.
