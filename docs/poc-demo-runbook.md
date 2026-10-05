# Local POC demo — free mode

For Carlos · target Wednesday, October 7, 2026. Everything runs on this PC with a **fictional catalog and fake extraction**. No API key, dotenv file, login or hosting is needed.

**Prerequisites:** Python 3.12, the pinned backend dependencies in this desk's `.venv-backend`, and PostgreSQL 17 binaries. The launcher creates the environment and installs the lock file on first use if it is absent. On this PC it finds the existing binaries automatically; elsewhere pass `-Python PATH_TO_PYTHON -PostgresBin PATH_TO_PG_BIN`. Run in an ordinary PowerShell terminal as Carlos; the restricted agent sandbox cannot start PostgreSQL. Port 8020 must be free.

**Start from the `poc-demo` desk:**

```powershell
& .\scripts\start-poc-demo.ps1
```

Open [the local demo](http://127.0.0.1:8020/poc-demo). The command seeds 150 invented products, creates three pending review cases and starts the app and its isolated database. Stop with Ctrl+C in that terminal. Restart preserves prior runs and decisions and creates fresh pending demo runs. The seed alone is `& .\.venv-backend\Scripts\python.exe scripts\seed-poc-demo.py`.

**Show these three fictional POs:**

1. **Clear code, similar code, ambiguous row** (`demo-three-tiers`; local structure reference **PO-04**): inspect/enlarge the source, enter your name and reason, approve the Certain line, select and approve the Probable line, and clarify the Uncertain line. Certain means one clear literal-code candidate; Probable means a normalized code or description suggests a candidate; Uncertain needs clarification. Every tier requires a decision.
2. **Codes inside descriptions and similar products** (`demo-description`; reference **PO-01**): inspect the embedded code and candidate description before selecting a product. A suggestion never silently changes an observed code. Correct a quantity if needed; its original literal stays saved and approval reopens.
3. **Existing product, new product, not a product** (`demo-three-answers`; reference **PO-23**): use catalog search to choose an existing product and approve separately; add a fictional new product and approve separately; mark the delivery instruction not a product. **Reviewed products → Finish** stays blocked until all required decisions are saved. Reload to show persistence.

For upload, download a fictional PDF/PNG/JPG from the entry page and choose it under **Upload a fictional PDF or photo**. Only recognized fictional bytes receive fixed observations. Return to `/poc-demo` for another upload. The standard landing page requires a real-catalog pool; its “API connection pending” banner is expected in this free kit.

**Reset:** stop the app, then run the same command with `-FreshDatabase`. It selects a new owned demo database and preserves the previous database, files and review evidence. It deletes nothing and never targets another desk. `-PrepareOnly` verifies setup and stops without retaining a website.

**Limits:** PO-01/04/23 are opaque private references; the displayed PDFs are invented structural examples, not extraction of those originals. The 33 original PDFs/45 pages were validated locally, and 33 fictional structural cases were dry-run. This proves workflow handling, not model accuracy. Source grounding and independent completeness remain known gaps. This is a review demonstration, with no pricing/stock guarantee or cart/order action. Step 4 is still unauthorized; Carlos must separately approve both a live run and which sources may leave this PC.
