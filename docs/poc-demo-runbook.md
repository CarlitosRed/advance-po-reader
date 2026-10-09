# Local POC demo — free mode

For Carlos · Wednesday, October 7, 2026 (counts updated for the landing head). **153 fictional products; fake extraction; every decision is explicit.** This mode needs no API key, dotenv file, login or hosting.

**Prerequisites:** open a **NORMAL PowerShell** (Start menu → PowerShell, **NOT Run as administrator**). PostgreSQL refuses administrator sessions; the launcher stops before setup if elevated. This desk has Python 3.12, pinned `.venv-backend` dependencies and PostgreSQL 17 binaries. Port 8020 must be free. The restricted agent sandbox cannot start PostgreSQL.

**Start:** paste both lines in PowerShell and leave that terminal open.

```powershell
Set-Location -LiteralPath 'C:\Users\carlo\dev\advance-po-reader.worktrees\poc-demo'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1
```

The execution-policy bypass applies only to that one process; no Windows setting changes.

Wait for “Free POC ready”, then open [the local demo](http://127.0.0.1:8020/poc-demo) (a second copy can use `-Port 8021`). Stop with **Ctrl+C**. Restart preserves earlier runs/decisions and creates fresh pending cases in the owned database.

**Phone flow.** The page has one big drop area (**Choose a PDF or photo**), a **Recent orders** list with progress such as “9 of 14 reviewed”, and a collapsed **Try a sample order** section. Free mode recognizes only the five samples (plus their PDF/PNG/JPG files, offered under the same section); any other file gets a plain message. Open an order: the first time, enter your name once (it is remembered on this device; **Change** is at the top). The review page has **three tabs**: **Sure** (the printed code matches exactly one product; look at the picture, tap the check mark, or **Confirm all visible**), **Check** (each line says why it is not certain; **Confirm** the best guess, **This one instead**, **Change product** / **Find the product**, or **Not a product**) and **Ignored lines** (totals, notes and charges the app ignored; optional). **Not right? Check it** moves a Sure line to Check. Each card shows the printed line as a picture (**Enlarge source** shows the page), Code, Description, Quantity and Price (Price is hidden when the order prints none). Technical details (SHA-256, run id, history) sit under **Details**; the reason is optional (**Add a note**) and defaults to “Reviewed in the demo”.

1. **Order with clear codes** (`demo-three-tiers`; **PO-04**): one clear code, one similar code, one ambiguous line. The clear line starts in **Sure**; the similar and ambiguous lines start in **Check**. Nothing is saved until you confirm it.
2. **Order with codes inside descriptions** (`demo-description`; **PO-01**): a code embedded in a description, a similar product and an ambiguous line, all in **Check**. Optionally open **Something misread? Correct a value**, choose **Quantity**, enter `002.50`, **Save correction**: the card shows the original `002.00` and your value, and the answer needs your confirmation again. For the ambiguous line use **Pick an existing product**, search `POC-0101`, **Choose**, then confirm it.
3. **Order with unclear lines** (`demo-three-answers`; **PO-23**): three lines that need your answer. Use **Pick an existing product** (search `POC-0101`, **Choose**, then confirm it), **It’s a new product** with a unique invented code such as `POC-DEMO-NEW-01`, then confirm it, and **Not a product**.
4. **Every kind of line** (`demo-all-tabs`): nine lines that fill all three tabs, to try **Confirm all visible** in **Sure**, the **Check** answers, and the optional **Ignored lines**.
5. **Why each line needs a look** (`demo-reasons`): eleven lines whose **Check** cards each show a different plain-words reason.

An answer that only chooses or adds a product is a binding; it still needs your confirmation. When every line is answered, the summary shows “N products confirmed” and a table (ID, Product, Qty, Price, with the printed description underneath). **Finish review** locks the review; **Download as spreadsheet** saves a UTF-8 CSV with a byte-order mark (BOM, so Excel shows accents correctly) and seven headers: `product_id`, `product`, `description`, `quantity`, `unit`, `quantity_as_printed`, `price`. `quantity` is the standard two-decimal number (`2.00`) and is left blank when the printed text is ambiguous; `quantity_as_printed` always keeps the original printed text (`002.00`, `1,000`), so the source evidence is never lost. Reload to show the saved review. Unprinted values stay blank; nothing is invented.

**Private catalog (optional):** `start-poc-demo.ps1 -CatalogFile C:\private\catalog.json -FreshDatabase` loads your own catalog (same shape as `fixtures/poc-demo/catalog.json`) instead of the 153 invented products; the sample lines then use products from that file.
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

## Live mode (T-019, needs your key; off by default)

Free mode above stays the default and is unchanged. Live mode lets the OpenAI model (default `gpt-6-luna`, setting `PO_BACKEND_EXTRACTION_MODEL`) read a real purchase order, then you review it in the same phone screens. **Cost is yours: a few cents per document; nothing is sent until you tap Send.**

1. **Key, once, by you.** In this desk's ignored `.env.backend` (never in chat) put `OPENAI_API_KEY=...` and a private `PO_BACKEND_LOCAL_API_TOKEN=` of 16+ characters (not the shared default). Optional there: `PO_BACKEND_EXTRACTION_MODEL=`.
2. **Rehearse for free.** `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -LiveRehearsal -Port 8021` shows the live screens against a fake OpenAI (no key, no network).
3. **Probe once (a few cents).** `.\.venv-backend\Scripts\python.exe scripts\poc-probe-live.py --confirm` sends one fictional one-page PDF through the same adapter and prints model, success or failure state, latency, tokens, estimated cost and whether the model accepted PDF file input. Without `--confirm` it refuses. OpenAI's page lists gpt-6-luna inputs as text and image, so if it says `probably_no`, run it with `--images`; if that works, set `PO_POC_PDF_AS_IMAGES=1` before starting (a one-page PDF is then sent as a page image; multi-page PDFs need backend page merging and stop with a plain message).
4. **Go live.** `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -Live -Port 8021` (add `-CatalogFile C:\private\catalog.json -FreshDatabase` for your catalog). It refuses, starting nothing, unless the key and a private token are present, sets live processing for that process only and a 180 s provider timeout if unset. Upload a PDF or photo: the page asks "This sends this document to OpenAI. Cost is usually a few cents. Send it?" and only **Send** submits an authorization tied to that file's hash. If the same file already has a finished reading (completed or partial), choosing it again reopens that reading and nothing is sent or charged again. If the earlier try failed, timed out (the outcome is unknown and may already have been charged) or was cancelled, choosing the file again and tapping **Send** (or `poc-run-live-file.py --confirm`) sends it again and can cost again: check your OpenAI usage first, because each new Send is your own new confirmation.
5. **Spend cap.** The page shows the running count. The backend stores token usage, not prices, so by default the cap counts runs: `PO_POC_MAX_LIVE_RUNS` (default 5). Set `PO_POC_INPUT_USD_PER_MTOK` and `PO_POC_OUTPUT_USD_PER_MTOK` (your current prices, finite and above zero; anything else is ignored) to also cap by estimated dollars: `PO_POC_SPEND_CAP_USD` (default 3; a value that is not a finite number above zero falls back to 3). The run limit stays on in both modes, and an attempt with no recorded usage (a timeout or server error) is counted at a deliberately high estimate, not as zero. At the cap new live uploads are refused with a plain message; raise the limit and restart. A fresh database (`-FreshDatabase`) starts the count at zero.
6. **Stop.** Press Ctrl+C in the terminal. Live data stays in this desk's ignored `data/`; delete nothing you want to keep.
