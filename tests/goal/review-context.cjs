"use strict";
// R01: a click made for one document must never write to, or process, another document after navigation.
// Runs the REAL review-action and authorization functions of web/local-reader/workflow.js in a vm with fake
// responses (no browser, no network). Fictional ids only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
function between(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end);
  assert.ok(from >= 0 && to > from, "marked block not found: " + start);
  return source.slice(from, to);
}
// Newer sources carry markers; the pre-fix source is sliced by its function names so the same test can run red.
const hasMarkers = source.includes("/* review-actions:start */");
const reviewBlock = hasMarkers ? between("/* review-actions:start */", "/* review-actions:end */")
  : between("async function reviewAction", "async function openSnapshot");
const authorizeBlock = source.includes("/* authorize:start */") ? between("/* authorize:start */", "/* authorize:end */") : "";

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise, resolve, reject}; }
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(resolve => setImmediate(resolve)); };

function world() {
  const log = {requests: [], toasts: [], errors: [], renders: 0, marks: [], processed: []};
  const pending = [];
  const state = {run: {id: "run-A"}, source: {id: "src-A"}, workspace: {id: "tenant-1"}, reviewer: "Fictional reviewer", reason: "",
    busy: false, tabs: {edit: {}}, result: {extraction: {}}, mode: "tabs", view: "document", events: [], processingRequest: null};
  const context = vm.createContext({state, log, setImmediate,
    console, Error, Promise,
    api(requestPath, options = {}) {
      const method = options.method || "GET";
      log.requests.push({method, path: requestPath, body: options.json || null, run: requestPath.split("/")[2]});
      if (method === "POST") { const gate = deferred(); pending.push(gate); return gate.promise; }
      return Promise.resolve({id: requestPath.split("/")[2]});
    },
    readAttribution: () => ({reviewer: state.reviewer, reason: "Checked"}),
    clearMessages() {}, fail(error) { log.errors.push(error.message); }, toast(text) { log.toasts.push(text); },
    renderDocument() { log.renders++; }, loadRun: () => (log.loadGate ? log.loadGate.promise : Promise.resolve()), toggleMark(kind, rowId, on) { log.marks.push({kind, rowId, on, run: state.run.id}); },
    processSavedRun: async runId => { log.processed.push(runId); },
    crypto: {randomUUID: () => "key"},
    document: {querySelectorAll: () => [{dataset: {rowId: "r1"}}, {dataset: {rowId: "r2"}}]},
    bulkTargets: (sure, visible) => visible.map(rowId => ({rowId, candidateId: "c-" + rowId})),
    escapeHTML: value => String(value), $: () => null,
  });
  vm.runInContext(reviewBlock + authorizeBlock + "\nthis.exports = {handleTabAction, bulkConfirm, handleTabForm};"
    + (authorizeBlock ? "\nthis.exports.authorizeSource = authorizeSource;" : ""), context);
  const navigate = (runId, sourceId) => { state.run = {id: runId}; state.source = {id: sourceId}; };
  return {state, log, pending, navigate, run: context.exports};
}
const writes = log => log.requests.filter(r => r.method === "POST");
const button = (act, cid) => ({dataset: {act, cid}});
const card = {};
const uncertain = {tier: "uncertain", boundId: null, row: {row_id: "r1", evidence: [{page_number: 1, region_reference: "x"}]}};

(async () => {
  // 1. Counterexample from the review: bind (this_is_product) for A is in flight; the person opens B; the bind
  //    finishes. The following approve must not be sent to B (nor anywhere).
  {
    const w = world();
    w.run.handleTabAction(button("confirm", "cand-1"), card, uncertain, "check");
    await settle();
    assert.deepEqual(writes(w.log).map(r => r.path), ["/runs/run-A/reviews"], "bind goes to A");
    w.navigate("run-B", "src-B");
    w.pending[0].resolve({});
    await settle();
    assert.deepEqual(writes(w.log).map(r => r.path), ["/runs/run-A/reviews"], "no later write after navigation");
    assert.ok(!w.log.requests.some(r => r.path.includes("run-B") && r.method === "POST"), "nothing written to B");
    assert.equal(w.state.run.id, "run-B", "B stays on screen");
    assert.equal(w.state.busy, false);
    assert.ok(w.log.errors.includes("review_context_changed"));
    assert.equal(w.log.marks.length, 0);
    assert.equal(w.log.toasts.length, 0, "no 'Confirmed' toast for the other document");
  }
  // 2. Same click, no navigation: bind then approve, both to A, with the original reviewer even if it is edited.
  {
    const w = world();
    w.run.handleTabAction(button("confirm", "cand-1"), card, uncertain, "check");
    await settle();
    w.state.reviewer = "Someone else";
    w.pending[0].resolve({});
    await settle();
    assert.deepEqual(writes(w.log).map(r => r.body.action), ["this_is_product", "approve"]);
    assert.ok(writes(w.log).every(r => r.path === "/runs/run-A/reviews" && r.body.reviewer === "Fictional reviewer"));
  }
  // 3. Bulk confirm: later rows must not be sent after navigation.
  {
    const w = world();
    w.run.bulkConfirm({sure: [{row: {row_id: "r1", evidence: []}}, {row: {row_id: "r2", evidence: []}}]});
    await settle();
    assert.equal(writes(w.log).length, 1);
    w.navigate("run-B", "src-B");
    w.pending[0].resolve({});
    await settle();
    assert.deepEqual(writes(w.log).map(r => r.path + ":" + r.body.row_id), ["/runs/run-A/reviews:r1"]);
    assert.ok(!w.log.requests.some(r => r.path.includes("run-B") && r.method === "POST"));
  }
  // 4. Single-write handlers: the write is A's, and A's local follow-ups (marks, edit state) do not touch B.
  for (const act of ["not-product", "choose"]) {
    const w = world();
    w.state.tabs.edit["r1"] = true;
    w.run.handleTabAction(button(act, "cand-1"), card, {...uncertain}, "check");
    await settle();
    w.navigate("run-B", "src-B");
    w.state.tabs.edit = {r1: "B-owned"};
    w.pending[0].resolve({});
    await settle();
    assert.deepEqual(writes(w.log).map(r => r.path), ["/runs/run-A/reviews"], act);
    assert.equal(w.state.tabs.edit.r1, "B-owned", act + ": B's screen state is untouched");
    assert.equal(w.log.marks.length, 0, act);
    assert.equal(w.log.toasts.length, 0, act);
    assert.equal(w.state.run.id, "run-B", act + ": B's run is not overwritten");
  }
  // 5. New product: the form values are read at click time and written to A.
  {
    const w = world();
    const form = {dataset: {form: "new", key: "k1"}, elements: {sku: {value: "SKU-1"}, description: {value: "Fictional"}, vendor: undefined}};
    w.run.handleTabForm(form, card, uncertain);
    await settle();
    form.elements.sku.value = "CHANGED";
    w.navigate("run-B", "src-B");
    w.pending[0].resolve({});
    await settle();
    assert.deepEqual(writes(w.log).map(r => [r.path, r.body.product.sku]), [["/runs/run-A/reviews", "SKU-1"]]);
    assert.equal(w.log.marks.length + w.log.toasts.length, 0);
  }
  // 6. Authorize-and-extract: the run created for A is the only run that may be processed, and only if A is
  //    still the open document. Opening an already authorized B meanwhile must never process B.
  if (authorizeBlock) {
    const w = world();
    const auth = {authorized: true, source_sha256: "a".repeat(64), authorized_by: "Fictional", policy_reference: "p", reason: "r"};
    const done = w.run.authorizeSource("src-A", "process", auth);
    await settle();
    w.navigate("run-B", "src-B");
    w.pending[0].resolve({id: "run-A2"});
    await done;
    assert.deepEqual(w.log.processed, [], "no processing after navigation");
    assert.equal(w.state.run.id, "run-B", "B's run is not replaced");
    // The review's path: navigation happens while the new run is loading, then state.run is B.
    const w3 = world();
    w3.log.loadGate = deferred();
    const late = w3.run.authorizeSource("src-A", "process", auth);
    await settle();
    w3.pending[0].resolve({id: "run-A2"});
    await settle();
    w3.navigate("run-B", "src-B");
    w3.log.loadGate.resolve();
    await late;
    assert.deepEqual(w3.log.processed, [], "an already authorized B is never processed");
    // Still on A: processes the run just created, not whatever state.run holds.
    const w2 = world();
    const ok = w2.run.authorizeSource("src-A", "process", auth);
    await settle();
    w2.pending[0].resolve({id: "run-A2"});
    await ok;
    assert.deepEqual(w2.log.processed, ["run-A2"]);
  }
  console.log("review context passed" + (authorizeBlock ? "" : " (authorize block absent)"));
})().catch(error => { console.error(error); process.exit(1); });
