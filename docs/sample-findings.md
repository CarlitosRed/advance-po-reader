# Sample findings (publication copy)

Seven original PDFs / eight pages were independently inspected. All have native text layers; image headers can still contain omitted fields. Originals, contact details, private row labels, email provenance and full findings remain in the local publication backup and ignored data/output directories.

Observed failure modes include supplier versus delivery address confusion, blank delivery sections, filenames differing from printed order numbers, image-only phone text, whitespace changes in identifiers and contact strings, international address conventions, and currency differing from shipping country. Preserve every raw observation and assign address roles only with evidence.

Original-byte hashes and actual sizes are checked against the private source manifest. Provider attachment sizes differed from actual bytes, so raw-file integrity uses downloaded sizes. Some PDFs have malformed font metadata warnings; successful extraction on these samples does not establish general OCR reliability.

The baseline recovered 23 product rows across the seven development PDFs. These files also seeded the provisional catalog, so this is regression evidence. Current vision results and limits are in framework-first-results.md. Training remains deferred.
