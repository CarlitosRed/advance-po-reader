"use strict";
// Pure helpers of the three-tab review page: loads only the marked block of web/local-reader/workflow.js.
// No browser, no network, fictional rows only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
assert.ok(block.includes("function assignTabs"), "marked block not found");
const context = vm.createContext({});
// `const` at the top of a script is not a property of the context, so export the helpers explicitly.
vm.runInContext(block + "\nthis.api = {TAB_IDS, rowRoleOf, rowStatusOf, candidatesOf, boundCandidateOf, assignTabs, tabCounts, defaultTabOf, emptyTabCopy, wholePageCounts, bulkTargets, regionBox, snapshotGeometry};", context);
const api = context.api;
const plain = value => JSON.parse(JSON.stringify(value));

const cand = id => ({candidate_id: id, sku: "SKU-" + id, description: "Fictional product " + id});
const region = (name, y0, y1) => ({region_reference: name, bbox: {x0: 0.05, y0, x1: 0.95, y1}});
const row = (id, over = {}) => ({row_id: id, row_kind: "product", row_role: "product_item", identifiers: [], description: {raw_value: "Fictional " + id},
  evidence: [{page_number: 1, region_reference: "r-" + id}], ...over});
const payload = (rows, schema = "1.2") => ({schema_version: schema, rows,
  pages: [{page_number: 1, regions: rows.map((r, i) => region("r-" + r.row_id, 0.1 + i * 0.08, 0.16 + i * 0.08))}]});
const sug = (id, tier, ...ids) => ({row_id: id, tier, suggested_candidate_id: tier === "certain" ? ids[0] : null, candidates: ids.map(cand)});
const ids = group => Array.from(group, e => e.row.row_id);

// --- roles: new schema reads row_role, legacy schema maps row_kind
assert.equal(api.rowRoleOf({row_role: "continuation"}, "1.2"), "continuation");
assert.equal(api.rowRoleOf({row_kind: "product"}, "1.1"), "product_item");
for (const kind of ["charge", "tax", "subtotal", "total", "note"]) assert.equal(api.rowRoleOf({row_kind: kind}, "1.1"), "document_detail");
assert.equal(api.rowRoleOf({row_kind: "unknown"}, "1.1"), "unknown");

// --- tabs: every row lands in exactly one tab
const rows = [row("a"), row("b"), row("c"), row("d"), row("e", {row_role: "document_detail", row_kind: "total"}),
  row("f", {row_role: "continuation"}), row("g", {row_role: "unknown", row_kind: "unknown"})];
const suggestions = [sug("a", "certain", "1"), sug("b", "probable", "2", "3"), sug("c", "uncertain", "4"), sug("d", "certain", "5"), sug("g", "uncertain")];
let groups = api.assignTabs(payload(rows), suggestions, [], null);
assert.deepEqual(ids(groups.sure), ["a", "d"]);
assert.deepEqual(ids(groups.check), ["b", "c", "g"]);
assert.deepEqual(ids(groups.not), ["e"]);
assert.equal(groups.sure.length + groups.check.length + groups.not.length, rows.length - 1, "continuations belong to their parent line");
assert.equal(groups.not[0].kind, "system");
assert.deepEqual(plain(api.tabCounts(groups)), {sure: {total: 2, todo: 2}, check: {total: 3, todo: 3}, not: {total: 1, todo: 1}});
assert.deepEqual(Array.from(groups.sure, e => e.lineIndex), [0, 3], "line numbers count only product-like rows");

// A certain row that has no suggested product cannot be confirmed in one click: it goes to Check.
groups = api.assignTabs(payload([row("a")]), [{row_id: "a", tier: "certain", suggested_candidate_id: null, candidates: []}], [], null);
assert.deepEqual(ids(groups.check), ["a"]);
// A row with no suggestion at all is uncertain.
groups = api.assignTabs(payload([row("a")]), [], [], null);
assert.deepEqual(ids(groups.check), ["a"]);

// --- decisions move rows
const event = (id, action, over = {}) => ({row_id: id, action, new_value: {candidates: []}, ...over});
groups = api.assignTabs(payload(rows), suggestions, [event("a", "approve"), event("b", "not_a_product")], null);
assert.deepEqual(ids(groups.sure), ["a", "d"], "an approved sure row stays in Sure, marked done");
assert.equal(groups.sure[0].done, true);
assert.equal(groups.sure[1].done, false);
assert.deepEqual(ids(groups.not), ["b", "e"].sort(), "a person-marked line joins Not products");
assert.equal(groups.not.find(e => e.row.row_id === "b").kind, "person");
assert.equal(groups.not.find(e => e.row.row_id === "b").done, true);
// A chosen product waits in Check for confirmation, even if the line was sure.
groups = api.assignTabs(payload(rows), suggestions, [event("a", "this_is_product", {new_value: {candidates: [cand("9")]}})], null);
assert.ok(ids(groups.check).includes("a"));
assert.equal(groups.check.find(e => e.row.row_id === "a").boundId, "9");
// Latest decision wins: not-a-product then a new binding brings the line back.
groups = api.assignTabs(payload(rows), suggestions, [event("c", "not_a_product"), event("c", "this_is_product", {new_value: {candidates: [cand("9")]}})], null);
assert.ok(ids(groups.check).includes("c"));
// Marks: moved forces Check; agreed / flagged finish a system line.
groups = api.assignTabs(payload(rows), suggestions, [], {moved: ["a"], agreed: ["e"]});
assert.ok(ids(groups.check).includes("a") && !ids(groups.sure).includes("a"));
assert.equal(groups.not[0].agreed, true);
assert.equal(groups.not[0].done, true);
groups = api.assignTabs(payload(rows), suggestions, [], {flagged: ["e"]});
assert.equal(groups.not[0].flagged, true);
assert.equal(groups.not[0].done, true);

// --- default tab and empty tabs (real runs often have zero certain rows)
const zeroCertain = api.assignTabs(payload([row("a"), row("b"), row("e", {row_role: "document_detail", row_kind: "total"})]),
  [sug("a", "probable", "1"), sug("b", "uncertain", "2")], [], null);
let counts = api.tabCounts(zeroCertain);
assert.equal(counts.sure.total, 0);
assert.equal(api.defaultTabOf(counts), "check", "an empty Sure tab is never the first screen");
const sureEmpty = api.emptyTabCopy("sure", counts, false);
assert.match(sureEmpty.text, /No line was sure this time/);
assert.equal(sureEmpty.goto, "check");
assert.equal(api.emptyTabCopy("not", {...counts, not: {total: 0, todo: 0}}, false).goto, "check");
assert.match(api.emptyTabCopy("sure", counts, true).text, /filter/);
// Everything done: open the first tab that has lines.
const allDone = {sure: {total: 2, todo: 0}, check: {total: 1, todo: 0}, not: {total: 0, todo: 0}};
assert.equal(api.defaultTabOf(allDone), "sure");
assert.match(api.emptyTabCopy("sure", allDone, false).text, /done/);
assert.equal(api.defaultTabOf({sure: {total: 0, todo: 0}, check: {total: 0, todo: 0}, not: {total: 2, todo: 0}}), "not");
assert.equal(api.defaultTabOf({sure: {total: 0, todo: 0}, check: {total: 0, todo: 0}, not: {total: 0, todo: 0}}), "sure");
assert.equal(api.emptyTabCopy("sure", {sure: {total: 0, todo: 0}, check: {total: 0, todo: 0}, not: {total: 0, todo: 0}}, false).goto, null);

// --- bulk confirm: only visible, unresolved Sure rows with a suggestion
groups = api.assignTabs(payload(rows), suggestions, [event("a", "approve")], null);
assert.deepEqual(plain(api.bulkTargets(groups.sure, ["a", "d", "b"])), [{rowId: "d", candidateId: "5"}], "approved, hidden and non-sure rows are left alone");
assert.deepEqual(plain(api.bulkTargets(groups.sure, [])), []);

// --- snapshot geometry
const g = api.snapshotGeometry({x0: 0.1, y0: 0.4, x1: 0.9, y1: 0.45}, 1000, 2000);
assert.ok(g.sx >= 0 && g.sy >= 0 && g.sx + g.sw <= 1000 && g.sy + g.sh <= 2000, "crop stays inside the page");
assert.ok(g.sy < 800 && g.sy + g.sh > 900, "context above and below the row");
assert.ok(g.highlight.x >= 0 && g.highlight.y >= 0 && g.highlight.x + g.highlight.w <= g.sw && g.highlight.y + g.highlight.h <= g.sh, "highlight sits inside the crop");
assert.equal(g.highlight.w, 800);
assert.equal(g.highlight.h, 100);
// A narrow box is widened so the text stays readable; a box at the page edge never leaves the page.
const narrow = api.snapshotGeometry({x0: 0.9, y0: 0.0, x1: 0.99, y1: 0.02}, 1000, 1000);
assert.ok(narrow.sw >= 600 && narrow.sx + narrow.sw <= 1000 && narrow.sy === 0);
// Missing, inverted or broken boxes fall back to the whole page; options.page keeps the whole page and still highlights.
const whole = {sx: 0, sy: 0, sw: 500, sh: 700, highlight: null};
for (const bad of [null, undefined, {x0: 0.5, y0: 0.5, x1: 0.4, y1: 0.6}, {x0: "a", y0: 0, x1: 1, y1: 1}, {x0: 0.2, y0: 0.2, x1: 0.2, y1: 0.4}]) assert.deepEqual(plain(api.snapshotGeometry(bad, 500, 700)), whole);
assert.deepEqual(plain(api.snapshotGeometry({x0: 0.1, y0: 0.1, x1: 0.2, y1: 0.2}, 0, 0)), {sx: 0, sy: 0, sw: 0, sh: 0, highlight: null});
const pageMode = api.snapshotGeometry({x0: 0.1, y0: 0.1, x1: 0.2, y1: 0.2}, 500, 700, {page: true});
assert.deepEqual(plain(pageMode), {sx: 0, sy: 0, sw: 500, sh: 700, highlight: {x: 50, y: 70, w: 50, h: 70}});
// Out-of-range coordinates are clamped, never drawn outside the page.
const clamped = api.snapshotGeometry({x0: -0.5, y0: 0.1, x1: 1.5, y1: 0.2}, 500, 700);
assert.ok(clamped.sx === 0 && clamped.sw <= 500 && clamped.highlight.w === 500);

// --- region lookup and rows without an exact spot
const p = payload([row("a"), row("b", {evidence: [{page_number: 1, region_reference: "missing"}]}), row("c", {evidence: []})]);
assert.ok(api.regionBox(p, p.rows[0]));
assert.equal(api.regionBox(p, p.rows[1]), null);
assert.equal(api.regionBox(p, p.rows[2]), null);
groups = api.assignTabs(p, [], [], null);
assert.deepEqual(plain(api.wholePageCounts(p, groups)), {1: 2});

console.log("three-tab helpers passed");
