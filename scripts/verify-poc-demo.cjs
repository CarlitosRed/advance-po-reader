"use strict";
// Browser check of the free demo's three-tab review flow: a fresh browser profile, loopback only,
// fictional QA attribution, the real controls. Usage:
//   node scripts/verify-poc-demo.cjs http://127.0.0.1:8022 "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
// Needs the `playwright` package (resolved from the current folder or next to the Node binary) and a
// Chromium-family browser; nothing is installed or downloaded by this script. No OpenAI call, no .env file.
// Run it against a demo started with -FreshDatabase: the free demo gives the same bytes the same run, so a second
// pass over already-reviewed samples stops at the first check with "nothing is approved before a person acts".
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require(require.resolve("playwright", {
  paths: [process.cwd(), path.join(path.dirname(process.execPath), "..", "node_modules")]
}));
const base = process.argv[2] || "http://127.0.0.1:8020";
if (new URL(base).hostname !== "127.0.0.1") throw new Error("Only a loopback demo can be verified");
const executablePath = process.argv[3];
const REVIEWER = "Synthetic QA (Claude simulation)";
const output = path.join(process.cwd(), "output", "poc-demo");
fs.mkdirSync(output, {recursive: true});

(async () => {
  const browser = await chromium.launch({executablePath, headless: true});
  const context = await browser.newContext({viewport: {width: 390, height: 844}});
  const external = [], errors = [];
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(base).origin && url.protocol !== "blob:") { external.push(url.hostname); return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  const screenshot = async name => {
    await page.waitForFunction(() => !document.getElementById("toast") || document.getElementById("toast").hidden);
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({path: path.join(output, name), fullPage: true});
  };
  const noOverflow = async label => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, "horizontal scroll on " + label);
  // A saved step: nothing is busy and the server now holds `count` events of this action.
  const saved = (action, count) => page.waitForFunction(([action, count]) => !state.busy && state.events.filter(e => e.action === action).length === count, [action, count], {timeout: 30000});
  const count = action => page.evaluate(action => state.events.filter(e => e.action === action).length, action);
  const approvedCount = () => page.evaluate(() => state.summary.approved_products.length);
  const rowId = index => page.evaluate(index => state.result.extraction.rows[index].row_id, index);
  const card = async index => page.locator('.tab-card[data-row-id="' + await rowId(index) + '"]');
  const tab = id => page.locator("#tab-" + id);
  const openTab = async id => { await tab(id).click(); await page.waitForSelector("#tab-" + id + "[aria-selected=true]"); };
  const selectedTab = () => page.evaluate(() => document.querySelector('.tab[aria-selected="true"]').dataset.tab);

  // Upload from the file input starts reading at once (no submit button); the first visit asks for a name.
  const openCase = async (id, ext = "pdf") => {
    await page.goto(base + "/poc-demo");
    await page.waitForFunction(() => document.querySelectorAll("#poc-cases a").length === 4);
    assert.equal(await page.locator("#poc-submit").count(), 0, "the entry page has no submit button");
    await page.setInputFiles("#poc-file", path.join(process.cwd(), "data", "poc-demo", "generated", id + "." + ext));
    await page.waitForSelector("#reviewer, #tab-panel", {timeout: 60000});
    if (await page.locator("#reviewer").count()) { await page.fill("#reviewer", REVIEWER); await page.click("#reviewer-form button.primary"); }
    await page.waitForSelector("#tab-panel");
    await page.waitForFunction(() => state.run && state.summary && state.suggestions);
    assert.equal(await page.evaluate(() => state.mode), "tabs");
    assert.equal(await approvedCount(), 0, "nothing is approved before a person acts");
    assert.equal(await page.evaluate(() => state.events.length), 0);
    await noOverflow("tabs of " + id);
  };
  const tiers = () => page.evaluate(() => state.suggestions.map(item => item.tier));
  const finish = async expectedApproved => {
    if (!(await page.locator("#finish-review").count())) await page.click("#reviewed-products");
    await page.waitForSelector("#finish-review");
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review");
    await saved("resolve", 1);
    await page.reload();
    await page.waitForFunction(() => state.run?.review_state === "resolved" && state.summary);
    assert.equal(await approvedCount(), expectedApproved);
  };
  // Check tab card with no printed suggestion: search, choose, then an explicit confirm.
  const chooseByCode = async (index, code, chosenSoFar) => {
    let c = await card(index);
    if (!(await c.locator('[data-form="search"]').count())) await c.locator('[data-act="edit"]').click();
    c = await card(index);
    await c.locator('[data-form="search"] input[name="q"]').fill(code);
    await c.locator('[data-form="search"] button').click();
    await c.locator('[data-act="choose"]').first().waitFor();
    const approvals = await count("approve");
    await c.locator('[data-act="choose"]').first().click();
    await saved("this_is_product", chosenSoFar);
    assert.equal(await count("approve"), approvals, "choosing a product is not a confirmation");
    const bound = await card(index);
    await bound.locator('[data-act="confirm"]').click();
    await saved("approve", approvals + 1);
  };
  const addNewProduct = async (index, sku, description, savedSoFar) => {
    let c = await card(index);
    if (!(await c.locator('[data-form="new"]').count())) await c.locator('[data-act="edit"]').click();
    c = await card(index);
    await c.locator("details.more-inline summary").click();
    await c.locator('[data-form="new"] input[name="sku"]').fill(sku);
    await c.locator('[data-form="new"] input[name="description"]').fill(description);
    const approvals = await count("approve");
    await c.locator('[data-form="new"] button').click();
    await saved("new_product", savedSoFar);
    assert.equal(await page.evaluate(() => state.events.at(-1).new_value.candidates[0].origin), "review");
    assert.equal(await count("approve"), approvals, "adding a product is not a confirmation");
    await (await card(index)).locator('[data-act="confirm"]').click();
    await saved("approve", approvals + 1);
  };
  const notAProduct = async (index, total) => {
    await (await card(index)).locator('[data-act="not-product"]').click();
    await saved("not_a_product", total);
  };

  try {
    await page.goto(base + "/poc-demo");
    await page.waitForFunction(() => document.querySelectorAll("#poc-cases a").length === 4);
    await noOverflow("entry");
    await screenshot("phone-entry.png");

    // ---- 1. Nothing is sure: the Sure tab is EMPTY (the usual real-world case) and must open without error.
    await openCase("demo-description");
    assert.deepEqual(await tiers(), ["probable", "probable", "uncertain"]);
    assert.equal(await selectedTab(), "check", "opens on the first tab with work");
    assert.match(await tab("sure").innerText(), /none/);
    assert.match(await page.locator("#tab-panel .tab-intro").innerText() + await page.locator("#tab-panel").innerText(), /Nothing was sure this time/);
    const embedded = await page.evaluate(() => state.result.extraction.rows[0].description.raw_value);
    assert.match(embedded, / code POC-/);
    assert.deepEqual(await page.evaluate(() => state.result.extraction.rows[0].identifiers), []);
    await openTab("sure");
    assert.deepEqual(errors, [], "opening an empty tab throws no error");
    assert.equal(await page.locator("#tab-filter").count(), 0);
    assert.equal(await page.locator(".tab-card").count(), 0);
    assert.match(await page.locator("#tab-empty").innerText(), /No line was sure this time/);
    await noOverflow("empty Sure tab");
    await screenshot("phone-empty-sure.png");
    await page.locator('#tab-empty button[data-tab="check"]').click();       // Go to Check
    await page.waitForSelector("#tab-check[aria-selected=true]");
    assert.equal(await page.locator(".tab-card").count(), 3);
    await openTab("not");
    assert.deepEqual(errors, []);
    assert.match(await page.locator("#tab-empty").innerText(), /No totals, notes or charges were found/);
    await openTab("check");
    // Open one line in the one-at-a-time view and come back.
    await (await card(0)).locator('[data-act="open-line"]').click();
    await page.waitForSelector("#back-tabs");
    assert.equal(await page.evaluate(() => state.mode), "line");
    await page.click("#back-tabs");
    await page.waitForSelector("#tab-panel");
    // Explicit decisions: two probable lines are confirmed by a click, the unclear one is not a product.
    await (await card(0)).locator('[data-act="confirm"]').first().click();
    await saved("approve", 1);
    await (await card(1)).locator('[data-act="confirm"]').first().click();
    await saved("approve", 2);
    await notAProduct(2, 1);
    assert.equal(await approvedCount(), 2);
    assert.equal(await page.evaluate(() => state.result.extraction.rows[0].description.raw_value), embedded);
    assert.deepEqual(await page.evaluate(() => state.result.extraction.rows[0].identifiers), []);
    await finish(2);

    // ---- 2. One sure line: filter, enlarge and a bulk confirm that respects the filter.
    await openCase("demo-three-tiers");
    assert.deepEqual(await tiers(), ["certain", "probable", "uncertain"]);
    assert.equal(await selectedTab(), "sure");
    await (await card(0)).locator('[data-act="enlarge"]').click();
    await page.waitForFunction(() => document.querySelector("#dialog-content canvas")?.width > 0);
    assert.equal(await page.locator("#detail-dialog").isVisible(), true);
    await page.click("#close-dialog");
    await page.fill("#tab-filter", "zzz-no-such-line");
    assert.equal(await page.locator("#bulk-confirm").isDisabled(), true);
    assert.match(await page.locator("#tab-empty").innerText(), /No line matches the filter/);
    await page.fill("#tab-filter", "");
    assert.equal(await page.locator("#bulk-confirm").innerText(), "Confirm all visible (1)");
    await page.click("#bulk-confirm");
    await saved("approve", 1);
    assert.equal(await approvedCount(), 1);
    await openTab("check");
    await (await card(1)).locator('[data-act="confirm"]').first().click();
    await saved("approve", 2);
    await notAProduct(2, 1);
    await openTab("not");
    assert.equal(await page.locator(".tab-card").count(), 1);
    await finish(2);

    // ---- 3. Every kind of line: all three tabs, filtered bulk approvals and explicit Check decisions.
    await openCase("demo-all-tabs");
    assert.deepEqual(await tiers(), ["certain", "certain", "certain", "probable", "probable", "uncertain"]);
    assert.equal(await selectedTab(), "sure");
    assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll(".tab")].map(t => t.querySelector(".tab-count").textContent)), ["3", "3", "3"]);
    // Filter down to exactly one sure line: the bulk button confirms that line only.
    const firstText = await page.evaluate(() => state.result.extraction.rows[0].description.raw_value.toLowerCase());
    await page.fill("#tab-filter", firstText);
    assert.equal(await page.locator(".tab-card:not([hidden])").count(), 1, "the filter leaves one line");
    assert.equal(await page.locator("#bulk-confirm").innerText(), "Confirm all visible (1)");
    await page.click("#bulk-confirm");
    await saved("approve", 1);
    assert.equal(await page.evaluate(() => state.events.at(-1).row_id === state.result.extraction.rows[0].row_id), true, "only the visible line was confirmed");
    assert.equal(await approvedCount(), 1);
    await page.fill("#tab-filter", "");
    assert.equal(await page.locator("#bulk-confirm").innerText(), "Confirm all visible (2)");
    // One sure line is not right: send it to Check, then bulk-confirm the other one.
    await (await card(2)).locator('[data-act="move"]').click();
    await page.waitForSelector("#bulk-confirm, #tab-sure");
    await openTab("sure");
    assert.equal(await page.locator("#bulk-confirm").innerText(), "Confirm all visible (1)");
    await page.click("#bulk-confirm");
    await saved("approve", 2);
    assert.equal(await approvedCount(), 2);
    assert.match(await tab("sure").innerText(), /all done/);
    // Check holds the moved line, two probable lines and the unclear one. Every answer is a click.
    await openTab("check");
    assert.equal(await page.locator(".tab-card").count(), 4);
    await (await card(2)).locator('[data-act="confirm"]').first().click();
    await saved("approve", 3);
    await chooseByCode(3, "POC-0101", 1);                                    // change product: search, choose, confirm
    await addNewProduct(4, "POC-QA-" + Date.now(), "Fictional QA accessory", 1);
    await notAProduct(5, 1);
    assert.equal(await approvedCount(), 5);
    // Not products: the three system lines are device-local marks (no server event), the person's mark is a real event.
    await openTab("not");
    assert.equal(await page.locator(".tab-card").count(), 4);
    const events = await page.evaluate(() => state.events.length);
    await page.locator('.tab-card [data-act="agree"]').first().click();
    await page.waitForSelector('.tab-card [data-act="unagree"]');
    await page.locator('.tab-card [data-act="flag"]').first().click();
    await page.waitForSelector('.tab-card [data-act="unflag"]');
    assert.equal(await page.evaluate(() => state.events.length), events, "agree and flag write no server event");
    await screenshot("phone-not-products.png");
    await page.click("#reviewed-products");
    await page.waitForSelector("#finish-review");
    assert.match(await page.locator("body").innerText(), /not in the spreadsheet/);
    await screenshot("phone-summary.png");
    await finish(5);
    await screenshot("phone-resolved-summary.png");

    // ---- 4. Three unclear lines: nothing to confirm, three ways to answer.
    await openCase("demo-three-answers");
    assert.deepEqual(await tiers(), ["uncertain", "uncertain", "uncertain"]);
    assert.equal(await selectedTab(), "check");
    await chooseByCode(0, "POC-0101", 1);
    await addNewProduct(1, "POC-QA-" + Date.now(), "Fictional QA accessory two", 1);
    await notAProduct(2, 1);
    assert.equal(await approvedCount(), 2);
    await finish(2);

    // ---- 5. The same order as PNG and JPG opens on the same tabs and approves nothing.
    for (const ext of ["png", "jpg"]) {
      await openCase("demo-three-tiers", ext);
      assert.equal(await page.evaluate(() => state.run.provider), "synthetic");
      assert.deepEqual(await tiers(), ["certain", "probable", "uncertain"]);
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const result = {viewport: [390, 844], entry_has_no_submit_button: true, upload_starts_review: true,
      empty_sure_and_not_tabs_open_without_error: true, empty_tab_explanation_and_go_to_check: true,
      filtered_bulk_confirm_only_visible: true, move_to_check: true, explicit_check_decisions: true,
      change_product_search_choose_confirm: true, new_product_then_confirm: true, not_a_product: true,
      device_local_agree_and_flag_write_no_event: true, enlarge: true, no_horizontal_overflow: true,
      finish_and_resolved_reload: true, uploads: ["PDF", "PNG", "JPG"],
      external_browser_requests: external.length, page_errors: errors.length, attribution: REVIEWER};
    fs.writeFileSync(path.join(output, "browser-qa.json"), JSON.stringify(result, null, 2));
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  } finally { await browser.close(); }
})().catch(error => {process.stderr.write(String(error.stack)); process.exitCode = 1;});
