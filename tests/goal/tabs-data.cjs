"use strict";
// Feeds REAL API data (fictional run, written by the Python test) through the three-tab helpers.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {assignTabs, tabCounts, defaultTabOf, regionBox, snapshotGeometry, wholePageCounts};", context);
const api = context.api;
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const extraction = data.result.extraction;
const groups = api.assignTabs(extraction, data.suggestions, [], null);
const ids = group => Array.from(group, e => e.row.row_id);
assert.deepEqual(ids(groups.sure), data.expect.sure, "tier certain -> Sure");
assert.deepEqual(ids(groups.check), data.expect.check, "probable and uncertain -> Check");
assert.deepEqual(ids(groups.not), data.expect.not, "totals, notes and charges -> Not products");
// Every row has a region on the page, so every snapshot is a real crop, never the whole-page fallback.
assert.deepEqual(JSON.parse(JSON.stringify(api.wholePageCounts(extraction, groups))), {});
for (const entry of Object.values(groups).flat()) {
  const box = api.regionBox(extraction, entry.row);
  assert.ok(box, entry.row.row_id + " has a region");
  const g = api.snapshotGeometry(box, data.page.width, data.page.height);
  assert.ok(g.highlight && g.sx >= 0 && g.sy >= 0 && g.sx + g.sw <= data.page.width && g.sy + g.sh <= data.page.height, "crop inside the real page image");
}
// With nothing certain, the first screen is Check, never an empty Sure tab.
const noSure = api.tabCounts(api.assignTabs(extraction, data.suggestions.map(s => ({...s, tier: s.tier === "certain" ? "probable" : s.tier, suggested_candidate_id: null})), [], null));
assert.equal(noSure.sure.total, 0);
assert.equal(api.defaultTabOf(noSure), "check");
console.log("three-tab real data passed");
