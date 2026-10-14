# Confirm a Sure line
slug: confirm-sure-line   surface: web UI   status: proven at 0e761fb on 2026-10-14
## Purpose
The reviewer confirms that a line whose printed code matches exactly one product is that product.
## How to reach it
Open the start page `/poc-demo`, choose **Order with clear codes** under Recent orders, enter your name once and choose **Start reviewing**; the **Sure** tab is open.
## Setup
A fresh database (`-FreshDatabase`) so the sample order shows `0 of 3 reviewed`. The free demo gives the same bytes the same run, so a second drive on the same database finds Line 1 already confirmed.
## How to drive it
1. Open `http://127.0.0.1:<port>/poc-demo`; wait for the heading "Upload a purchase order" and "Order with clear codes · 0 of 3 reviewed".
2. Click the Recent orders card "Order with clear codes" (scroll it into view; the link with the same name under "Try a sample order" is collapsed and not clickable).
3. If "Who is reviewing?" shows: click the "Your name" field, type `Synthetic QA (Claude simulation)`, click "Start reviewing". Wait for "3 lines left to check · 0 of 3 done".
4. Scroll down until card "Line 1 · POC-0101" shows its picture; find the button "This is the product" (it appears in the tree only after the picture loads) and click it.
5. Wait for toast "Confirmed." and header "2 lines left to check · 1 of 3 done".
6. Navigate back to `/poc-demo`; read the card text.
## Proof
Visible end state: header "1 of 3 done", Sure tab "all done" with "Everything in this tab is done."; after reload the start page lists "Order with clear codes · 1 of 3 reviewed".
Side effects: browser network log shows `POST /runs/<run id>/reviews -> 201 Created`; read-only query `select row_id, action, reviewer, reason from review_events order by event_sequence` returns exactly one row: `p1-line-1 | approve | Synthetic QA (Claude simulation) | Reviewed in the demo`.
## Evidence to capture
Screenshots at steps 1, 3, 4, 5, 6; network request list and console messages after step 5; the review_events query output; provider_attempts summary (`select model, synthetic, state, count(*) from provider_attempts group by 1,2,3`) to show no live attempt.
## Cleanup
The approval row stays in the throwaway demo database; it goes with `data\poc-demo` at teardown (or is left behind by the next `-FreshDatabase`).
## Pointers
Button: web/local-reader/workflow.js:730. Review write route: backend/app.py:409. Sample case: fixtures/poc-demo/cases.json (`demo-three-tiers`); runbook docs/poc-demo-runbook.md:20.
## Demo caption (optional)
Open a sample order, look at the printed line next to the product it matched, and tap "This is the product". The answer is saved with your name, and the order now shows 1 of 3 reviewed.
