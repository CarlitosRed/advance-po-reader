"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", {
  paths: [process.cwd(), path.join(path.dirname(process.execPath), "..", "node_modules")]
}));

(async () => {
  const [origin, fixture, executablePath] = process.argv.slice(2);
  const seed = JSON.parse(fs.readFileSync(fixture, "utf8"));
  const browser = await chromium.launch({executablePath, headless: true});
  try {
    // The review screen is phone-first: one line card at a time.
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    // This browser may reach only the test-owned server, never an existing service.
    await page.route("**/*", route => {
      const url = route.request().url();
      return url.startsWith(origin + "/") || url.startsWith("blob:")
        ? route.continue() : route.abort();
    });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(origin);
    await page.evaluate(seed => {Object.assign(state, seed); renderDocument();}, seed);
    await page.waitForFunction(() => document.getElementById("row-preview")?.naturalWidth > 0);
    // Only the Certain match is pre-selected; nothing is approved until a person clicks.
    assert.equal(await page.locator('.guess[data-preselected="true"]').count(), 1);
    assert.equal(await page.evaluate(() => state.events.length), 0);
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    await page.evaluate(() => renderDocument());

    const waitSaved = action => page.waitForFunction(action =>
      !state.busy && state.events.at(-1)?.action === action, action);
    await page.click("#approve-row");
    await waitSaved("approve");
    // After an explicit answer the card moves to the next line that still needs one (Probable).
    await page.waitForFunction(() => /Line 2 of 3/.test(document.querySelector(".progress-text")?.innerText || ""));
    assert.equal(await page.locator('.guess[data-preselected="false"]').count(), 1);
    await page.click("#approve-row");
    await page.waitForFunction(() => !state.busy && state.events.length === 2);

    // Uncertain: no candidate, so no approve button; the single question offers three answers.
    await page.waitForFunction(() => /Line 3 of 3/.test(document.querySelector(".progress-text")?.innerText || ""));
    assert.equal(await page.locator("#approve-row").count(), 0);
    assert.equal(await page.locator(".answer").count(), 3);
    await page.click("#answer-not-product");
    await waitSaved("not_a_product");
    assert.equal(await page.evaluate(() => state.result.extraction.rows[2].row_kind), "unknown");

    // Change the answer: add a new product, which saves a binding that still needs approval.
    await page.evaluate(() => {state.row = 2; renderDocument();});
    await page.click("#change-answer");
    await page.click("#answer-new");
    await page.fill("#new-product-sku", "GOAL-BROWSER-004");
    await page.fill("#new-product-description", "Fictional browser accessory");
    await page.locator("#new-product-form button").click();
    await waitSaved("new_product");
    assert.equal(await page.evaluate(() => state.events.at(-1).new_value.candidates[0].origin), "review");
    assert.match(await page.locator(".guess").innerText(), /Added by a reviewer/);
    await page.waitForFunction(() => document.getElementById("row-preview")?.naturalWidth > 0);
    await page.screenshot({path: path.join(path.dirname(fixture), "review-controls.png"), fullPage: true});
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    await page.evaluate(() => renderDocument());

    // Pick another: choose the existing (customer-added) product, then approve it separately.
    await page.click("#pick-another");
    await page.click("#answer-existing");
    await page.locator("#panel-existing [data-propose]").first().click();
    await waitSaved("this_is_product");
    assert.equal(await page.evaluate(() => state.summary.pending_row_ids.includes("line-3")), true);
    assert.equal(await page.evaluate(() => errorText(new Error("selected_candidate_outside_current_binding"))), "Select the product bound to this line, or save a new product binding before approving.");
    await page.click("#approve-row");
    await waitSaved("approve");
    // Every line is answered: the done screen offers Finish and, after it, the spreadsheet.
    await page.waitForSelector(".done-head");
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review");
    await waitSaved("resolve");
    assert.equal(await page.evaluate(() => state.run.review_state), "resolved");
    // The reason is optional: saved events carry the default text, never an empty reason.
    assert.equal(await page.evaluate(() => state.events.every(e => e.reason.length > 0)), true);
    assert.deepEqual(errors, []);
    process.stdout.write("three answers and explicit approval passed\n");
  } finally {
    await browser.close();
  }
})().catch(error => {process.stderr.write(String(error.stack)); process.exitCode = 1;});
