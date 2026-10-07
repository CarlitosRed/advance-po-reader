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

const NO_MATCH = "No catalog product matches this code or name.";
const CONFLICT = "The app found conflicting readings on this line; please check it.";
const HINT = "Matched from a code in the description; please check it against the printed line.";
const NAME = "Matched by an approximate search on the name or code; please check it.";
const EXACT = "A printed code matched exactly; please check the match against the line.";
const NORM = "Matched after ignoring spaces and punctuation in a printed code; please check it.";
const TWO = "2 catalog products could match this line; pick the right one.";
// Every sentence states a fact the API data proves (method, tier_reason, candidates, a hard-to-read field). None says a
// printed code is close to, different from or the same as the product.
const expected = {
  "line-1": NO_MATCH,
  "line-2": NORM,
  "line-3": CONFLICT,
  "line-4": "No product code on this line; matched by name only.",
  "line-5": "No code column on this line; the code was found inside the description.",
  "line-6": "3 catalog products could match this line; pick the right one.",
  "line-7": "The catalog has both 'D6224-2' and 'WERNER D6224-2'.",
  "line-9": "Part of this line is hard to read.",
  "line-10": NORM,
  "line-11": CONFLICT,
  "line-12": CONFLICT,
  "line-13": CONFLICT,
  "line-14": EXACT,
  "line-15": TWO,
  "line-16": CONFLICT,
  "line-17": HINT, "line-18": HINT, "line-19": HINT, "line-20": HINT, "line-22": HINT,
  "line-21": NAME,
  "line-23": CONFLICT,
  "line-24": CONFLICT,
  // Reported cases: exact name with an unrelated customer-role identifier is only "found by name"...
  "line-25": NAME,
  // ...a non-ASCII value literally equal to the catalog code (same-value customer alias) is never called a mismatch...
  "line-26": EXACT,
  // ...ASCII and non-ASCII aliases beside an unrelated name, a vendor alias beside the exact name...
  "line-27": EXACT,
  "line-28": EXACT,
  "line-29": CONFLICT,
  // ...and a page with no identifier column.
  "line-30": "No product code on this line; matched by name only.",
};
const seen = {};
for (const [id, text] of Object.entries(expected)) seen[id] = reason(id);
if (process.env.REASONS_DUMP) console.log(JSON.stringify(data.suggestions.map(s => [s.row_id, s.method, s.tier, s.tier_reason, s.candidates.map(c => c.sku)]), null, 1), seen);
for (const [id, text] of Object.entries(expected)) assert.equal(seen[id], text, id);
// The control line is certain: it belongs to Sure and is never given a reason in Check.
assert.equal(suggestion("line-8").tier, "certain");
// The reported reproduction and its numeric twin really are description-code-hint retrievals with no customer alias.
assert.equal(suggestion("line-17").method, "description_code_hint");
assert.equal(suggestion("line-18").method, "description_numeric_code_hint");
assert.equal(suggestion("line-17").candidates[0].sku, "GOAL-002");
// The two reported reproductions are really these retrievals (no near-but-different code is provable from them).
assert.equal(suggestion("line-25").method, "trigram");
assert.equal(suggestion("line-26").method, "exact");
assert.equal(suggestion("line-26").candidates[0].sku, "ÉX-88");
assert.equal(suggestion("line-30").method, "trigram");
// No sentence may say a printed code is close to, different from, or not the same as the product.
for (const id of Object.keys(expected)) assert.doesNotMatch(reason(id), /does not match|not the catalog|different|differently|close to|not the same|written/i, id);
console.log("plain reasons on real data passed");
