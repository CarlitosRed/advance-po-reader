"use strict";
// Feeds REAL review-API suggestions (fictional run, written by test_goal_reasons.py) through plainReason.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {plainReason};", context);
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const suggestion = id => data.suggestions.find(s => s.row_id === id);
const row = id => data.rows.find(r => r.row_id === id);
const reason = id => context.api.plainReason(row(id), suggestion(id));

const expected = {
  "line-1": "No catalog product matches this code or name.",
  "line-2": "The printed code is written a little differently from the catalog code.",
  "line-3": "A code in the description does not match the printed code.",
  "line-4": "No product code on this line; matched by name only.",
  "line-5": "No code column on this line; the code was found inside the description.",
  "line-6": "3 catalog products could match this line; pick the right one.",
  "line-7": "The catalog has both 'D6224-2' and 'WERNER D6224-2'.",
  "line-9": "Part of this line is hard to read.",
  "line-10": "The printed code is an alternate code for this product, written a little differently.",
  "line-11": "The printed code is not the catalog's main code for this product.",
  "line-12": "A code in the description does not match this product.",
  "line-13": "A code in the description does not match the printed code.",
  "line-14": "The printed code is not the catalog's main code for this product.",
  "line-15": "2 catalog products could match this line; pick the right one.",
  "line-16": "The printed code is not the catalog's main code for this product.",
};
const seen = {};
for (const [id, text] of Object.entries(expected)) seen[id] = reason(id);
if (process.env.REASONS_DUMP) console.log(JSON.stringify(data.suggestions.map(s => [s.row_id, s.method, s.tier, s.tier_reason, s.candidates.map(c => c.sku)]), null, 1), seen);
for (const [id, text] of Object.entries(expected)) assert.equal(seen[id], text, id);
// The control line is certain: it belongs to Sure and is never given a reason in Check.
assert.equal(suggestion("line-8").tier, "certain");
console.log("plain reasons on real data passed");
