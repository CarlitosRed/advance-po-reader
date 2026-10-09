"use strict";
// R01 remainder: a slow loader for document A must never install its source, run or result after the person has
// moved on to document B (a "mixed pair": B's source panel with A's review data, so a decision writes to A).
// Runs the REAL loader functions of web/local-reader/app.js and workflow.js in a vm with deferred fake responses
// (no browser, no network). Fictional ids only.
// Usage: node loader-context.cjs [check-name ...]   (default: every check). Exit code 1 if any check fails.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// LOADER_SOURCE_DIR lets the same checks run against another copy of the two files (for example the pre-fix source).
const sourceDir = process.env.LOADER_SOURCE_DIR || path.join(__dirname, "..", "..", "web", "local-reader");
const read = name => fs.readFileSync(path.join(sourceDir, name), "utf8");
const appSource = read("app.js"), workflowSource = read("workflow.js");
function between(text, start, end) {
  const from = text.indexOf(start), to = text.indexOf(end, from + 1);
  assert.ok(from >= 0 && to > from, "block not found: " + start + " .. " + end);
  return text.slice(from, to);
}
// Sliced by function names so the same checks run against the pre-fix source (red) and the fixed source (green).
const loaders = between(appSource, "async function startUpload", "function renderPendingDocument");
const chooseCatalogSource = between(appSource, "function chooseCatalog", "function catalogScopeQuery");
const claimSource = appSource.includes("function claimNavigation") ? between(appSource, "function claimNavigation", "function setView") : "";
const errorTextSource = between(appSource, "function errorText", "function fail(");
const restoreRouteSource = between(appSource, "async function restoreRoute", "window.addEventListener(\"popstate\"");
const processSavedRunSource = between(workflowSource, "async function processSavedRun", "function enhancePending");

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise, resolve, reject}; }
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(resolve => setImmediate(resolve)); };
const suffix = id => String(id).replace(/^(src|run)-/, "");

class FakeFormData { constructor() { this.values = new Map(); } set(key, value) { this.values.set(key, value); } get(key) { return this.values.get(key); } }

function world() {
  const log = {requests: [], renders: [], toasts: [], errors: [], summaries: 0, uploadsRendered: 0};
  const holds = new Map();
  const state = {csrf: "", workspace: {id: "tenant-1"}, catalog: {id: "pool-1", is_pool: true}, defaultPool: {id: "pool-1", name: "All products", is_pool: true},
    catalogs: [{id: "vendor-sample", name: "Fictional sample", synthetic: true}, {id: "vendor-B", name: "Fictional vendor B"}],
    pools: [{id: "pool-1", name: "All products", is_pool: true}], library: [{sha256: "lib-sha", filename: "library.pdf"}],
    configuration: {limits: {upload_bytes: 1e9}}, view: "upload", source: null, run: null, name: "", page: 1, row: 0, mode: "tabs",
    tabs: {tab: null, show: {}, edit: {}, query: ""}, busy: false, result: null, summary: null, runReadiness: null, events: [], suggestions: [],
    processingRequest: null, nav: 0};
  const hold = (method, route) => { const gate = deferred(); holds.set(method + " " + route, gate); return gate; };
  const snapshot = () => ({source: state.source?.id || null, run: state.run?.id || null, result: state.result?.run || null});
  function respond(method, route, options) {
    let m;
    if (method === "POST" && route === "/documents") return {id: "src-" + w.uploadId, sha256: "sha-" + w.uploadId, page_count: 1, catalog_pool_id: null, vendor_id: options.body.get("vendor_id") || null};
    if (method === "POST" && (m = /^\/documents\/([^/]+)\/runs$/.exec(route))) return {id: "run-" + suffix(m[1]), state: "created", provider: options.json.provider};
    if (method === "POST" && /^\/runs\/[^/]+\/process$/.test(route)) return {};
    if (method === "GET" && (m = /^\/documents\/([^/]+)$/.exec(route))) return {id: m[1], sha256: "sha-" + suffix(m[1]), page_count: 1, vendor_id: "vendor-B", catalog_pool_id: null};
    if (method === "GET" && (m = /^\/documents\/([^/]+)\/runs$/.exec(route))) return {runs: [{id: "run-" + suffix(m[1])}]};
    if (method === "GET" && (m = /^\/runs\/([^/]+)$/.exec(route))) return {id: m[1], state: "completed", review_state: "open", provider: "openai"};
    if (method === "GET" && (m = /^\/runs\/([^/]+)\/(result|suggestions|reviews|summary|readiness)$/.exec(route))) {
      const run = m[1];
      return {result: {extraction: {rows: []}, run}, suggestions: {suggestions: [], run}, reviews: {events: [], run}, summary: {run}, readiness: {run, can_process: true, blockers: []}}[m[2]];
    }
    if (method === "GET" && route === "/website/demo-document") return {size: 10, type: "application/pdf"};
    if (method === "GET" && /^\/website\/corpus\/[^/]+\/content$/.test(route)) return {size: 10, type: "application/pdf"};
    throw new Error("unexpected request " + method + " " + route);
  }
  const context = vm.createContext({state, log, setImmediate, console, Error, Promise, Map, Set, URL, URLSearchParams, JSON, String, Number, RegExp, Object, Array, FormData: FakeFormData,
    File: class { constructor(parts, name) { this.name = name; this.size = 10; } },
    location: {hash: ""}, crypto: {randomUUID: () => "key"},
    api(route, options = {}) {
      const method = options.method || "GET";
      log.requests.push({method, path: route, vendor: options.body?.get?.("vendor_id") ?? null, json: options.json || null});
      const gate = holds.get(method + " " + route);
      if (gate) { holds.delete(method + " " + route); return gate.promise; }
      return Promise.resolve(respond(method, route, options));
    },
    stopStatusPolling() {}, clearMessages() {}, showLoading() {}, fail(error) { log.errors.push(error.message); }, toast(text) { log.toasts.push(text); },
    renderDocument() { log.renders.push(snapshot()); }, renderUpload() { log.uploadsRendered++; }, renderSummary() { log.summaries++; },
    setView() {}, escapeHTML: value => String(value)});
  vm.runInContext(claimSource + chooseCatalogSource + loaders + restoreRouteSource + processSavedRunSource
    + "\nthis.exports = {startUpload, startSample, openSource, loadRun, restoreRoute, processSavedRun, useLibraryDocument: typeof useLibraryDocument === 'function' ? useLibraryDocument : null};", context);
  vm.runInContext(errorTextSource + "\nthis.errorText = errorText;", context);
  const w = {context, state, log, hold, run: context.exports, uploadId: "A", errorText: context.errorText, snapshot};
  return w;
}
function assertConsistent(snap, label) {
  if (snap.source && snap.run) assert.equal(suffix(snap.source), suffix(snap.run), label + ": source " + snap.source + " is paired with run " + snap.run);
  if (snap.run && snap.result) assert.equal(snap.result, snap.run, label + ": run " + snap.run + " shows the result of " + snap.result);
}
function assertNeverMixed(w, label) {
  for (const snap of w.log.renders) assertConsistent(snap, label + " (render)");
  assertConsistent(w.snapshot(), label + " (final)");
}
function assertIsB(w, label = "") {
  const got = "source=" + w.state.source?.id + " run=" + w.state.run?.id;
  assert.equal(got, "source=src-B run=run-B", (label ? label + ": " : "") + "state is " + got + ", expected source=src-B run=run-B");
}
const pdf = {name: "order.pdf", size: 10};

const checks = {
  // 1. processSavedRun: A's process request is done, A's final GET /runs/run-A is slow, document B is opened.
  async processSavedRun_final_read_never_pairs_B_with_run_A() {
    const w = world();
    w.state.source = {id: "src-A"}; w.state.run = {id: "run-A", state: "created"}; w.state.result = {run: "run-A"};
    const gate = w.hold("GET", "/runs/run-A");
    const pending = w.run.processSavedRun("run-A");
    await settle();
    await w.run.openSource("src-B");
    assertIsB(w, "B finished opening");
    gate.resolve({id: "run-A", state: "completed", review_state: "open"});
    await pending.catch(() => {}); await settle();
    assertIsB(w, "A's late run was dropped");
    assertNeverMixed(w, "processSavedRun");
    assert.equal(w.state.processingRequest, null);
  },
  // 2. openSource: A's /documents/A/runs answer is slow; B is opened and finishes; A's list arrives.
  async openSource_slow_run_list_never_pairs_B_with_run_A() {
    const w = world();
    const gate = w.hold("GET", "/documents/src-A/runs");
    const pending = w.run.openSource("src-A");
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({runs: [{id: "run-A"}]});
    await pending.catch(() => {}); await settle();
    assertIsB(w);
    assertNeverMixed(w, "openSource");
  },
  // 2b. openSource: every other awaited response (document, run read, run data) is dropped when stale.
  async openSource_every_slow_response_is_dropped_when_stale() {
    for (const [method, route] of [["GET", "/documents/src-A"], ["GET", "/runs/run-A"], ["GET", "/runs/run-A/result"], ["GET", "/runs/run-A/summary"]]) {
      const w = world();
      const gate = w.hold(method, route);
      const pending = w.run.openSource("src-A");
      await settle();
      await w.run.openSource("src-B");
      gate.resolve(route === "/documents/src-A" ? {id: "src-A", sha256: "sha-A", page_count: 1, vendor_id: "vendor-B", catalog_pool_id: null}
        : route === "/runs/run-A" ? {id: "run-A", state: "completed"} : route.endsWith("/result") ? {extraction: {rows: []}, run: "run-A"} : {run: "run-A"});
      await pending.catch(() => {}); await settle();
      assertIsB(w, route);
      assertNeverMixed(w, "openSource " + route);
    }
  },
  // 3. startUpload: the create-run response for uploaded A is slow; B is opened.
  async startUpload_slow_create_run_never_pairs_B_with_run_A() {
    const w = world();
    const gate = w.hold("POST", "/documents/src-A/runs");
    const pending = w.run.startUpload(pdf);
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({id: "run-A", state: "created", provider: "openai"});
    await pending.catch(() => {}); await settle();
    assertIsB(w);
    assertNeverMixed(w, "startUpload");
    assert.equal(w.state.busy, false, "the upload no longer holds the busy flag");
    assert.equal(w.log.uploadsRendered, 0, "a stale upload does not repaint the upload screen over B");
  },
  // 3b. startUpload: the synthetic path (process + refresh + load) is also dropped, and sends no process request once stale.
  async startUpload_synthetic_steps_stop_when_stale() {
    const w = world();
    w.state.catalog = w.state.catalogs[0];
    const gate = w.hold("POST", "/documents/src-A/runs");
    const pending = w.run.startUpload(pdf, true, w.state.catalogs[0]);
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({id: "run-A", state: "created", provider: "synthetic"});
    await pending.catch(() => {}); await settle();
    assertIsB(w);
    assert.ok(!w.log.requests.some(r => r.path === "/runs/run-A/process"), "no process request for the stale upload");
    assertNeverMixed(w, "startUpload synthetic");
  },
  // 3c. startUpload: a failure that arrives after navigation does not repaint the upload screen over B.
  async startUpload_stale_failure_does_not_repaint_over_B() {
    const w = world();
    const gate = w.hold("POST", "/documents/src-A/runs");
    const pending = w.run.startUpload(pdf);
    await settle();
    await w.run.openSource("src-B");
    gate.reject(new Error("server_unavailable"));
    await pending.catch(() => {}); await settle();
    assert.equal(w.log.uploadsRendered, 0);
    assertIsB(w);
  },
  // 4. startSample: the synthetic catalog chosen before the byte fetch is the one the upload uses.
  async startSample_keeps_its_catalog_across_the_byte_fetch() {
    const w = world();
    const gate = w.hold("GET", "/website/demo-document");
    const pending = w.run.startSample();
    await settle();
    w.state.catalog = w.state.catalogs[1]; // a legacy vendor catalog becomes current during the byte fetch
    gate.resolve({size: 10, type: "application/pdf"});
    await pending; await settle();
    const upload = w.log.requests.find(r => r.method === "POST" && r.path === "/documents");
    assert.ok(upload, "the sample upload happened");
    assert.equal(upload.vendor, "vendor-sample", "the sample is written to the synthetic catalog, not " + upload.vendor);
    assert.equal(w.state.catalog.id, "vendor-sample");
    assertNeverMixed(w, "startSample");
  },
  // 4b. startSample: if document B is opened during the byte fetch, the older sample click is dropped.
  async startSample_is_dropped_when_another_document_opens_first() {
    const w = world();
    const gate = w.hold("GET", "/website/demo-document");
    const pending = w.run.startSample();
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({size: 10, type: "application/pdf"});
    await pending.catch(() => {}); await settle();
    assert.ok(!w.log.requests.some(r => r.method === "POST" && r.path === "/documents"), "no sample upload over B");
    assertIsB(w);
    assertNeverMixed(w, "startSample dropped");
  },
  // 5. Library button: same class (bytes fetched, then startUpload takes over the screen).
  async library_download_is_dropped_when_another_document_opens_first() {
    const w = world();
    assert.ok(w.run.useLibraryDocument, "useLibraryDocument exists");
    const gate = w.hold("GET", "/website/corpus/lib-sha/content");
    const pending = w.run.useLibraryDocument("lib-sha");
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({size: 10, type: "application/pdf"});
    await pending.catch(() => {}); await settle();
    assert.ok(!w.log.requests.some(r => r.method === "POST" && r.path === "/documents"), "no library upload over B");
    assertIsB(w);
  },
  // 6. Route loader: a summary route for A must not paint a summary over B.
  async restoreRoute_summary_is_not_painted_for_a_dropped_load() {
    const w = world();
    const idA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    w.context.location.hash = "#document=" + idA + "&run=&summary=1";
    const gate = w.hold("GET", "/documents/" + idA + "/runs");
    const pending = w.run.restoreRoute();
    await settle();
    await w.run.openSource("src-B");
    gate.resolve({runs: [{id: "run-" + idA}]});
    await pending.catch(() => {}); await settle();
    assert.equal(w.log.summaries, 0, "no summary painted for the dropped route load");
    assertIsB(w);
    assertNeverMixed(w, "restoreRoute");
  },
  // 7. Normal paths still work and install source, run and result together.
  async openSource_without_navigation_installs_a_consistent_pair() {
    const w = world();
    assert.equal(await w.run.openSource("src-A"), true);
    assert.deepEqual([w.state.source.id, w.state.run.id, w.state.result.run], ["src-A", "run-A", "run-A"]);
    assert.equal(w.log.renders.length, 1);
    assertNeverMixed(w, "openSource normal");
    assert.equal(await w.run.openSource("src-A", "run-A"), true);
  },
  async startUpload_without_navigation_installs_a_consistent_pair() {
    const w = world();
    await w.run.startUpload(pdf);
    assert.deepEqual([w.state.source.id, w.state.run.id, w.state.result.run], ["src-A", "run-A", "run-A"]);
    assert.equal(w.log.renders.length, 1);
    assert.equal(w.state.busy, false);
    assertNeverMixed(w, "startUpload normal");
    assert.ok(!w.log.requests.some(r => r.path.endsWith("/process")), "a real upload is not processed without authorization");
  },
  async startSample_without_navigation_processes_the_sample_run() {
    const w = world();
    await w.run.startSample();
    assert.deepEqual([w.state.source.id, w.state.run.id, w.state.result.run], ["src-A", "run-A", "run-A"]);
    assert.ok(w.log.requests.some(r => r.path === "/runs/run-A/process" && r.method === "POST"));
    assert.equal(w.state.catalog.id, "vendor-sample");
    assertNeverMixed(w, "startSample normal");
  },
  async processSavedRun_without_navigation_refreshes_the_run() {
    const w = world();
    w.state.source = {id: "src-A"}; w.state.run = {id: "run-A", state: "created"}; w.state.result = null;
    await w.run.processSavedRun("run-A");
    assert.deepEqual([w.state.source.id, w.state.run.id, w.state.run.state, w.state.result.run], ["src-A", "run-A", "completed", "run-A"]);
    assert.ok(w.log.requests.some(r => r.method === "POST" && r.path === "/runs/run-A/process"));
    assert.equal(w.state.processingRequest, null);
  },
  // 8. P3: a known server error code gets a plain sentence, not "(code)".
  async error_text_explains_product_exists_outside_catalog_pool() {
    const w = world();
    const text = w.errorText(new Error("product_exists_outside_catalog_pool"));
    assert.ok(/another catalog pool/i.test(text), text);
    assert.ok(!text.includes("product_exists_outside_catalog_pool"), "no raw code in the message: " + text);
  },
};

(async () => {
  const wanted = process.argv.slice(2);
  const names = wanted.length ? wanted : Object.keys(checks);
  let failed = 0;
  for (const name of names) {
    if (!checks[name]) { console.log("FAIL " + name + ": unknown check"); failed++; continue; }
    try { await checks[name](); console.log("PASS " + name); }
    catch (error) { failed++; console.log("FAIL " + name + ": " + String(error.message).split("\n")[0]); }
  }
  console.log(failed ? failed + " of " + names.length + " loader checks failed" : "loader context passed (" + names.length + " checks)");
  process.exit(failed ? 1 : 0);
})();
