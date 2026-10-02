# Mockup verification - October 1, 2026

Verified against the local static preview in the Codex in-app browser, using synthetic documents only.

- Upload: unsupported extension rejected; invalid PDF signature rejected; valid PDF selected; local PDF preview opened; sample-result disclosure visibly distinguishes example decisions from the uploaded file.
- Loading: both official brand marks displayed; staged progress and cancellation affordance present. Reduced-motion styles disable the moving dots and transitions.
- Review: source page and selected row snippet displayed; conflicting product numbers remain visible; blank SKU and zero quantity rejected; product search/selection accepted; missing unit rejected; explicit PK accepted without conversion; non-product delivery note dismissed.
- Cart: unresolved lines remain flagged and absent from ready products; unresolved lines block confirmation; confirmed sample contains 5 product lines, 8 EA and 1 PK; invalid cart quantity immediately blocks confirmation; editing 2 to 2.5 updates the total to 8.5 EA while leaving 1 PK separate; removal and restoration preserve line count; sample confirmation succeeds after resolution.
- Preview dialog: source document opens; Escape closes the native dialog.
- Responsive: review has no horizontal overflow at 375, 768, 1024 and 1440 CSS pixels; upload and cart have no overflow at 375 pixels; no broken images observed. Viewport override reset afterward.
- Browser: no error-level console messages observed during the successful final UI checks.
- Optional WebMCP: 4 tools registered with expected schemas/annotations. Read/start/confirm/dismiss actions update the same state as the UI. Invalid catalog SKU and attempted dismissal of an already matched line reject without changing the staged products.
- Static output: JavaScript syntax passed; referenced HTML assets present; stripped catalog contains 18 ID/name pairs only; all 7 PDF row PNGs present. Synthetic PDF rendered and visually inspected.

Scope: these are interface checks with sample decisions, not an evaluation of reader accuracy, model services, authoritative catalog integration, external cart writes, or production order submission. Reduced-motion behavior was checked in the source styles; OS/browser motion preference and 200% text enlargement were not emulated during this pass.

Review screenshot is stored locally in ignored `tmp/qa/product-review.jpg`.
