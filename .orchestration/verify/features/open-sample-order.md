# Open a sample order
slug: open-sample-order   surface: web UI   status: unproven
## Purpose
A first-time user opens one of the five fictional sample orders to see its lines sorted into Sure, Check and Ignored lines.
## How to reach it
Open the start page `/poc-demo`; the sample orders are under Recent orders (and under the collapsed "Try a sample order").
## Setup
Fresh database (`-FreshDatabase`).
## How to drive it
1. Open `http://127.0.0.1:<port>/poc-demo`; wait for "Recent orders".
2. Click the card "Order with every kind of line".
3. If asked, enter `Synthetic QA (Claude simulation)` and click "Start reviewing".
4. Read the three tab labels and counts.
## Proof
Visible end state: tabs "Sure", "Check", "Ignored lines" with non-zero counts; header "0 of N done". (Exact counts UNVERIFIED for this sample; read them on first drive and pin them here.)
Side effects: none (read-only; all requests in the network log are GET).
## Evidence to capture
Screenshots at steps 1 and 4; network list showing only GETs.
## Cleanup
none
## Pointers
scripts/poc-demo.html:10-14; scripts/poc-demo-ui.js; web/local-reader/workflow.js:785; docs/poc-demo-runbook.md:18, 23.
## Demo caption (optional)
Pick a sample order: every printed line lands in one of three tabs, Sure, Check or Ignored, so you know where to look first.
