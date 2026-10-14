# Upload a PDF or photo
slug: upload-own-file   surface: web UI   status: unproven (blocked here: the built-in browser pane has no file-chooser control; Playwright not installed)
## Purpose
The user adds their own order file; in free mode only the five sample files are recognized and anything else gets a plain message.
## How to reach it
Open `/poc-demo`; the big drop area "Choose a PDF or photo".
## Setup
A sample file served by the demo itself: `GET /poc-demo/files/demo-three-tiers.png` (scripts/poc-demo.py:78-82), saved into the run folder. For the negative case, any small invented PDF in `fixtures/` of the verify folder (never a real order).
## How to drive it
1. Choose the sample PNG in "Choose a PDF or photo".
2. Wait for the order to open (or for its existing run to reopen).
3. Negative: choose an invented PDF; expect the message "This free preview can only read the sample orders. Open one under "Try a sample order"."
## Proof
Visible end state: step 2 opens the review for that sample; step 3 shows the plain refusal.
Side effects: `POST /documents` 201 for the accepted upload (source_documents row, read-only count before/after); no new provider_attempts row with a model other than `poc-fixed-json-v1`.
## Evidence to capture
Screenshots at each step; network list; source_documents and provider_attempts counts before/after.
## Cleanup
Uploaded rows stay in the throwaway DB.
## Pointers
scripts/poc-demo.html:10; scripts/poc-demo-ui.js:12, 102; backend/app.py:267; free-runs-only guard scripts/poc_demo_support.py:63-79.
## Demo caption (optional)
Drop a PDF or a photo of an order. The free preview reads only its sample orders and says so plainly for anything else.
