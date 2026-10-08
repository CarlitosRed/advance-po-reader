# Glossary: the words used in these pages

[Back to the map](README.md)

Plain meanings, in alphabetical order. All examples use invented data.

| Word | What it means here |
| --- | --- |
| **Alias** | Another code or name that a catalog product is also known by. Example: product `ACME-1001` might have the alias `HNG-50` (the code a customer prints). An alias is stored next to the product. It only counts when it is looked up with the same kind of label it was saved under. |
| **Approval (person approves)** | A person pressed the confirm button for one line. The app never approves a product by itself, whatever the tier. |
| **Audit trail** | The saved list of what each person decided, when, and why. Stored as "review events". The database refuses to change or delete them once written. |
| **Candidate** | A catalog product the app proposes for a line. A line can have none, one, or several. |
| **Catalog** | Our own product list: for each product a code (SKU) and a description. The app only ever suggests products that are in it. |
| **Certain / Probable / Uncertain** | The three confidence tiers. See [the tiers page](04-confidence-tiers.md). Certain still needs a person. |
| **Check (tab)** | The review tab for lines the app is not sure about (Probable and Uncertain tiers). |
| **Continuation line** | A second printed line that only continues the description of the line above it ("with screws included"). It is shown together with that product and is not a product of its own. |
| **CSV** | A plain table file that opens in Excel. The "Download as spreadsheet" button makes one. |
| **Evidence** | The exact spot on the page (a rectangle) where a value was read. Every row and every value must point to one. |
| **Gate** | One decision point in the flow. Each page of this folder explains one gate. |
| **Hash (SHA-256)** | A fingerprint of a file. If one byte changes, the fingerprint changes. Used to prove the file that was approved for sending is the file that was sent. |
| **Ignored lines / Not products (tab)** | The review tab for totals, notes, charges, taxes and lines a person marked "not a product". In version 1 it is named "Ignored lines" and is optional (before PR #21 it was named "Not products"). |
| **Model** | The AI program that reads the PDF page and writes down what is printed. It does not choose catalog products. |
| **Normalized code** | A code with everything except letters and digits removed and capitals only. `acme-1001` and `ACME 1001` both become `ACME1001`. Used to find near-identical spellings. |
| **PR (pull request)** | A proposed change to the code, reviewed before it is merged. "PR #19" is change number 19. |
| **Prompt** | The written instructions sent to the model together with the PDF. |
| **Row** | One printed line of the order, as the model wrote it down. |
| **Row kind / row role** | What kind of line it is: product, charge, tax, subtotal, total, note or unknown (kind), and how it relates to the others: product item, continuation, document detail or unknown (role). |
| **Run** | One reading of one file. It has a state (created, processing, completed, partial, failed) and, later, a review state. |
| **SKU** | The catalog's code for a product. In this project the catalog key is our own product code. |
| **Snapshot** | A cropped picture of the page around one line, with the line outlined, so the reviewer can compare with the printed original. |
| **Strict check** | The validation of the model's answer against a long list of rules. One broken rule rejects the whole answer. |
| **Tier** | A confidence level given to a line: Certain, Probable or Uncertain. It decides which tab the line starts in. |
| **Trigram (text similarity)** | A way to compare two pieces of text by their three-letter pieces. "Close but not equal" scores high. Needs a database add-on called `pg_trgm`. |
| **Vendor prefix** | Letters printed in front of a code that name the supplier. Example: `ZED ACME-1001` is `ACME-1001` with the prefix `ZED`. |
