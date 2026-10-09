# Sample findings (publication copy)

> **Historical private-corpus assessment:** These findings describe the earlier local PDF and self-hosted evaluation work only. They are not OpenAI or Apple results and do not establish production accuracy. The source PDFs, private row-level labels and full findings remain outside Git; see [the project goal](../PROJECT_GOAL.md) for the current roadmap and evaluation rules.

Seven original PDFs / eight pages were independently inspected. All have native text layers; image headers can still contain omitted fields. Originals, contact details, private row labels, email provenance and full findings remain in the local publication backup and ignored data/output directories.

Observed failure modes include supplier versus delivery address confusion, blank delivery sections, filenames differing from printed order numbers, image-only phone text, whitespace changes in identifiers and contact strings, international address conventions, and currency differing from shipping country. Preserve every raw observation and assign address roles only with evidence.

Original-byte hashes and actual sizes are checked against the private source manifest. Provider attachment sizes differed from actual bytes, so raw-file integrity uses downloaded sizes. Some PDFs have malformed font metadata warnings; successful extraction on these samples does not establish general OCR reliability.

The baseline recovered 23 product rows across the seven development PDFs. These files also seeded the provisional catalog, so this is regression evidence. Historical vision results and limits are in [the archived first-results report](archive/framework-first-results.md). These findings do not measure the retained native-text CLI (`reader.py`, no provider call) or the FastAPI backend with its server-side OpenAI adapter (`backend/`), which is separate.
