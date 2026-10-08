/* Browser verification for the static, synthetic mockup only.
 * Run: node web/po-reader-mockup/tests/mockup-v2.cjs
 * Uses a loopback static server; rejects every external request and every XHR/fetch.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const playwrightModule = process.env.PLAYWRIGHT_MODULE || 'C:/Users/carlo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const browserExecutable = process.env.BROWSER_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const { chromium } = require(playwrightModule);

const mockupRoot = path.resolve(__dirname, '..');
const staticRoot = path.join(mockupRoot, 'dist');
const screenshotsRoot = path.resolve(mockupRoot, '../../docs/mockup-v2/screenshots');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.pdf': 'application/pdf' };
const forbiddenRequests = [];
const browserErrors = [];
const consoleErrors = [];
const results = [];

const server = http.createServer((request, response) => {
  let file;
  try {
    const name = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname).replace(/^\/+/, '') || 'index.html';
    file = path.resolve(staticRoot, name);
  } catch {
    response.writeHead(400).end();
    return;
  }
  if (!file.startsWith(staticRoot + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    response.writeHead(404).end();
    return;
  }
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.end(fs.readFileSync(file));
});

function row(page, line) {
  return page.locator(`article[data-row="line-${line}"]`);
}

async function checkProgress(page, expected) {
  await page.waitForFunction(value => document.querySelector('#review-progress')?.textContent.includes(`${value} of 7 lines reviewed`), expected);
  const actual = await page.locator('#review-progress').innerText();
  assert(actual.includes(`${expected} of 7 lines reviewed`), `Unexpected progress: ${actual}`);
  assert.equal(await page.locator('#review-final').isDisabled(), expected !== 7, 'Final review must require all seven source decisions');
}

async function checkAccepted(page, expected) {
  if (await page.locator('#accepted-count').count()) {
    assert.equal((await page.locator('#accepted-count').innerText()).trim(), String(expected), 'Unexpected final accepted count');
  } else {
    assert.match(await page.locator('.progress-label').innerText(), new RegExp(`\\b${expected} accepted\\b`), 'Unexpected review accepted count');
  }
}

async function saveScreenshot(page, name) {
  await page.waitForFunction(() => {
    const toast = document.querySelector('#status-message');
    return !toast || (!toast.classList.contains('visible') && getComputedStyle(toast).opacity === '0');
  });
  // Full-page captures otherwise place offscreen fixed controls relative to
  // the scrolled viewport, including the hidden skip link above its origin.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(screenshotsRoot, name), fullPage: true });
}

async function freshSample(page, baseUrl) {
  await page.goto(baseUrl);
  await page.locator('#sample-order').click();
  await page.locator('#review-progress').waitFor({ timeout: 15000 });
  await checkProgress(page, 0);
  await checkAccepted(page, 0);
  assert.equal(await page.locator('article[data-row]').count(), 7, 'Every source line must have a card');
  for (const line of [4, 6, 7]) {
    assert.equal(await row(page, line).locator('.answer-choices > button').count(), 3, `Line ${line} must offer exactly three uncertain answers`);
    for (const action of ['choose-existing', 'create-new', 'ignore']) {
      assert.equal(await row(page, line).locator(`.answer-choices [data-action="${action}"]`).count(), 1);
    }
  }
  assert.equal(await page.locator('#approve-all').count(), 0, 'Acceptance must remain behind final review');
}

async function selectExisting(page, line, sku, query = sku) {
  await row(page, line).locator('[data-action="choose-existing"]').click();
  const search = page.locator(`#search-line-${line}`);
  await search.fill(query);
  await page.locator(`[data-product="${sku}"]`).first().click();
  const form = page.locator(`form[data-form="existing"][data-row="line-${line}"]`);
  await form.waitFor();
  return form;
}

async function setField(form, name, value) {
  const field = form.locator(`[name="${name}"]`);
  if (await field.evaluate(element => element.tagName === 'SELECT')) await field.selectOption(value);
  else await field.fill(value);
}

async function approveExisting(page, line, sku, quantity, unit) {
  const form = await selectExisting(page, line, sku);
  await setField(form, 'quantity', quantity);
  await setField(form, 'unit', unit);
  await form.getByRole('button', { name: 'Approve line', exact: true }).click();
}

async function verifyOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({ viewport: window.innerWidth, body: document.body.scrollWidth, document: document.documentElement.scrollWidth }));
  assert(dimensions.body <= dimensions.viewport + 1 && dimensions.document <= dimensions.viewport + 1, `${label} overflows horizontally: ${JSON.stringify(dimensions)}`);
}

async function verifyResponsiveState(page, label) {
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: width >= 768 ? 1000 : 844 });
    await verifyOverflow(page, `${width}px ${label}`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
}

async function main() {
  fs.mkdirSync(screenshotsRoot, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch({ headless: true, executablePath: browserExecutable });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, serviceWorkers: 'block' });
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== new URL(baseUrl).origin || ['xhr', 'fetch', 'websocket'].includes(request.resourceType())) {
      forbiddenRequests.push({ url: url.href, type: request.resourceType() });
      await route.abort();
    } else await route.continue();
  });
  context.on('page', page => {
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('websocket', socket => forbiddenRequests.push({ url: socket.url(), type: 'websocket' }));
  });
  const page = await context.newPage();
  try {
    await page.goto(baseUrl);
    await verifyResponsiveState(page, 'upload screen');
    const rejectedFiles = [
      { name: 'invalid.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic technical test') },
      { name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('invalid synthetic PDF signature') },
      { name: 'empty.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) },
      { name: 'oversized.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(25 * 1024 * 1024 + 1) }
    ];
    for (const fixture of rejectedFiles) {
      await page.locator('#file-input').setInputFiles(fixture);
      await page.waitForFunction(() => Boolean(document.querySelector('#upload-error')?.textContent));
      assert.equal(await page.locator('#review-progress').count(), 0, `${fixture.name} must not open review`);
      assert.equal(await page.locator('#cancel-reading').count(), 0, `${fixture.name} must not begin simulated reading`);
      await page.goto(baseUrl);
    }
    results.push('unsupported, invalid-signature, empty and oversized synthetic uploads are rejected');

    for (const fixture of ['sample-purchase-order.pdf', 'line-4.png']) {
      await page.locator('#file-input').setInputFiles(path.join(staticRoot, 'assets', fixture));
      await page.locator('#cancel-reading').waitFor();
      await page.locator('#review-progress').waitFor({ timeout: 15000 });
      await checkProgress(page, 0);
      await checkAccepted(page, 0);
      assert((await page.locator('.notice').innerText()).includes(fixture));
      await page.locator('[data-action="preview-file"]').click();
      await page.locator('dialog[open]').waitFor();
      if (fixture.endsWith('.png')) assert.match(await page.locator('#preview-content img').getAttribute('src'), /^blob:/);
      else assert.match(await page.locator('#preview-content a').getAttribute('href'), /^blob:/);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('dialog[open]').count(), 0);
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-action')), 'preview-file', 'Escape must return focus to the chosen-file preview control');
      await checkProgress(page, 0);
      await checkAccepted(page, 0);
      await page.goto(baseUrl);
    }
    results.push('existing sample PDF and PNG open local previews and synthetic results with zero accepted');

    await page.locator('#sample-order').click();
    await page.locator('#cancel-reading').click();
    await page.locator('#sample-order').waitFor();
    await page.waitForTimeout(2600);
    assert.equal(await page.locator('#review-progress').count(), 0, 'Cancelled simulation must not reopen review');
    results.push('cancelled reading remains cancelled');

    await freshSample(page, baseUrl);
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: width >= 768 ? 1000 : 844 });
      await verifyOverflow(page, `${width}px initial review`);
      if (width === 390) await saveScreenshot(page, 'after-phone.png');
      if (width === 1440) await saveScreenshot(page, 'after-desktop.png');
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#document-preview').click();
    await page.locator('dialog[open]').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog[open]').count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'document-preview', 'Escape must restore the original document preview button focus');
    await checkProgress(page, 0);
    await checkAccepted(page, 0);
    results.push('preview and navigation never approve a line');

    for (const line of [1, 2, 3]) {
      await row(page, line).locator('[data-action="approve"]').click();
      await checkProgress(page, line);
    }
    results.push('certain lines require three separate explicit review taps');

    const originalPackText = await row(page, 5).locator('.raw-observation').textContent();
    const originalPackImage = await row(page, 5).locator('.snippet-image img').getAttribute('src');
    const probableForm = await selectExisting(page, 5, '79009');
    await checkProgress(page, 3);
    for (const quantity of ['', '0', '-1', 'abc', '1e3', '100000', '1.2345']) {
      await setField(probableForm, 'quantity', quantity);
      await probableForm.getByRole('button', { name: 'Approve line', exact: true }).click();
      await checkProgress(page, 3);
    }
    await setField(probableForm, 'quantity', '2');
    await setField(probableForm, 'unit', 'PK');
    await checkProgress(page, 3);
    await probableForm.getByRole('button', { name: 'Approve line', exact: true }).click();
    await checkProgress(page, 4);
    await row(page, 5).locator('[data-action="edit"]').click();
    await checkProgress(page, 3);
    await approveExisting(page, 5, '79009', '1.250', 'PK');
    await checkProgress(page, 4);
    assert((await row(page, 5).locator('.product-meta').innerText()).includes('1.250 PK'), 'Reviewed decimal quantity and pack unit must remain literal strings');
    assert.equal(await row(page, 5).locator('.raw-observation').textContent(), originalPackText, 'Reviewed quantity must not alter literal source evidence');
    assert.equal(await row(page, 5).locator('.snippet-image img').getAttribute('src'), originalPackImage, 'Reviewed quantity must not replace the original snippet');
    await checkAccepted(page, 0);
    results.push('invalid quantities stay pending; an edit revokes a prior decision until a new approval');
    results.push('decimal PK decision preserved while original quantity, unit and snippet remain unchanged');

    const uncertainForm = await selectExisting(page, 4, '7050718L');
    await checkProgress(page, 4);
    await verifyResponsiveState(page, 'uncertain editor');
    await saveScreenshot(page, 'after-uncertain-phone.png');
    await setField(uncertainForm, 'quantity', '2');
    await setField(uncertainForm, 'unit', 'EA');
    await uncertainForm.getByRole('button', { name: 'Approve line', exact: true }).click();
    await checkProgress(page, 5);

    await row(page, 6).locator('[data-action="create-new"]').click();
    const newForm = page.locator('form[data-form="new"][data-row="line-6"]');
    await setField(newForm, 'productName', 'Fictional review item');
    await setField(newForm, 'quantity', '1');
    await setField(newForm, 'unit', 'EA');
    await setField(newForm, 'productId', '7140618');
    await newForm.getByRole('button', { name: 'Add sample product & review line', exact: true }).click();
    await checkProgress(page, 5);
    assert.match(await newForm.locator('.inline-error').innerText(), /already|duplicate/i, 'Duplicate existing product code must be rejected');
    await setField(newForm, 'productId', 'DEMO-NEW-006');
    for (const [name, restore] of [['productName', 'Fictional review item'], ['quantity', '1'], ['unit', 'EA']]) {
      await setField(newForm, name, '');
      await newForm.getByRole('button', { name: 'Add sample product & review line', exact: true }).click();
      await checkProgress(page, 5);
      assert((await newForm.locator('.inline-error').innerText()).trim().length > 0, `Blank ${name} must show an error`);
      await setField(newForm, name, restore);
    }
    await checkProgress(page, 5);
    await newForm.getByRole('button', { name: 'Add sample product & review line', exact: true }).click();
    await checkProgress(page, 6);
    const appendedProductForm = await selectExisting(page, 7, 'DEMO-NEW-006');
    assert((await appendedProductForm.locator('.selected-product').innerText()).includes('Fictional review item'), 'New product must be searchable from another line');
    await setField(appendedProductForm, 'quantity', '1');
    await setField(appendedProductForm, 'unit', 'EA');
    await appendedProductForm.getByRole('button', { name: 'Approve line', exact: true }).click();
    await checkProgress(page, 7);
    await row(page, 7).locator('[data-action="edit"]').click();
    await checkProgress(page, 6);
    await row(page, 7).locator('[data-action="ignore"]').click();
    await checkProgress(page, 7);
    const ignored = page.locator('#ignored-lines');
    assert.equal(await ignored.evaluate(element => element.tagName), 'DETAILS');
    assert.equal(await ignored.getAttribute('open'), null, 'Ignored section should start collapsed');
    await ignored.locator('summary').click();
    assert((await ignored.innerText()).includes('shipping') || (await ignored.innerText()).includes('Carriage'), 'Ignored source text must remain inspectable');
    await ignored.locator('[data-action="edit"]').click();
    await checkProgress(page, 6);
    await row(page, 7).locator('[data-action="ignore"]').click();
    await checkProgress(page, 7);
    results.push('choose existing, create sample product and ignore retain separate deliberate decisions');
    results.push('duplicate and blank new-product fields are rejected; appended sample product is searchable on another line');

    await page.locator('#review-final').click();
    await page.locator('#approve-all').waitFor();
    assert.equal(await page.locator('#approve-all').isDisabled(), false, 'Final explicit approval must be available after complete review');
    await checkAccepted(page, 0);
    await verifyResponsiveState(page, 'pending final summary');
    await page.locator('#back-review').click();
    await checkProgress(page, 7);
    await row(page, 1).locator('[data-action="edit"]').click();
    await checkProgress(page, 6);
    await row(page, 1).locator('[data-action="approve"]').click();
    await checkProgress(page, 7);
    await page.locator('#review-final').click();
    await checkAccepted(page, 0);
    await page.locator('#approve-all').click();
    assert.equal(await page.locator('#approve-all').isDisabled(), true, 'Acceptance must be idempotent');
    await checkAccepted(page, 6);
    assert.match(await page.locator('main').innerText(), /approved|accepted|confirmed/i, 'Accepted sample state must be visible');
    await verifyResponsiveState(page, 'accepted summary');
    await saveScreenshot(page, 'after-approval-phone.png');
    results.push('final acceptance requires a second explicit tap; returning and editing reopens the gate');

    await page.locator('[data-final-row="line-5"] [data-action="edit"]').click();
    await checkProgress(page, 6);
    await checkAccepted(page, 0);
    await approveExisting(page, 5, '79009', '1.250', 'PK');
    await checkProgress(page, 7);
    await page.locator('#review-final').click();
    await checkAccepted(page, 0);
    await page.locator('#approve-all').click();
    await checkAccepted(page, 6);
    results.push('editing an accepted line revokes every final acceptance until a new final tap');

    // Each uncertain answer is also exercised in a clean zero-review sample run.
    await freshSample(page, baseUrl);
    await approveExisting(page, 4, '7050718L', '2', 'EA');
    await checkProgress(page, 1);
    await freshSample(page, baseUrl);
    await row(page, 6).locator('[data-action="create-new"]').click();
    const isolatedNew = page.locator('form[data-form="new"][data-row="line-6"]');
    for (const [name, value] of Object.entries({ productId: 'DEMO-NEW-TEST', productName: 'Fictional QA item', quantity: '1', unit: 'EA' })) await setField(isolatedNew, name, value);
    await isolatedNew.getByRole('button', { name: 'Add sample product & review line', exact: true }).click();
    await checkProgress(page, 1);
    await freshSample(page, baseUrl);
    await row(page, 7).locator('[data-action="ignore"]').click();
    await checkProgress(page, 1);
    results.push('all three uncertain answer paths pass in independent fresh runs');

    assert.deepEqual(forbiddenRequests, [], 'Mockup attempted an API or external request');
    assert.deepEqual(browserErrors, [], 'Mockup raised a browser JavaScript error');
    assert.deepEqual(consoleErrors, [], 'Mockup raised a browser console or CSP error');
    results.push('zero API/external requests, browser exceptions, console errors and CSP errors');
    console.log(JSON.stringify({ status: 'passed', checks: results, screenshots: ['after-phone.png', 'after-desktop.png', 'after-uncertain-phone.png', 'after-approval-phone.png'] }, null, 2));
  } finally {
    await context.close();
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  if (forbiddenRequests.length) console.error('Forbidden requests:', forbiddenRequests);
  server.close();
  process.exitCode = 1;
});
