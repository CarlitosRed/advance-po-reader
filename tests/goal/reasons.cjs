"use strict";
// plainReason: one plain sentence for each line in Check. A table of cases built from the strings and fields the
// backend really produces (backend/tiers.py tier_reason, backend/catalog.py method / candidates / evidence).
// Fictional data only; loads just the marked block of web/local-reader/workflow.js.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {plainReason, vendorPrefixPair, hasPrintedCode, hasUnclearReading};", context);
const api = context.api;

// Real tier_reason strings of backend/tiers.py.
const TIER = {
  unresolved: "Unresolved source evidence, classification or candidate ambiguity",
  conflict: "Code-column and description readings conflict with the candidate",
  probable: "Description, embedded-code, alias or normalized match requires confirmation",
  tooMany: "Too many code-like readings to verify against the catalog",
  skipped: "Catalog check skipped because the lookup budget for this run was spent",
  probableIgnored: "Description, embedded-code, alias or normalized match requires confirmation; 1 other reading(s) ignored (measurement or not a catalog code)",
};
const obs = (value, over = {}) => ({state: "observed", raw_value: value, alternative_readings: [], ...over});
const code = (value, over = {}) => ({...obs(value, over), source_role: "vendor_sku"});
const coded = (value, source_role) => ({...obs(value), source_role});
const row = (over = {}) => ({row_id: "r", row_kind: "product", uncertainty: null, identifiers: [code("POC-0101")],
  description: obs("Fictional ladder"), quantity: obs("2"), unit: obs("EA"), ...over});
const noCode = (over = {}) => row({identifiers: [], ...over});
const cand = (sku, description = "Fictional product " + sku) => ({candidate_id: "id-" + sku, sku, description, method: "x", origin: "catalog"});
const suggestion = (method, candidates, tier, tier_reason, over = {}) => ({method, candidates, tier, tier_reason, outcome: candidates.length === 1 ? "suggested" : candidates.length ? "ambiguous" : "no_match", evidence: [], ...over});

const SURE_NOT = "The app is not sure enough to confirm this one by itself.";
const CONFLICT = "The app found conflicting readings on this line; please check it.";
const HINT = "Matched from a code in the description; please check it against the printed line.";
const NAME = "Matched by an approximate search on the name or code; please check it.";
const IGNORED = "Other codes or sizes on this line were set aside; please check the match.";
const EXACT = "A printed code matched exactly; please check the match against the line.";
const NORM = "Matched after ignoring spaces and punctuation in a printed code; please check it.";
const cases = [
  ["several look alike (3)", row(), suggestion("trigram", [cand("A-1"), cand("A-2"), cand("A-3")], "uncertain", TIER.unresolved), "3 catalog products could match this line; pick the right one."],
  ["several look alike (2), no code", noCode(), suggestion("trigram", [cand("POC-1"), cand("POC-2")], "uncertain", TIER.unresolved), "2 catalog products could match this line; pick the right one."],
  ["nothing matches", row(), suggestion("none", [], "uncertain", TIER.unresolved, {evidence: []}), "No catalog product matches this code or name."],
  ["nothing matches, no code", noCode(), suggestion("none", [], "uncertain", TIER.unresolved), "No catalog product matches this code or name."],
  ["no suggestion at all", row(), null, "No catalog product matches this code or name."],
  ["conflict, description holds another code", row({description: obs("Fictional ladder POC-0202")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), CONFLICT],
  ["conflict, no code column", noCode({description: obs("Fictional ladder code ZZ-99")}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.conflict), CONFLICT],
  ["conflict, two printed codes", row({identifiers: [code("POC-0101"), code("POC-0202")]}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), CONFLICT],
  ["conflict, printed alias", row({identifiers: [code("OLD-77")]}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), CONFLICT],
  ["conflict, non-ASCII code", row({identifiers: [code("ÉX-88")]}), suggestion("exact", [cand("ÉX-88")], "uncertain", TIER.conflict), CONFLICT],
  ["too many readings", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.tooMany), "This line has too many codes to check against the catalog."],
  ["catalog check skipped", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.skipped), "The app skipped its catalog check on this line; please check the match."],
  ["no code printed, name only", noCode(), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "No product code on this line; matched by name only."],
  ["vendor-prefixed duplicate", row(), suggestion("trigram", [cand("D6224-2"), cand("WERNER D6224-2")], "uncertain", TIER.unresolved), "The catalog has both 'D6224-2' and 'WERNER D6224-2'."],
  ["vendor-prefixed duplicate with dash", row(), suggestion("trigram", [cand("WER-D6224-2"), cand("D6224-2")], "uncertain", TIER.unresolved), "The catalog has both 'D6224-2' and 'WER-D6224-2'."],
  ["hard to read: unclear code", row({identifiers: [code("POC-O101", {state: "uncertain"})]}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["hard to read: other readings", row({quantity: obs("200", {alternative_readings: ["2.00"]})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["hard to read: unreadable description", row({description: obs(null, {state: "unreadable"})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["not clearly a product", row({row_kind: "unknown", uncertainty: "Fictional ambiguous row"}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "The app could not tell for sure that this line is a product."],
  ["normalized match, vendor code", row({identifiers: [code("POC0101")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), NORM],
  ["normalized match, customer role", row({identifiers: [coded("CUSTOM77", "customer_item_number")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), NORM],
  ["normalized with no printed code", noCode(), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), SURE_NOT],
  ["exact printed code, probable", row({identifiers: [code("OLD-77")]}), suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), EXACT],
  ["exact non-ASCII value equal to the catalog code (reported case)", row({identifiers: [coded("ÉX-88", "customer_item_number")]}), suggestion("exact", [cand("ÉX-88")], "probable", TIER.probable), EXACT],
  ["code inside description, no code column", noCode(), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "No code column on this line; the code was found inside the description."],
  ["numeric code inside description", noCode(), suggestion("description_numeric_code_hint", [cand("12345")], "probable", TIER.probable), "No code column on this line; the code was found inside the description."],
  ["description code, printed code of another value", row({identifiers: [code("ZZZ-9")]}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), HINT],
  ["description code, printed code equals the product code", row({identifiers: [coded("POC-0101", "customer_item_number")], description: obs("Fictional ladder code POC-0101")}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), HINT],
  ["numeric description code, printed code", row({identifiers: [coded("12345", "customer_item_number")], description: obs("Fictional hinge 12345")}), suggestion("description_numeric_code_hint", [cand("12345")], "probable", TIER.probable), HINT],
  ["description code, vendor-prefixed printed code", row({identifiers: [code("WER POC-0101")]}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), HINT],
  ["description code only roughly fits", noCode(), suggestion("description_code_hint_trigram", [cand("POC-0101")], "probable", TIER.probable), "Matched approximately from a code in the description; please check it."],
  ["name match, exact name, unrelated customer-role code (reported case)", row({identifiers: [coded("CUST-5", "customer_item_number")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), NAME],
  ["name match, printed code equals the product code", row({identifiers: [coded("POC-0101", "customer_item_number")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), NAME],
  ["name match, printed code only roughly fits", row({identifiers: [code("POC-O101")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), NAME],
  ["ignored readings, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: [{kind: "description_hint_ignored", extractor: "numeric", reason: "measurement", length: 4}]}), IGNORED],
  ["ignored code reading, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: [{kind: "code_reading_ignored", extractor: "code_column", reason: "not_a_catalog_code", length: 6}]}), IGNORED],
  ["anything else, printed code", row(), suggestion("exact", [cand("POC-0101")], "probable", "Something new"), EXACT],
  ["anything else, no printed code", noCode(), suggestion("exact", [cand("POC-0101")], "probable", "Something new"), SURE_NOT],
  ["missing row data is safe", null, suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), SURE_NOT],
];
for (const [name, line, s, expected] of cases) assert.equal(api.plainReason(line, s), expected, name);

// Order of precedence: look-alikes beat everything; a conflict beats a hard-to-read field; no match beats unclear readings.
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("trigram", [cand("A"), cand("B")], "uncertain", TIER.unresolved)), "2 catalog products could match this line; pick the right one.");
assert.equal(api.plainReason(row({identifiers: [code("A")], quantity: obs("1", {state: "uncertain"})}), suggestion("exact", [cand("A")], "uncertain", TIER.conflict)), CONFLICT);
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("none", [], "uncertain", TIER.unresolved)), "No catalog product matches this code or name.");

// The rule: no sentence may claim a mismatch, closeness or difference between the printed code and the product.
for (const [name, line, s] of cases) assert.doesNotMatch(api.plainReason(line, s), /do not agree|does not match|not the (?:catalog|same)|close to|different|differently|written/i, name);
// Every sentence that can be shown, with the fact about the API data it relies on. Nothing outside this list exists.
const FACTS = {
  "N catalog products could match this line; pick the right one.": "candidates.length > 1 (the count is printed)",
  "The catalog has both X and Y.": "two candidate SKUs literally end with one another after a letters-only prefix",
  "No catalog product matches this code or name.": "candidates is empty (or there is no suggestion)",
  "This line has too many codes to check against the catalog.": "tier_reason says too many code-like readings",
  "The app skipped its catalog check on this line; please check the match.": "tier_reason says the lookup budget was spent",
  [CONFLICT]: "tier_reason says the readings conflict",
  "Part of this line is hard to read.": "a field has state uncertain/unreadable or alternative readings",
  "The app could not tell for sure that this line is a product.": "row_kind is not product, or the row has an uncertainty note",
  [HINT]: "method is a description hint and the row has a printed identifier",
  "No code column on this line; the code was found inside the description.": "method is a description hint and the row has no identifier",
  "Matched approximately from a code in the description; please check it.": "method is description_code_hint_trigram",
  [NAME]: "method is trigram and the row has a printed identifier",
  "No product code on this line; matched by name only.": "method is trigram and the row has no identifier",
  [IGNORED]: "evidence has a description_hint_ignored or code_reading_ignored entry",
  [NORM]: "method is normalized and the row has a printed identifier",
  [EXACT]: "method is exact and the row has a printed identifier",
  [SURE_NOT]: "none of the facts above (neutral)",
};
const keyOf = text => text.replace(/^\d+ catalog products/, "N catalog products").replace(/^The catalog has both .*$/, "The catalog has both X and Y.");
for (const [name, line, s] of cases) assert.ok(keyOf(api.plainReason(line, s)) in FACTS, name + ": " + api.plainReason(line, s));
const shown = new Set(cases.map(([, line, s]) => keyOf(api.plainReason(line, s))));
for (const text of Object.keys(FACTS)) assert.ok(shown.has(text), "unused sentence: " + text);

// Helpers.
assert.deepEqual(Array.from(api.vendorPrefixPair([cand("WERNER D6224-2"), cand("D6224-2")])), ["D6224-2", "WERNER D6224-2"]);
assert.equal(api.vendorPrefixPair([cand("D6224-2"), cand("D6224-3")]), null);
assert.equal(api.vendorPrefixPair([cand("XD6224-2"), cand("D6224-2")]), null, "the shorter code must be the whole trailing token");
assert.equal(api.vendorPrefixPair([cand("W1 D6224-2"), cand("D6224-2")]), null, "a prefix with digits is not a vendor prefix");
assert.equal(api.vendorPrefixPair([cand("D6224-2")]), null);
assert.equal(api.hasPrintedCode(row()), true);
assert.equal(api.hasPrintedCode(noCode()), false);
assert.equal(api.hasPrintedCode(row({identifiers: [code("  ")]})), false, "a blank code is no code");
assert.equal(api.hasUnclearReading(row()), false);

// Plain words only: none of the internal terms may reach a person.
const banned = /tier|trigram|canonical|evidence|candidate|retriev|normaliz|method|sku|similar/i;
for (const [name, line, s] of cases) assert.doesNotMatch(api.plainReason(line, s), banned, name);
// Every sentence is short and ends like a sentence.
for (const [name, line, s] of cases) {
  const text = api.plainReason(line, s);
  assert.ok(text.length <= 90 && /[.]$/.test(text), name + ": " + text);
}
console.log("plain reasons passed (" + cases.length + " cases)");
