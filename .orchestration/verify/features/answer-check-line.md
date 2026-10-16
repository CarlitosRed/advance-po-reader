# Answer a Check line
slug: answer-check-line   surface: web UI   status: unproven
## Purpose
The reviewer resolves lines the app is unsure about: pick an existing product, declare a new product, or mark a line as not a product.
## How to reach it
Open `/poc-demo`, choose **Order with unclear lines**, enter your name if asked; open the **Check** tab.
## Setup
Fresh database. The invented code `POC-DEMO-NEW-01` must not exist yet (fresh DB guarantees it).
## How to drive it
1. Open the order "Order with unclear lines"; open tab "Check" (3 to check).
2. Line A: "Pick an existing product", search `POC-0101`, "Choose", then confirm it.
3. Line B: "It's a new product", enter code `POC-DEMO-NEW-01`, save, then confirm it.
4. Line C: "Not a product".
5. Wait for "3 of 3 done".
## Proof
Visible end state: "0 lines left to check · 3 of 3 done"; the summary shows the confirmed products.
Side effects: review_events gains one row per action (bind/propose plus approve for A and B, a not-a-product decision for C); read with `select row_id, action, reviewer from review_events order by event_sequence`. Exact action names UNVERIFIED: read them on first drive and pin them here.
## Evidence to capture
Screenshot after each step; network list (POST /runs/<id>/reviews 201 per action); review_events query.
## Cleanup
Rows stay in the throwaway demo DB.
## Pointers
docs/poc-demo-runbook.md:22; web/local-reader/workflow.js:746; backend/app.py:409.
## Demo caption (optional)
For a line the app could not match, pick the right product, add a new one, or say it is not a product. Every answer carries your name.
