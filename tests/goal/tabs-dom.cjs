"use strict";
// Real browser check of the three-tab screen when some tabs are EMPTY (the common case: nothing "sure").
// Loopback only, fictional data, no network beyond the test-owned server.
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
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.route("**/*", route => {
      const url = route.request().url();
      return url.startsWith(origin + "/") || url.startsWith("blob:") ? route.continue() : route.abort();
    });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(origin);
    await page.evaluate(seed => {Object.assign(state, seed); renderDocument();}, seed);

    // No line is sure, so the page opens on Check, which has a toolbar and cards.
    await page.waitForSelector("#tab-check[aria-selected=true]");
    assert.equal(await page.locator("#tab-filter").count(), 1);
    assert.equal(await page.locator(".tab-card").count(), 2);
    assert.match(await page.locator("#tab-sure").innerText(), /none/);

    // Open the EMPTY Sure tab: no exception, no toolbar, a plain explanation and a working button.
    await page.click("#tab-sure");
    await page.waitForSelector("#tab-sure[aria-selected=true]");
    assert.deepEqual(errors, []);
    assert.equal(await page.locator("#tab-filter").count(), 0);
    assert.equal(await page.locator(".tab-card").count(), 0);
    assert.equal(await page.locator("#tab-empty").isVisible(), true);
    assert.match(await page.locator("#tab-empty").innerText(), /No line was sure this time/);
    const goTo = page.locator("#tab-empty button[data-tab=check]");
    assert.match(await goTo.innerText(), /Go to Check \(2\)/);
    // The rest of the page is still wired after an empty tab: the tab keys and the summary button respond.
    await page.focus("#tab-sure");
    await page.keyboard.press("ArrowRight");
    await page.waitForSelector("#tab-check[aria-selected=true]");
    await page.click("#tab-sure");
    await goTo.click();
    await page.waitForSelector("#tab-check[aria-selected=true]");
    assert.equal(await page.locator("#tab-filter").count(), 1);
    assert.equal(await page.locator(".tab-card").count(), 2);

    // The filter works on a tab that has lines, and a filter that matches nothing says so.
    await page.fill("#tab-filter", "zzz-no-such-line");
    assert.equal(await page.locator(".tab-card:not([hidden])").count(), 0);
    assert.match(await page.locator("#tab-empty").innerText(), /No line matches the filter/);
    await page.fill("#tab-filter", "");
    assert.equal(await page.locator(".tab-card:not([hidden])").count(), 2);

    // The Not products tab is empty too (no totals, notes or marked lines in this fixture).
    await page.click("#tab-not");
    await page.waitForSelector("#tab-not[aria-selected=true]");
    assert.equal(await page.locator("#tab-filter").count(), 0);
    assert.match(await page.locator("#tab-empty").innerText(), /No totals, notes or charges were found/);
    await page.locator("#tab-empty button[data-tab=check]").click();
    await page.waitForSelector("#tab-check[aria-selected=true]");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.deepEqual(errors, []);
    process.stdout.write("empty tabs passed\n");
  } finally {
    await browser.close();
  }
})().catch(error => {process.stderr.write(String(error.stack)); process.exitCode = 1;});
