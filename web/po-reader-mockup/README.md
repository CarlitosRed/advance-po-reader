# Purchase Order Reader mockup v2

T-005 is a static, phone-first review walkthrough. It uses the existing synthetic purchase order DEMO-1042, its seven rendered line snippets, and the existing 18-product sample catalog. No login, backend, provider calls, or cart integration are needed.

Open `dist/index.html` in a browser, or serve `dist/` with an ordinary local static server. Choose **Try the sample purchase order** to explore the complete flow. A PDF or photo selection also works, but it is local preview only: the following review always uses clearly labeled sample observations and snippets.

For a local browser preview, run `node web/po-reader-mockup/serve.cjs` from the repository root and open `http://127.0.0.1:4315`. The read-only server serves static files only and binds to loopback. Set `MOCKUP_PORT` to change the port.

## Review flow

1. Select one PDF, JPG, PNG, or WebP (25 MB maximum), or use the sample. A cancellable reading simulation follows.
2. **Certain:** three exact-code suggestions start selected, with zero reviewed or accepted lines. Tap **Approve line** on each, or change the product.
3. **Probable:** the roof-rack-clamp suggestion needs confirmation of its printed pack unit. Confirm it, or search for another sample product.
4. **Uncertain:** conflicting codes, a delivery instruction, and a shipping charge each keep their source snippet and exactly three answers: **This is product X**, **New product**, **Not a product**.
5. Catalog selection and editing fields only prepare a draft. **Approve line** saves an existing-product decision. **Add sample product & review line** adds a product to the in-memory sample catalog and records the explicit review. **Not a product** preserves the source in the collapsed **Ignored** section.
6. Review all seven source lines to unlock the final summary, then tap **Approve all reviewed lines**. Editing any decision revokes the full-review approval and reopens that line.

Quantities remain strings in observations and decisions. EA, PK, and BOX totals are separate; the UI never converts packs into individual items. Missing or invalid quantities/units block product review. New product codes must be unique within the sample catalog. Refresh or a new review clears all additions and decisions.

## Verification

Run the focused browser suite from the repository root:

```powershell
node web/po-reader-mockup/tests/mockup-v2.cjs
```

The suite serves only `dist/` over loopback and exercises real controls using the bundled Playwright runtime and installed Edge. Its runtime/browser defaults match this Windows workspace; they can be overridden as documented in the script. It rejects external requests and API transports, checks approval gates and responsive behavior, and captures the after screenshots. See [QA.md](QA.md) and the [before/after evidence](../../docs/mockup-v2/README.md).

## Static boundaries

`sample-catalog.js` is a local script containing the same ID/name pairs as `assets/catalog.json`; using a script lets the demo also open from disk without a catalog fetch. The content security policy includes `connect-src 'none'`. There are no API clients, WebMCP mutation hooks, credentials, remote fonts, storage writes, database writes, or order submission. A chosen file uses a temporary browser object URL that is revoked on cancellation or reset.

The prototype does not extract, match, or validate a real uploaded PO. It does not prove reader accuracy, production readiness, catalog authority, or persistent audit behavior. The displayed confidence tiers are fixed sample scenarios. The probable scenario has a matching product code but needs a human pack-unit decision; the uncertain scenario retains both conflicting source codes.

All existing sample assets were retained unchanged. The old `create-demo-document.py` utility uses the repository's data directory and is outside T-005; do not run it for this workflow. This task does not deploy or modify the existing hosted Site.
