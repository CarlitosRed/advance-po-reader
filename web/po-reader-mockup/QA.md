# Mockup v2 verification — October 3, 2026

The verification applies to the static T-005 sample interface. It uses the existing synthetic purchase order and sample catalog only. No customer PO, backend, provider, or external catalog is part of this check.

The browser suite is `tests/mockup-v2.cjs`, run from the repository root with `node`. It starts a temporary loopback static server, uses installed Microsoft Edge with the bundled Playwright runtime, and closes both when done.

Verified behavior:

- All seven lines start pending: zero reviewed, zero accepted. Certain suggestions are pre-selected but need individual explicit taps.
- Cancellation remains cancelled after the simulated reading timer expires.
- Empty, oversized, unsupported, and signature-invalid sample uploads are rejected. The existing sample PDF and PNG photo can be selected and previewed locally; Escape closes the dialog and restores focus.
- Catalog selection, source previews, quantity edits, and summary navigation do not accept products.
- Blank, zero, negative, nonnumeric, exponent, oversized, and over-precision quantities are rejected. Valid quantities retain their ordering unit; source observations remain unchanged.
- The three uncertain answers work independently and together: choose an existing product, add a session-local sample product, or preserve a non-product in Ignored.
- Blank new-product fields and duplicate codes are rejected. A newly reviewed sample product is searchable from another line during the same session.
- Ignored source text and snippets remain inspectable in collapsed details, including shipping charges. Reopening a line revokes its earlier decision.
- All source lines require a decision to unlock the final summary. The separate final tap approves only the reviewed product decisions. Subsequent edits revoke final approval.
- Review, editor, and final views fit 320, 390, 768, and 1440 CSS-pixel widths without horizontal overflow.
- Browser monitoring rejects external requests, fetch/XHR, and WebSockets. No API/external requests or JavaScript exceptions were observed.

The final suite passed 13 substantive checks, with zero accepted product lines before the final tap and six accepted product lines in the mixed-answer QA scenario afterward. The pack-unit correction `1.250 PK` was preserved literally while the source remained `1 PK`. The suite's console output is the source of truth for the completed pass.

The independent source review checked immutable observations, separate drafts and decisions, cancellation tokens, conditional approved-state copy, 44-pixel controls, visible focus styles, native dialogs, and reduced-motion CSS. Opening an editor scrolls the active field into view on phones. No screen-reader or real device test was performed.

Before screenshots were captured from `origin/main` commit `4bf061b06d12bb229a771705153a58f9b2d88a7b`. After screenshots come from the browser suite in this branch. Both use a 390 × 844 phone viewport and a 1440 × 1000 desktop viewport. The [screenshot gallery](../../docs/mockup-v2/README.md) includes an uncertain editor and final approved sample.

These results verify sample interactions and layout. They do not measure extraction quality, live catalog integration, persistent product creation, production audit events, or order placement.
