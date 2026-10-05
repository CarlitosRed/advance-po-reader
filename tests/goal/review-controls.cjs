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
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
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
    await page.waitForFunction(() => document.getElementById("source-page")?.naturalWidth > 0 &&
      document.getElementById("row-preview")?.naturalWidth > 0);
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 1);
    assert.equal(await page.evaluate(() => state.events.length), 0);
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    await page.evaluate(() => renderDocument());

    if (seed.sourceMode === "photo") {
      await page.click("#reviewed-products");
      assert.equal(await page.locator("[data-confirm-unavailable]").count(), 1);
      await page.click('[data-confirm-unavailable="1"]');
      await page.waitForFunction(() => !state.busy && state.events.at(-1)?.action === "confirm_unavailable_page_text");
      assert.equal(await page.locator("[data-confirm-unavailable]").count(), 0);
      assert.equal(await page.locator("#finish-review").isDisabled(), true);
      assert.equal(await page.evaluate(() => state.summary.source_grounding.every(check => check.status === "unavailable")), true);
      assert.equal(await page.evaluate(() => state.summary.blockers.includes("independent_page_product_counts_required")), true);
      await page.evaluate(() => renderDocument());
    }
    const initialEventCount = await page.evaluate(() => state.events.length);

    const waitSaved = action => page.waitForFunction(action =>
      !state.busy && state.events.at(-1)?.action === action, action);
    await page.click("#approve-row");
    await waitSaved("approve");
    await page.click('[data-row="1"]');
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 0);
    await page.locator('input[name="candidate"]').check();
    await page.click("#approve-row");
    await page.waitForFunction(initial => !state.busy && state.events.length === initial + 2, initialEventCount);

    await page.click('[data-row="2"]');
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 0);
    await page.click("#answer-not-product");
    await waitSaved("not_a_product");
    assert.equal(await page.evaluate(() => state.result.extraction.rows[2].row_kind), "unknown");

    await page.locator(".review-answers summary").click();
    await page.fill("#new-product-sku", "GOAL-BROWSER-004");
    await page.fill("#new-product-description", "Fictional browser accessory");
    await page.locator("#new-product-form button").click();
    await waitSaved("new_product");
    assert.equal(await page.evaluate(() => state.events.at(-1).new_value.candidates[0].origin), "review");
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 1);
    assert.match(await page.locator(".candidate").innerText(), /Customer review/);
    await page.waitForFunction(() => document.getElementById("row-preview")?.naturalWidth > 0);
    await page.screenshot({path: path.join(path.dirname(fixture), "review-controls.png"), fullPage: true});
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    await page.evaluate(() => renderDocument());
    await page.locator('input[name="candidate"]').check();
    await page.click("#answer-product");
    await waitSaved("this_is_product");
    assert.equal(await page.evaluate(() => state.summary.pending_row_ids.includes("line-3")), true);
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 1);
    assert.equal(await page.evaluate(() => errorText(new Error("selected_candidate_outside_current_binding"))), "Select the product bound to this line, or save a new product binding before approving.");
    await page.click("#approve-row");
    await waitSaved("approve");
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    assert.match(await page.locator('[data-coverage-page="1"]').innerText(), /Extracted product items: 2/);
    await page.fill('[data-page-count="1"] input[name="product_count"]', "3");
    await page.locator('[data-page-count="1"] button').click();
    await waitSaved("confirm_page_product_count");
    assert.equal(await page.evaluate(() => state.summary.page_coverage[0].status), "mismatch");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    assert.equal(await page.locator("[data-new-count-run]").count(), 1);
    await page.fill("#review-reason", "My prior independent count included a heading; rechecked the two source products");
    await page.fill('[data-page-count="1"] input[name="product_count"]', "2");
    await page.locator('[data-page-count="1"] input[name="count_error"]').check();
    await page.locator('[data-page-count="1"] button').click();
    await page.waitForFunction(() => !state.busy && state.summary.page_coverage[0].status === "matched");
    assert.equal(await page.evaluate(() => state.summary.page_coverage[0].status), "matched");
    if (seed.sourceMode === "unsupported") {
      assert.equal(await page.locator("#finish-review").isDisabled(), true);
      assert.match(await page.locator('[data-source-row="line-1"]').innerText(), /Fictional fabricated text/);
      await page.click('[data-confirm-source="line-1"]');
      await waitSaved("confirm_source_text");
      assert.equal(await page.evaluate(() => state.summary.source_grounding[0].status), "unsupported");
      assert.equal(await page.evaluate(() => state.summary.approved_products.length), 3);
    }
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review");
    await waitSaved("resolve");
    assert.equal(await page.evaluate(() => state.run.review_state), "resolved");
    assert.deepEqual(errors, []);
    process.stdout.write("three answers and explicit approval passed\n");
  } finally {
    await browser.close();
  }
})().catch(error => {process.stderr.write(String(error.stack)); process.exitCode = 1;});
