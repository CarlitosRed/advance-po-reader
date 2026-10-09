# Local website verification — October 2, 2026

This records website checkpoint `d01b2ca`. The later agent/demo phase and
`0005_review_sequence` migration are documented in
[local-agent-demo.md](local-agent-demo.md), including 245 backend, 135 Gate A
and 20 agent checks, actual STDIO verification and offline browser handoff.

This worktree extends the verified backend; these results describe local
implementation behavior and do not measure model extraction accuracy.

| Check | Actual result | Scope |
| --- | --- | --- |
| Full backend suite via scripts/test-backend.ps1 | 234 passed, no skips or warnings | Includes 13 new session/catalog/proposal/provenance tests and the preserved 221 backend checks; real PostgreSQL and mocked provider transport. |
| Preserved Gate A suite via the same script | 135 passed, no skips or warnings | Separate website-owned test database; original service/data unchanged. |
| Final focused website/coordinate rerun | 15 passed, no skips or warnings | The 13 website tests plus two added rotated-PDF/EXIF-photo coordinate tests after the final preview changes. |
| Alembic metadata check | No new upgrade operations | Actual website database at 0004_website_catalog. |
| Python dependency check | No broken requirements | This worktree's isolated Python environment. |
| JavaScript syntax | Passed | Finished static frontend. |
| Real source import | 3 catalogs, 2,720 products, 33 PDFs, 45 pages | Staging database/archive hashes checked; all PDFs decoded locally, no legacy VLM targets imported. |
| Source-record parity | 42,996 attributes, 2,570 detail sections; no inferred real aliases | Counts read back from PostgreSQL; namespace product counts 2,380 / 160 / 180. |

Browser checks exercised a fictional PDF through the actual local backend:
source page/crop, explicit approval, literal correction from 2 to 002.50 with
original unchanged, reopened approval, manual catalog search/proposal,
candidate selection, charge/total acknowledgement, reviewed-product summary,
review resolution, and reload preserving the selected run and audit.
The sample is clearly labeled fictional; its simulated QA reviewer is not
a customer review or a training/gold label.

Additional browser checks and private evidence are recorded in
`output/website-verification/browser-qa.json`. Screenshots under
`output/website-verification/` contain fictional source data only.
Private customer document/corpus receipts remain ignored.

The three real catalog choices and source details were exercised, and one
supplied PDF was saved with no extracted rows, navigated to its third page,
and enlarged for local inspection. Returning from the fictional sample clears
its demo catalog; choosing a file or library document without a real catalog
shows an explicit selection error. Read-only browser tools preserve the
distinction between the selected catalog and the last opened run's catalog.

Layouts at widths 375, 768, 1024 and 1440 were checked without horizontal
overflow on the exercised screens. Keyboard Tab reached the visible skip
link, and the final browser console had no error entries. Viewport overrides
were reset. A 200% browser-zoom check remains unverified because the supported
shortcut did not change the viewport or device pixel ratio. Reduced-motion
CSS is present; an OS-preference simulation was not performed.

No live model request, API key setup, provider-performance measurement,
training, real cart write or deployment occurred. Real catalog integration
does not establish a PDF's country/vendor or an orderable unit. Local file
validation/preview does not establish purchase-order classification or
extraction fidelity. Real API/provider behavior and production authentication
remain later verification.
