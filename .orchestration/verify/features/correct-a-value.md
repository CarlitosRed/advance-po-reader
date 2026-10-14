# Correct a misread quantity
slug: correct-a-value   surface: web UI   status: unproven
## Purpose
The reviewer fixes a value the reader misread, keeping the original printed text as evidence.
## How to reach it
Open `/poc-demo`, choose **Order with codes inside descriptions**, enter your name if asked, open the **Check** tab.
## Setup
Fresh database.
## How to drive it
1. On the first Check card open "Something misread? Correct a value".
2. Choose "Quantity", enter `002.50`, click "Save correction".
3. Read the card: original `002.00` and the new value; the answer asks for confirmation again.
4. Confirm the line.
## Proof
Visible end state: the card shows both the original `002.00` and `002.50`, and after confirm the line counts as done.
Side effects: review_events row with old_value containing `002.00` and new_value containing `002.50`, then an approve row; read-only query `select action, old_value, new_value from review_events order by event_sequence`.
## Evidence to capture
Screenshots at steps 1, 3, 4; network list; review_events query.
## Cleanup
Rows stay in the throwaway demo DB.
## Pointers
docs/poc-demo-runbook.md:21; backend/app.py:409; correction-order regression note docs/local-agent-demo.md:174-178.
## Demo caption (optional)
If the reader got a number wrong, correct it. The original printed value is kept next to yours, and the line needs your confirmation again.
