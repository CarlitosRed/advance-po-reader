# Finish the review and download the spreadsheet
slug: finish-and-download   surface: web UI   status: unproven (CSV half blocked here: the built-in browser pane exposes no download capture)
## Purpose
After answering every line, the reviewer locks the review and saves the confirmed products as a CSV for Excel.
## How to reach it
Answer every line of a sample order (for example confirm-sure-line plus answer-check-line on "Order with clear codes"), then open **Summary**.
## Setup
A fresh database and every line of one sample order answered by earlier drives in the same session.
## How to drive it
1. Click "Summary"; wait for "N products confirmed" and the table (ID, Product, Qty, Price).
2. Click "Finish review"; wait for the review to show as locked.
3. Click "Download as spreadsheet"; capture the downloaded `confirmed-products.csv`.
4. Reload; the review stays locked.
## Proof
Visible end state: "Finish review" gone, the summary marked finished; after reload still finished.
Side effects: a review_events row for the resolve action (`saveReview("resolve")`); the CSV file: UTF-8 with BOM, headers `product_id,product,description,quantity,unit,quantity_as_printed,price`, `quantity_as_printed` keeps the printed text. The CSV is built in the browser (Blob), so the file is only observable with a download-capable browser tool.
## Evidence to capture
Screenshots at steps 1, 2, 4; review_events query; the CSV file with size and SHA-256.
## Cleanup
Delete the downloaded CSV from the download folder after copying it into the run folder; DB rows stay in the throwaway DB.
## Pointers
web/local-reader/workflow.js:376-378 (CSV Blob, filename), :420 (Finish review), :422-425 (Download), :437 (resolve); docs/poc-demo-runbook.md:26.
## Demo caption (optional)
When every line is answered, finish the review to lock it and download the confirmed products as a spreadsheet.
