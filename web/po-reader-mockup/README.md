# Purchase Order Reader mockup

Interactive, owner-private Sites prototype for the SmarterCommerce / Werner purchase-order workflow. Source is deliberately contained in this folder, with its own Git history. Reader logic in the parent repository is a separate work stream. The parent baseline inspected during creation was `93a1b5c`.

Open the Site to upload or drop a PDF/photo, or choose **Try a sample purchase order**. The sample exercises exact matches, conflicting product numbers, pack-unit confirmation, a non-product instruction, shipping-charge exclusion, and the cart.

## What works

- One PDF, JPG, PNG, or WebP selection/drop, validated by size, extension and signature; 25 MB maximum. Uploaded files remain local browser object URLs, with a document preview.
- SmarterCommerce and Werner logo loading sequence, cancellation, reduced-motion support.
- Source PDF/page and actual rendered row snippets from a synthetic PO with no customer data.
- SKU/name search across the existing 18-product provisional sample catalog, explicit product/quantity/unit confirmation, non-product dismissal and restoration.
- Matched and confirmed cart lines, quantity changes, removal/restoration, unresolved-line flags, quantities grouped by unit, and simulated cart confirmation.
- Accessible semantic controls, focus/error feedback, browser back navigation, and responsive upload/review/cart views.
- Optional WebMCP actions with the same validation and in-memory state as the interface.

## Prototype boundaries

There is no live extraction in this website yet. Uploading a new document leads to clearly labeled **sample review results**, alongside a separate preview of the user's file. Example rows and snippets are never presented as extracted from the upload. The website does not call the reader CLI, an external AI API, a real store catalog, or a store cart. There are no prices, customer details, checkout, training, or order submission. Browser refresh clears the in-memory session and decisions.

`dist/assets/catalog.json` contains only sample IDs/names. It excludes PDF provenance, emails, addresses and source customer documents. Ordering-unit controls in the mockup are example choices; production support and conversions require the real catalog contract.

## Continue implementation

Connect the reader through an authenticated adapter that maps preserved raw observations and reviewed candidate decisions to the UI states. Replace sample catalog choices with authoritative product/variant keys, ordering rules and availability. Revalidate every confirmed line against the current catalog before sending a cart operation. Preserve source document hash, page, region, raw quantities/units, corrections and idempotency keys. Review decisions must remain observations until approved by a human; no training is authorized.

`create-demo-document.py` rebuilds the synthetic PO, row PNGs and stripped sample catalog using the parent sample catalog. It is a development utility and is not deployed as server code. Normal hosting uses the tracked static `dist/` output with `.openai/hosting.json`.

## Design and asset sources

The requested `npx skills use "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill" --skill "ui-ux-pro-max"` was run and its complete output read. Relative support files were resolved from the emitted temporary supporting directory. Its minimal enterprise style, document-grey/scan-blue palette and accessibility guidance informed this working surface. Marketing-layout recommendations were not suitable for the upload/review task.

Official logos, used without changing their source pixels:

- SmarterCommerce: https://www.smartercommerce.net/images/smartercommerce2022libraries/smartercommerce/assets/sc-logo-black-gotham-topbottom-1.png?sfvrsn=24442ed1_6
- Werner: https://www.prodrivenbrands.com/images/default-source/brand-logos/werner_li_2000x2000x300.jpg?sfvrsn=35102d8d_2

UI icons use Lucide-style outline geometry. Product names remain the provisional labels already in this project.
