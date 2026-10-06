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

const cases = [
  ["several look alike (3)", row(), suggestion("trigram", [cand("A-1"), cand("A-2"), cand("A-3")], "uncertain", TIER.unresolved), "3 catalog products could match this line; pick the right one."],
  ["several look alike (2), no code", noCode(), suggestion("trigram", [cand("POC-1"), cand("POC-2")], "uncertain", TIER.unresolved), "2 catalog products could match this line; pick the right one."],
  ["nothing matches", row(), suggestion("none", [], "uncertain", TIER.unresolved, {evidence: []}), "No catalog product matches this code or name."],
  ["nothing matches, no code", noCode(), suggestion("none", [], "uncertain", TIER.unresolved), "No catalog product matches this code or name."],
  ["no suggestion at all", row(), null, "No catalog product matches this code or name."],
  ["description code differs from the printed main code", row({description: obs("Fictional ladder POC-0202")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "A code in the description does not match the printed code."],
  ["unmatched labeled token, no code column", noCode({description: obs("Fictional ladder code ZZ-99")}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.conflict), "A code in the description does not match this product."],
  ["printed main code spelled differently, description code differs", row({identifiers: [code("POC0101")], description: obs("Fictional ladder POC-0202")}), suggestion("normalized", [cand("POC-0101")], "uncertain", TIER.conflict), "A code in the description does not match the printed code."],
  ["two different codes printed", row({identifiers: [code("POC-0101"), code("POC-0202")]}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "Two different product codes are printed on this line."],
  ["printed alias differs from main code (conflict)", row({identifiers: [code("OLD-77")], description: obs("Fictional ladder")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "The printed code is not the catalog's main code for this product."],
  ["alias conflict but description also holds a code", row({identifiers: [code("OLD-77")], description: obs("Fictional ladder POC-0202")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "The printed code is not the catalog's main code for this product."],
  ["vendor-prefixed printed code is not called different", row({identifiers: [code("WER POC-0101"), code("OLD-77")], description: obs("Fictional ladder")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "The printed code is not the catalog's main code for this product."],
  ["conflict whose cause cannot be established", row({identifiers: [code("POC-0101"), code("POC0101"), code("OLD-77")], description: obs("Fictional ladder POC-0202")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "The app is not sure enough to confirm this one by itself."],
  ["too many readings", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.tooMany), "This line has too many codes to check against the catalog."],
  ["catalog check skipped", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.skipped), "The app skipped its catalog check on this line; please check the match."],
  ["no code printed, name only", noCode(), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "No product code on this line; matched by name only."],
  ["vendor-prefixed duplicate", row(), suggestion("trigram", [cand("D6224-2"), cand("WERNER D6224-2")], "uncertain", TIER.unresolved), "The catalog has both 'D6224-2' and 'WERNER D6224-2'."],
  ["vendor-prefixed duplicate with dash", row(), suggestion("trigram", [cand("WER-D6224-2"), cand("D6224-2")], "uncertain", TIER.unresolved), "The catalog has both 'D6224-2' and 'WER-D6224-2'."],
  ["hard to read: unclear code", row({identifiers: [code("POC-O101", {state: "uncertain"})]}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["hard to read: other readings", row({quantity: obs("200", {alternative_readings: ["2.00"]})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["hard to read: unreadable description", row({description: obs(null, {state: "unreadable"})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "Part of this line is hard to read."],
  ["not clearly a product", row({row_kind: "unknown", uncertainty: "Fictional ambiguous row"}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "The app could not tell for sure that this line is a product."],
  ["code written differently", row({identifiers: [code("POC0101")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "The printed code is written a little differently from the catalog code."],
  ["customer item number is an alias, written differently", row({identifiers: [coded("CUSTOM77", "customer_item_number")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "The printed code is an alternate code for this product, written a little differently."],
  ["vendor code is an alias, written differently", row({identifiers: [code("OLD77")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "The printed code is an alternate code for this product, written a little differently."],
  ["customer item number that looks like the main code is not claimed", row({identifiers: [coded("POC0101", "customer_item_number")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "The app is not sure enough to confirm this one by itself."],
  ["normalized with no printed code", noCode(), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "The app is not sure enough to confirm this one by itself."],
  ["code is an alternate code", row({identifiers: [code("OLD-77")]}), suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), "The printed code is not the catalog's main code for this product."],
  ["code inside description, no code column", noCode(), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "No code column on this line; the code was found inside the description."],
  ["numeric code inside description", noCode(), suggestion("description_numeric_code_hint", [cand("12345")], "probable", TIER.probable), "No code column on this line; the code was found inside the description."],
  ["description code while printed code misses", row({identifiers: [code("ZZZ-9")]}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "The printed code does not match, but a code in the description does."],
  ["description code only close", noCode(), suggestion("description_code_hint_trigram", [cand("POC-0101")], "probable", TIER.probable), "The code in the description is close to this catalog code, but not the same."],
  ["printed code only close", row({identifiers: [code("POC-O101")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "The printed code or name is close to this product, but not the same."],
  ["ignored readings, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: [{kind: "description_hint_ignored", extractor: "numeric", reason: "measurement", length: 4}]}), "Other codes or sizes on this line were set aside; please check the match."],
  ["ignored code reading, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: [{kind: "code_reading_ignored", extractor: "code_column", reason: "not_a_catalog_code", length: 6}]}), "Other codes or sizes on this line were set aside; please check the match."],
  ["anything else", row(), suggestion("exact", [cand("POC-0101")], "probable", "Something new"), "The app is not sure enough to confirm this one by itself."],
  ["missing row data is safe", null, suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), "The app is not sure enough to confirm this one by itself."],
];
for (const [name, line, s, expected] of cases) assert.equal(api.plainReason(line, s), expected, name);

// Order of precedence: look-alikes beat everything; a conflict beats a hard-to-read field; no match beats unclear readings.
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("trigram", [cand("A"), cand("B")], "uncertain", TIER.unresolved)), "2 catalog products could match this line; pick the right one.");
assert.equal(api.plainReason(row({identifiers: [code("A")], quantity: obs("1", {state: "uncertain"})}), suggestion("exact", [cand("A")], "uncertain", TIER.conflict)), "A code in the description does not match the printed code.");
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("none", [], "uncertain", TIER.unresolved)), "No catalog product matches this code or name.");

// The old catch-all sentence must be unreachable: nothing may say the code and the description "do not agree".
for (const [name, line, s] of cases) assert.doesNotMatch(api.plainReason(line, s), /do not agree/, name);

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
