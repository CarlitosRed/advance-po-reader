"use strict";
// A fresh browser profile, loopback only, fictional QA attribution and real controls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require(require.resolve("playwright", {paths:[path.join(path.dirname(process.execPath), "..", "node_modules")]}));
const base = process.argv[2] || "http://127.0.0.1:8020";
if (new URL(base).hostname !== "127.0.0.1") throw new Error("Only a loopback demo can be verified");
const executablePath = process.argv[3];
const output = path.join(process.cwd(), "output", "poc-demo");
fs.mkdirSync(output, {recursive:true});
(async () => {
  const browser = await chromium.launch({executablePath, headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844}});
  const external = [], errors = [];
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(base).origin) { external.push(url.hostname); return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  const screenshot = async name => {
    await page.waitForFunction(() => !document.getElementById("toast") || document.getElementById("toast").hidden);
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.waitForFunction(() => window.scrollY === 0);
    await page.screenshot({path:path.join(output,name),fullPage:true});
  };
  page.on("pageerror", error => errors.push(error.message));
  const waitSaved = action => page.waitForFunction(action => !state.busy && state.events.at(-1)?.action === action, action);
  const reviewer = async () => {
    await page.fill("#reviewer", "Synthetic QA (Codex simulation)");
    await page.fill("#review-reason", "Inspected fictional fixture; not customer approval");
  };
  const openCase = async index => {
    await page.goto(base + "/poc-demo");
    await page.waitForFunction(() => document.querySelectorAll("#poc-cases a").length === 3);
    const caseIDs = ["demo-three-tiers", "demo-description", "demo-three-answers"];
    await page.setInputFiles("#poc-file", path.join(process.cwd(), "data", "poc-demo", "generated", caseIDs[index] + ".pdf"));
    await page.click("#poc-submit");
    await page.waitForSelector("#approve-row");
    await page.waitForFunction(() => document.getElementById("row-preview")?.naturalWidth > 0);
    await reviewer();
  };
  try {
    await page.goto(base + "/poc-demo");
    await page.waitForFunction(() => document.querySelectorAll("#poc-cases a").length === 3);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await screenshot("phone-entry.png");
    await openCase(0);
    assert.deepEqual(await page.evaluate(() => state.suggestions.map(item => item.tier)), ["certain","probable","uncertain"]);
    assert.equal(await page.evaluate(() => state.summary.approved_products.length), 0);
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.click("#enlarge-source");
    await page.waitForFunction(() => document.getElementById("enlarged-page")?.naturalWidth > 0);
    assert.equal(await page.locator("#detail-dialog").isVisible(), true);
    await page.click("#close-dialog");
    await screenshot("phone-three-tiers.png");
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), true);
    await page.evaluate(() => renderDocument());
    await page.click("#approve-row"); await waitSaved("approve");
    await page.locator("#correction-form").evaluate(form => form.closest("details").open = true);
    await page.selectOption("#correction-field", "quantity");
    await page.fill("#correction-value", "002.50");
    await page.locator("#correction-form button").click(); await waitSaved("correct");
    assert.equal(await page.evaluate(() => state.summary.pending_row_ids.includes(state.result.extraction.rows[0].row_id)), true);
    await page.reload(); await page.waitForSelector("#approve-row"); await reviewer();
    assert.equal(await page.evaluate(() => state.result.extraction.rows[0].quantity.raw_value), "002.00");
    assert.equal(await page.evaluate(() => effectiveValue(state.result.extraction.rows[0], "quantity")), "002.50");
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="1"]');
    assert.match(await page.locator(".decision-heading").innerText(), /probable/);
    assert.equal(await page.locator('input[name="candidate"]:checked').count(), 0);
    await page.locator('input[name="candidate"]').first().check();
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="2"]');
    assert.match(await page.locator(".decision-heading").innerText(), /uncertain/);
    await page.click("#answer-not-product"); await waitSaved("not_a_product");
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review"); await waitSaved("resolve");
    await page.reload(); await page.waitForFunction(() => state.run?.review_state === "resolved" && state.summary);
    assert.equal(await page.evaluate(() => state.summary.approved_products.length), 2);

    await openCase(1);
    assert.deepEqual(await page.evaluate(() => state.suggestions.map(item => item.tier)), ["probable","probable","uncertain"]);
    const embeddedDescription = await page.evaluate(() => state.result.extraction.rows[0].description.raw_value);
    assert.match(embeddedDescription, / code POC-/);
    assert.deepEqual(await page.evaluate(() => state.result.extraction.rows[0].identifiers), []);
    await page.locator('input[name="candidate"]').first().check();
    await page.click("#approve-row"); await waitSaved("approve");
    await page.locator("#correction-form").evaluate(form => form.closest("details").open = true);
    await page.selectOption("#correction-field", "quantity");
    await page.fill("#correction-value", "002.50");
    await page.locator("#correction-form button").click(); await waitSaved("correct");
    assert.equal(await page.evaluate(() => state.summary.pending_row_ids.includes(state.result.extraction.rows[0].row_id)), true);
    await page.reload(); await page.waitForSelector("#approve-row"); await reviewer();
    assert.equal(await page.evaluate(() => state.result.extraction.rows[0].description.raw_value), embeddedDescription);
    assert.deepEqual(await page.evaluate(() => state.result.extraction.rows[0].identifiers), []);
    assert.equal(await page.evaluate(() => state.result.extraction.rows[0].quantity.raw_value), "002.00");
    assert.equal(await page.evaluate(() => effectiveValue(state.result.extraction.rows[0], "quantity")), "002.50");
    await page.locator('input[name="candidate"]').first().check();
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="1"]');
    await page.locator('input[name="candidate"]').first().check();
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="2"]');
    await page.click("#answer-not-product"); await waitSaved("not_a_product");
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review"); await waitSaved("resolve");
    await page.reload(); await page.waitForFunction(() => state.run?.review_state === "resolved" && state.summary);
    assert.equal(await page.evaluate(() => state.summary.approved_products.length), 2);

    await openCase(2);
    await page.locator("#manual-search").evaluate(form => form.closest("details").open = true);
    await page.fill("#manual-query", "POC-0101");
    await page.locator("#manual-search button").click();
    await page.waitForSelector("[data-propose]"); await page.locator("[data-propose]").first().click();
    await waitSaved("this_is_product");
    assert.equal(await page.evaluate(() => state.summary.approved_products.length), 0);
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="1"]');
    await page.locator(".review-answers details").evaluate(details => details.open = true);
    await page.fill("#new-product-sku", "POC-QA-" + Date.now());
    await page.fill("#new-product-description", "Fictional QA accessory");
    await page.locator("#new-product-form button").click(); await waitSaved("new_product");
    assert.equal(await page.evaluate(() => state.events.at(-1).new_value.candidates[0].origin), "review");
    assert.equal(await page.evaluate(() => state.summary.approved_products.length), 1);
    await page.click("#approve-row"); await waitSaved("approve");
    await page.click('[data-row="2"]');
    await page.click("#answer-not-product"); await waitSaved("not_a_product");
    await page.click("#reviewed-products");
    assert.equal(await page.locator("#finish-review").isDisabled(), false);
    await page.click("#finish-review"); await waitSaved("resolve");
    await screenshot("phone-resolved-summary.png");

    for (const suffix of ["pdf","png","jpg"]) {
      await page.goto(base + "/poc-demo");
      await page.waitForFunction(() => document.querySelectorAll("#poc-cases a").length === 3);
      await page.setInputFiles("#poc-file", path.join(process.cwd(),"data","poc-demo","generated","demo-three-tiers." + suffix));
      await page.click("#poc-submit"); await page.waitForSelector("#approve-row");
      assert.equal(await page.evaluate(() => state.run.provider), "synthetic");
      assert.equal(await page.evaluate(() => state.summary.approved_products.length), 0);
      assert.deepEqual(await page.evaluate(() => state.suggestions.map(item => item.tier)), ["certain","probable","uncertain"]);
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const result = {viewport:[390,844],entry_no_horizontal_overflow:true,review_no_horizontal_overflow:true,
      all_three_tiers:true,all_three_answers:true,all_three_cases:true,embedded_code_observation_preserved:true,
      source_enlargement:true,explicit_approval:true,correction_reopens_approval:true,
      original_and_corrected_literals_persist:true,finish_blocker:true,resolved_reload:true,
      uploads:["PDF","PNG","JPG"],external_browser_requests:0,page_errors:0,
      attribution:"Synthetic QA (Codex simulation)"};
    fs.writeFileSync(path.join(output,"browser-qa.json"),JSON.stringify(result,null,2));
    process.stdout.write(JSON.stringify(result,null,2) + "\n");
  } finally { await browser.close(); }
})().catch(error => {process.stderr.write(String(error.stack));process.exitCode=1;});
