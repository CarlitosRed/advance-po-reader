# Local POC demo — free mode

For Carlos · Wednesday, October 7, 2026. **150 fictional products; fake extraction; every decision is explicit.** This mode needs no API key, dotenv file, login or hosting.

**Prerequisites:** open a **NORMAL PowerShell** (Start menu → PowerShell, **NOT Run as administrator**). PostgreSQL refuses administrator sessions; the launcher stops before setup if elevated. This desk has Python 3.12, pinned `.venv-backend` dependencies and PostgreSQL 17 binaries. Port 8020 must be free. The restricted agent sandbox cannot start PostgreSQL.

**Start:** paste both lines in PowerShell and leave that terminal open.

```powershell
Set-Location -LiteralPath 'C:\Users\carlo\dev\advance-po-reader.worktrees\poc-demo'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1
```

The execution-policy bypass applies only to that one process; no Windows setting changes.

Wait for “Free POC ready”, then open [the local demo](http://127.0.0.1:8020/poc-demo). Stop with **Ctrl+C**. Restart preserves earlier runs/decisions and creates fresh pending cases in the owned database.

**Show the three buttons under “Three prepared review cases”.** In each case, click **Enlarge source**, inspect the printed line, then close it. Fill **Your name** and **Decision reason** before saving. Use a reason that identifies this as a fictional demonstration. Return to the local demo link between cases.

1. **Clear code, similar code, ambiguous row** (`demo-three-tiers`; opaque reference **PO-04**). Line 1 is **Certain**: one literal-code candidate is selected, but it is pending until **Approve selected product**. Select Line 2, **Probable**, check its candidate and approve. Select Line 3, **Uncertain**; for this demonstration exclude the fictional placeholder with **This is not a product** and explain that choice in the reason. **Reviewed products → Finish review** is enabled only after every required decision is saved.
2. **Codes inside descriptions and similar products** (`demo-description`; **PO-01**). Line 1 has a code inside its description; inspect the suggested product, select it and approve. Open **Correct a reviewed field**, choose **quantity**, enter `002.50` and **Save correction**. Approval reopens. Reload: the original `002.00` remains in evidence and the reviewed value is saved separately. Select the candidate and approve again. Approve Line 2 after checking its candidate; exclude Line 3's fictional unlisted placeholder with an explicit reason, then finish.
3. **Existing product, new product, not a product** (`demo-three-answers`; **PO-23**). Line 1: expand **Find another product**, search `POC-0101`, click **Choose product**, then approve separately. Line 2: expand **This is a new product**, use a unique invented code such as `POC-DEMO-NEW-01` and a fictional description, click **Add product and save choice**, then approve separately. Line 3: mark the delivery instruction **This is not a product**. Finish and reload to show the saved review. Unresolved quantity/unit labels remain visible; product decisions do not invent missing values.

**Upload demonstration:** download a fictional PDF/PNG/JPG from `/poc-demo`, choose that unchanged file and click **Upload and open review**. Only recognized fictional bytes receive fixed observations. Use `/poc-demo` for each upload; the standard landing page requires a real-catalog pool. “API connection pending” is expected in free mode.

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
