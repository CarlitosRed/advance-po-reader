"use strict";
// Regressions for the four review findings of PR #21 round 5, plus controls, on REAL review-API suggestions (fictional
// run written by test_goal_reasons.py). Each case pairs the real API facts with the one sentence they prove.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {plainReason, plainReasonRule};", context);
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const suggestion = id => data.suggestions.find(s => s.row_id === id);
const row = id => data.rows.find(r => r.row_id === id);
const rule = id => context.api.plainReasonRule(row(id), suggestion(id));
const facts = id => {
  const s = suggestion(id);
  return {method: s.method, tier: s.tier, candidates: s.candidates.map(c => c.sku), reason: s.reason};
};

const NOT_SEARCHED = "This line was not searched in the catalog: it is not clear what kind of line it is.";
const EXACT = "A printed code matched exactly; please check the match against the line.";
const NOTE = "The reading of this line carries a note: “Unit price may exclude tax; product classification is clear”.";
const BLANK_CELL = "No code was read under “Code”; the match comes from a code in the description.";
const NO_CODE = "No code was read on this line; the match comes from a code in the description.";
const NAME_ONLY = "Matched by an approximate search on the description; please check it.";
const NAME_OR_CODE = "Matched by an approximate search on the name or code; please check it.";
const FOUND_NONE = "The catalog search found no product for this line.";
const NORM = "Matched after ignoring spaces, punctuation and capital letters in a printed code; please check it.";
const seen = {};
const expect = (id, ruleId, text, check) => {
  const got = rule(id);
  seen[id] = {got: got.text, facts: facts(id)};
  assert.equal(got.id, ruleId, id + " rule " + JSON.stringify(seen[id]));
  assert.equal(got.text, text, id);
  if (check) check(suggestion(id), row(id));
};
// Finding 1: an unknown row is never searched (empty placeholder); the identical product-classified row finds GOAL-002.
expect("line-1", "not_searched", NOT_SEARCHED, s => {
  assert.equal(s.candidates.length, 0);
  assert.match(s.reason, /three-way decision/);
});
expect("line-2", "exact", EXACT, s => {
  assert.deepEqual(s.candidates.map(c => c.sku), ["GOAL-002"]);
  assert.equal(s.method, "exact");
});
// Control: a product row that WAS searched and found nothing.
expect("line-8", "searched_none", FOUND_NONE, s => {
  assert.equal(s.candidates.length, 0);
  assert.equal(s.reason, "No candidate found in the supplied tenant/vendor catalog");
});
// Finding 2: a price/tax note on a clearly classified product row is quoted, never turned into "not sure it is a product".
expect("line-3", "row_note", NOTE, (s, r) => {
  assert.equal(r.row_kind, "product");
  assert.equal(s.tier, "uncertain");
  assert.equal(s.candidates[0].sku, "GOAL-002");
});
// Finding 3: an empty Code cell (identifier not_present, label Code) beside a code in the description.
expect("line-4", "hint_blank_cell", BLANK_CELL, (s, r) => {
  assert.equal(s.method, "description_code_hint");
  assert.equal(r.identifiers[0].state, "not_present");
  assert.equal(r.identifiers[0].source_label, "Code");
  assert.equal(r.identifiers[0].raw_value, null);
});
// Control: the same description with no identifier entry at all.
expect("line-5", "hint_no_code", NO_CODE, s => assert.equal(s.method, "description_code_hint"));
// Finding 4: a short numeric code printed in the description that the bounded extractors skip; found by the name search.
expect("line-6", "approximate_name", NAME_ONLY, (s, r) => {
  assert.equal(s.method, "trigram");
  assert.deepEqual(s.candidates.map(c => c.sku), ["77"]);
  assert.match(r.description.raw_value, /code 77$/);
});
// Control: the same name search with an unrelated printed customer number.
expect("line-7", "approximate_code", NAME_OR_CODE, s => assert.equal(s.method, "trigram"));
// Control: a vendor code that differs only in capitals/punctuation is a normalized match (and says so completely).
expect("line-9", "normalized", NORM, s => assert.equal(s.method, "normalized"));
// Control: too many identifiers to search at all.
{
  expect("line-10", "search_failed", "The app could not run its catalog search on this line; please check it.", s => {
    assert.equal(s.candidates.length, 0);
    assert.match(s.reason, /bounded search contract/);
  });
}
if (process.env.REASONS_DUMP) console.log(JSON.stringify(seen, null, 1));
console.log("plain reasons truth regressions passed (" + Object.keys(seen).length + " real-API cases)");
