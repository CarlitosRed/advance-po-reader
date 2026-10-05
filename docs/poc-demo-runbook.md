# Local POC demo — free mode

For Carlos · Wednesday, October 7, 2026. **150 fictional products; fake extraction; every decision is explicit.** This mode needs no API key, dotenv file, login or hosting.

**Prerequisites:** open a **NORMAL PowerShell** (Start menu → PowerShell, **NOT Run as administrator**). PostgreSQL refuses administrator sessions; the launcher stops before setup if elevated. This desk has Python 3.12, pinned `.venv-backend` dependencies and PostgreSQL 17 binaries. Port 8020 must be free. The restricted agent sandbox cannot start PostgreSQL.

**Start:** paste both lines in PowerShell and leave that terminal open.

```powershell
Set-Location -LiteralPath 'C:\Users\carlo\dev\advance-po-reader.worktrees\poc-demo'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1
```

The execution-policy bypass applies only to that one process; no Windows setting changes.

Wait for “Free POC ready”, then open [the local demo](http://127.0.0.1:8020/poc-demo) (a second copy can use `-Port 8021`). Stop with **Ctrl+C**. Restart preserves earlier runs/decisions and creates fresh pending cases in the owned database.

**Phone flow (T-018).** The page has one big drop area (**Choose a PDF or photo**), a **Recent orders** list with progress such as “9 of 14 reviewed”, and a collapsed **Try a sample order** section. Free mode recognizes only the three samples (plus their PDF/PNG/JPG files, offered under the same section); any other file gets a plain message. Open an order: the first time, enter your name once (it is remembered on this device; **Change** is at the top). Each line is one card: the printed line as a picture (**Enlarge source** shows the page), Code, Description, Quantity and Price (Price is hidden when the order prints none). Technical details (SHA-256, run id, history) sit under **Details**; the reason is optional (**Add a note**) and defaults to “Reviewed in the demo”.

1. **Order with clear codes** (`demo-three-tiers`; **PO-04**). Line 1 is **Looks right** with the one literal-code match already selected, but it is only saved when you tap **Yes, this one**. Line 2 is also **Looks right** (a normalized-code match): check it, then **Yes, this one**. Line 3 is **Needs your help**: choose **Not a product** (it is a placeholder). The last answer opens the done screen.
2. **Order with codes inside descriptions** (`demo-description`; **PO-01**). Line 1: check the suggestion. Optionally open **Something misread? Correct a value**, choose **Quantity**, enter `002.50`, **Save correction**: the card shows the original `002.00` and your value, and the answer needs **Yes, this one** again. Confirm Line 2; for Line 3 use **Pick an existing product**, search `POC-0101`, **Choose**, then **Yes, this one**.
3. **Order with unclear lines** (`demo-three-answers`; **PO-23**). Line 1: **Pick an existing product** (search `POC-0101`, **Choose**, then **Yes, this one**). Line 2: **It’s a new product** with a unique invented code such as `POC-DEMO-NEW-01`, then **Yes, this one**. Line 3: **Not a product**.

An answer that only chooses or adds a product is a binding; it still needs **Yes, this one**. **Pick another** and **Change my answer** reopen the three answers. When every line has an answer the done screen shows “N products confirmed” and a table (ID, Product, Qty, Price, with the printed description underneath). **Finish review** locks the review; **Download as spreadsheet** saves a UTF-8 CSV (Product ID, Product name, Description, Quantity, Unit, Price). Reload to show the saved review. Unprinted values stay blank; nothing is invented.

**Private catalog (optional):** `start-poc-demo.ps1 -CatalogFile C:\path\outsideepo\catalog.json -FreshDatabase` loads your own catalog (same shape as `fixtures/poc-demo/catalog.json`) instead of the 150 invented products; the sample lines then use products from that file.
Keep the file outside this repository (the loader refuses paths inside it); `seed-poc-demo.py --catalog-file PATH` does the same for seeding, and switching catalogs needs `-FreshDatabase`.

**Reset:** stop with Ctrl+C, then run from the same desk:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -FreshDatabase
```

This preserves all previous databases, files and reviews. With the app stopped, **verify setup** or **seed alone** from the same normal terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -PrepareOnly
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\.venv-backend\Scripts\python.exe scripts\seed-poc-demo.py"
```

Verification exits without keeping the website running. Seeding is idempotent and preserves reviews.

**Limits:** Certain suggests a literal-code match; Probable suggests a normalized-code or description match; Uncertain needs clarification. None means approved. PO-01/04/23 refer privately to source structures; displayed files are invented examples. The 33 originals/45 pages were validated locally; 33 fictional structural cases were dry-run. This proves workflow handling. Model accuracy, source grounding and independent completeness remain unverified. There is no real catalog, pricing/stock guarantee or cart/order action. Step 4 needs Carlos's separate go in this chat and his choice of sources allowed to leave this PC.
