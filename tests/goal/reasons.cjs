"use strict";
// plainReason: one plain sentence for each line in Check. A table of hand-picked cases built from the strings and
// fields the backend really produces (backend/tiers.py tier_reason, backend/catalog.py reason / method / candidates /
// evidence), including every counterexample reported in review. The same table is also the list of sentences: each
// rule of REASON_RULES must be used by at least one case. tests/goal/reasons-generated.cjs checks all combinations.
// Fictional data only; loads just the marked block of web/local-reader/workflow.js.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {plainReason, plainReasonRule, reasonFacts, REASON_RULES, vendorPrefixPair, hasPrintedCode, hasUnclearReading, unclearFields};", context);
const api = context.api;

// Real tier_reason strings of backend/tiers.py and real retrieval reasons of backend/catalog.py / service.py / tiers.py.
const TIER = {
  unresolved: "Unresolved source evidence, classification or candidate ambiguity",
  conflict: "Code-column and description readings conflict with the candidate",
  probable: "Description, embedded-code, alias or normalized match requires confirmation",
  tooMany: "Too many code-like readings to verify against the catalog",
  skipped: "Catalog check skipped because the lookup budget for this run was spent",
  probableIgnored: "Description, embedded-code, alias or normalized match requires confirmation; 1 other reading(s) ignored (measurement or not a catalog code)",
};
const REASON = {
  empty: "No candidate found in the supplied tenant/vendor catalog",
  noFuzzy: "No candidate found in the supplied tenant/vendor catalog; pg_trgm unavailable, fuzzy retrieval disabled",
  unsearched: "Unknown source row requires an explicit three-way decision",
  failed: "Retrieval input exceeds the bounded search contract; human review required",
  one: "Candidate requires explicit human approval",
  many: "Multiple candidates require human review; no candidate was selected",
};
const obs = (value, over = {}) => ({state: "observed", raw_value: value, alternative_readings: [], ...over});
const code = (value, over = {}) => ({...obs(value, over), source_role: "vendor_sku", source_label: "Code"});
const coded = (value, source_role) => ({...obs(value), source_role, source_label: "Code"});
const blankCell = (label = "Code", over = {}) => ({state: "not_present", raw_value: null, alternative_readings: [], source_role: "vendor_sku", source_label: label, ...over});
const row = (over = {}) => ({row_id: "r", row_kind: "product", uncertainty: null, identifiers: [code("POC-0101")],
  description: obs("Fictional ladder"), quantity: obs("2"), unit: obs("EA"), ...over});
const noCode = (over = {}) => row({identifiers: [], ...over});
const unknownRow = (over = {}) => row({row_kind: "unknown", uncertainty: "Fictional ambiguous row", identifiers: [], ...over});
const cand = (sku, description = "Fictional product " + sku) => ({candidate_id: "id-" + sku, sku, description, method: "x", origin: "catalog"});
const suggestion = (method, candidates, tier, tier_reason, over = {}) => ({method, candidates, tier, tier_reason,
  outcome: candidates.length === 1 ? "suggested" : candidates.length ? "ambiguous" : "no_match", evidence: [],
  reason: candidates.length === 1 ? REASON.one : candidates.length ? REASON.many : REASON.empty, ...over});
const placeholder = () => suggestion("none", [], "uncertain", TIER.unresolved, {reason: REASON.unsearched, retrieval_version: "review-tiers-v1"});

const SURE_NOT = "The app is not sure enough to confirm this one by itself.";
const CONFLICT = "The app found conflicting readings on this line; please check it.";
const HINT = "Matched from a code in the description; please check it against the printed line.";
const NAME = "Matched by an approximate search on the name or code; please check it.";
const NAME_ONLY = "Matched by an approximate search on the description; please check it.";
const IGNORED = "Other codes or sizes on this line were set aside; please check the match.";
const EXACT = "A printed code matched exactly; please check the match against the line.";
const NORM = "Matched after ignoring spaces, punctuation and capital letters in a printed code; please check it.";
const NOT_SEARCHED = "This line was not searched in the catalog: it is not clear what kind of line it is.";
const FOUND_NONE = "The catalog search found no product for this line.";
const NO_HINT_CODE = "The match comes from a code in the description; please check it.";
const ignoredEvidence = [{kind: "description_hint_ignored", extractor: "numeric", reason: "measurement", length: 4}];
// [name, row, suggestion, rule id, sentence]
const cases = [
  ["several look alike (3)", row(), suggestion("trigram", [cand("A-1"), cand("A-2"), cand("A-3")], "uncertain", TIER.unresolved), "look_alikes", "3 catalog products could match this line; pick the right one."],
  ["several look alike (2), no code", noCode(), suggestion("trigram", [cand("POC-1"), cand("POC-2")], "uncertain", TIER.unresolved), "look_alikes", "2 catalog products could match this line; pick the right one."],
  ["vendor-prefixed duplicate", row(), suggestion("trigram", [cand("D6224-2"), cand("WERNER D6224-2")], "uncertain", TIER.unresolved), "look_alikes_twin", "The catalog has both 'D6224-2' and 'WERNER D6224-2'."],
  ["vendor-prefixed duplicate with dash", row(), suggestion("trigram", [cand("WER-D6224-2"), cand("D6224-2")], "uncertain", TIER.unresolved), "look_alikes_twin", "The catalog has both 'D6224-2' and 'WER-D6224-2'."],
  // Finding 1: an empty candidate list of a line that was never searched is not "nothing matches".
  ["unknown line, never searched (reported case)", unknownRow({identifiers: [code("GOAL-002")], description: obs("Synthetic vermilion bracket")}), placeholder(), "not_searched", NOT_SEARCHED],
  ["searched, nothing found", row(), suggestion("none", [], "uncertain", TIER.unresolved), "searched_none", FOUND_NONE],
  ["searched, nothing found, no code", noCode(), suggestion("none", [], "uncertain", TIER.unresolved), "searched_none", FOUND_NONE],
  ["product line, price note, nothing found", row({uncertainty: "Unit price may exclude tax"}), suggestion("none", [], "uncertain", TIER.unresolved), "searched_none", FOUND_NONE],
  ["nothing at all to search with", noCode({description: {state: "not_applicable", raw_value: null, alternative_readings: []}}), suggestion("none", [], "uncertain", TIER.unresolved), "nothing_to_search", "This line has no code or description to search the catalog with."],
  ["search input too large", row(), suggestion("none", [], "uncertain", TIER.unresolved, {reason: REASON.failed}), "search_failed", "The app could not run its catalog search on this line; please check it."],
  ["fuzzy search unavailable", row(), suggestion("none", [], "uncertain", TIER.unresolved, {reason: REASON.noFuzzy}), "no_suggestion", "No suggestion is available for this line."],
  ["no suggestion at all", row(), null, "no_suggestion", "No suggestion is available for this line."],
  ["unknown reason text, no candidate", row(), suggestion("none", [], "uncertain", TIER.unresolved, {reason: "Something new"}), "no_suggestion", "No suggestion is available for this line."],
  ["placeholder text on a product row stays neutral", row(), placeholder(), "no_suggestion", "No suggestion is available for this line."],
  ["conflict, description holds another code", row({description: obs("Fictional ladder POC-0202")}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.conflict), "conflict", CONFLICT],
  ["conflict, no code column", noCode({description: obs("Fictional ladder code ZZ-99")}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.conflict), "conflict", CONFLICT],
  ["conflict, non-ASCII code", row({identifiers: [code("ÉX-88")]}), suggestion("exact", [cand("ÉX-88")], "uncertain", TIER.conflict), "conflict", CONFLICT],
  ["too many readings", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.tooMany), "too_many_readings", "This line has too many code-like readings to check against the catalog."],
  ["catalog check skipped", row(), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.skipped), "check_skipped", "The app skipped its catalog check on this line; please check the match."],
  ["hard to read: unclear code", row({identifiers: [code("POC-O101", {state: "uncertain"})]}), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "unclear_reading", "The app was unsure how to read this line's code."],
  ["hard to read: other readings of the quantity", row({quantity: obs("200", {alternative_readings: ["2.00"]})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "unclear_reading", "The app was unsure how to read this line's quantity."],
  ["hard to read: unreadable description", row({description: obs(null, {state: "unreadable"})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "unclear_reading", "The app was unsure how to read this line's description."],
  ["hard to read: code, quantity and unit", row({identifiers: [code("POC-O101", {state: "uncertain"})], quantity: obs("1", {state: "uncertain"}), unit: obs("EA", {state: "uncertain"})}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "unclear_reading", "The app was unsure how to read this line's code, quantity and unit."],
  ["not clearly a product (unknown kind with a candidate)", unknownRow(), suggestion("trigram", [cand("POC-0101")], "uncertain", TIER.unresolved), "not_a_product", "The app could not tell for sure that this line is a product."],
  // Finding 2: a note about price or tax is not an uncertain classification.
  ["product line with a price note (reported case)", row({uncertainty: "Unit price may exclude tax; product classification is clear"}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "row_note", "The reading of this line carries a note: “Unit price may exclude tax; product classification is clear”."],
  ["product line with a long note", row({uncertainty: "x".repeat(300)}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "row_note", "The reading of this line carries a note: “" + "x".repeat(109) + "…”."],
  ["product line, note with markup", row({uncertainty: "<b>total</b>   per box"}), suggestion("exact", [cand("POC-0101")], "uncertain", TIER.unresolved), "row_note", "The reading of this line carries a note: “<b>total</b> per box”."],
  ["a code under another kind of label is still a code", row({identifiers: [{...code("POC-0101"), source_label: "Item"}]}), suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), "exact", EXACT],
  ["normalized match, vendor code", row({identifiers: [code("POC0101")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "normalized", NORM],
  ["normalized match, customer role", row({identifiers: [coded("CUSTOM77", "customer_item_number")]}), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "normalized", NORM],
  ["normalized with no printed code", noCode(), suggestion("normalized", [cand("POC-0101")], "probable", TIER.probable), "not_sure", SURE_NOT],
  ["exact printed code, probable", row({identifiers: [code("OLD-77")]}), suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), "exact", EXACT],
  ["exact non-ASCII value equal to the catalog code", row({identifiers: [coded("ÉX-88", "customer_item_number")]}), suggestion("exact", [cand("ÉX-88")], "probable", TIER.probable), "exact", EXACT],
  // Finding 3: a blank cell under a printed label is not "no code column".
  ["blank Code cell, code in the description (reported case)", row({identifiers: [blankCell("Code")], description: obs("Synthetic vermilion bracket code GOAL-002")}), suggestion("description_code_hint", [cand("GOAL-002")], "probable", TIER.probable), "hint_blank_cell", "No code was read under “Code”; the match comes from a code in the description."],
  ["blank cells under two labels", row({identifiers: [blankCell("Code"), blankCell("Item no.", {source_role: "customer_item_number"})]}), suggestion("description_code_hint", [cand("GOAL-002")], "probable", TIER.probable), "hint_blank_cell", "No code was read under “Code” and “Item no.”; the match comes from a code in the description."],
  ["blank cell without a printed label", row({identifiers: [blankCell(null)]}), suggestion("description_code_hint", [cand("GOAL-002")], "probable", TIER.probable), "hint_no_code", NO_HINT_CODE],
  ["no identifier entry at all, code in the description", noCode(), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "hint_no_code", NO_HINT_CODE],
  ["numeric code inside description", noCode(), suggestion("description_numeric_code_hint", [cand("12345")], "probable", TIER.probable), "hint_no_code", NO_HINT_CODE],
  ["description code, printed code of another value", row({identifiers: [code("ZZZ-9")]}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "hint_with_code", HINT],
  ["description code, printed code equals the product code", row({identifiers: [coded("POC-0101", "customer_item_number")], description: obs("Fictional ladder code POC-0101")}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "hint_with_code", HINT],
  ["numeric description code, printed code", row({identifiers: [coded("12345", "customer_item_number")], description: obs("Fictional hinge 12345")}), suggestion("description_numeric_code_hint", [cand("12345")], "probable", TIER.probable), "hint_with_code", HINT],
  ["a blank cell beside a printed code", row({identifiers: [blankCell("Code"), code("ZZZ-9", {source_label: "Item"})]}), suggestion("description_code_hint", [cand("POC-0101")], "probable", TIER.probable), "hint_with_code", HINT],
  ["description code only roughly fits", noCode(), suggestion("description_code_hint_trigram", [cand("POC-0101")], "probable", TIER.probable), "hint_rough", "Matched approximately from a code in the description; please check it."],
  // Finding 4: a name search says how the match was found, never that no code is printed.
  ["name search, no identifier, code printed in the description (reported case)", noCode({description: obs("Synthetic ultramarine locking latch assembly code 77")}), suggestion("trigram", [cand("77")], "probable", TIER.probable), "approximate_name", NAME_ONLY],
  ["name search, no identifier", noCode(), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "approximate_name", NAME_ONLY],
  ["name search, blank code cell", row({identifiers: [blankCell("Code")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "approximate_name", NAME_ONLY],
  ["name match, exact name, unrelated customer-role code", row({identifiers: [coded("CUST-5", "customer_item_number")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "approximate_code", NAME],
  ["name match, printed code equals the product code", row({identifiers: [coded("POC-0101", "customer_item_number")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "approximate_code", NAME],
  ["name match, printed code only roughly fits", row({identifiers: [code("POC-O101")]}), suggestion("trigram", [cand("POC-0101")], "probable", TIER.probable), "approximate_code", NAME],
  ["ignored readings, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: ignoredEvidence}), "set_aside", IGNORED],
  ["ignored code reading, nothing more specific", row(), suggestion("exact", [cand("POC-0101")], "probable", TIER.probableIgnored, {evidence: [{kind: "code_reading_ignored", extractor: "code_column", reason: "not_a_catalog_code", length: 6}]}), "set_aside", IGNORED],
  ["anything else, printed code", row(), suggestion("exact", [cand("POC-0101")], "probable", "Something new"), "exact", EXACT],
  ["anything else, no printed code", noCode(), suggestion("exact", [cand("POC-0101")], "probable", "Something new"), "not_sure", SURE_NOT],
  ["a certain line moved to Check by the person", row(), suggestion("exact", [cand("POC-0101")], "certain", "Unique literal code-column match; explicit human approval still required"), "exact", EXACT],
  ["a certain tier that matches no rule", noCode(), suggestion("exact", [cand("POC-0101")], "certain", "Something new"), "check", "Please check this match against the line."],
  ["missing row data is safe", null, suggestion("exact", [cand("POC-0101")], "probable", TIER.probable), "not_sure", SURE_NOT],
];
for (const [name, line, s, id, expected] of cases) {
  const got = api.plainReasonRule(line, s);
  assert.equal(got.id, id, name + " (rule)");
  assert.equal(got.text, expected, name);
  assert.equal(api.plainReason(line, s), expected, name);
}

// Order of precedence: look-alikes beat everything; no search result beats a hard-to-read field; a conflict beats a
// hard-to-read field.
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("trigram", [cand("A"), cand("B")], "uncertain", TIER.unresolved)), "2 catalog products could match this line; pick the right one.");
assert.equal(api.plainReason(row({identifiers: [code("A")], quantity: obs("1", {state: "uncertain"})}), suggestion("exact", [cand("A")], "uncertain", TIER.conflict)), CONFLICT);
assert.equal(api.plainReason(row({quantity: obs("1", {state: "uncertain"})}), suggestion("none", [], "uncertain", TIER.unresolved)), FOUND_NONE);

// Every rule is used by the table (no sentence outside the table can ever be shown) and every case names a real rule.
const ruleIds = api.REASON_RULES.map(rule => rule.id);
assert.equal(new Set(ruleIds).size, ruleIds.length, "rule ids are unique");
const used = new Set(cases.map(item => item[3]));
for (const id of ruleIds) assert.ok(used.has(id), "unused rule: " + id);
for (const id of used) assert.ok(ruleIds.includes(id), "unknown rule: " + id);

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
assert.deepEqual(Array.from(api.unclearFields(row({description: obs("x", {state: "unreadable"}), unit: obs("EA", {alternative_readings: ["BX"]})}))), ["description", "unit"]);

// The rule: no sentence may claim a mismatch, closeness or difference between the printed code and the product, a
// missing column, or that no code exists on the line.
const NEVER = /do not agree|does not match|not the (?:catalog|same)|close to|different|differently|written|no code column|no product code|name only|no catalog product matches/i;
for (const [name, line, s, id] of cases) if (id !== "row_note") assert.doesNotMatch(api.plainReason(line, s), NEVER, name);
// Plain words only: none of the internal terms may reach a person (the quoted note is the line's own text).
const banned = /tier|trigram|canonical|evidence|candidate|retriev|normaliz|method|sku|similar/i;
for (const [name, line, s, id] of cases) if (id !== "row_note") assert.doesNotMatch(api.plainReason(line, s), banned, name);
// Every sentence is short and ends like a sentence.
for (const [name, line, s, id] of cases) {
  const text = api.plainReason(line, s);
  assert.ok(text.length <= (id === "row_note" ? 160 : 100) && /[.]$|[.]”[.]$/.test(text), name + ": " + text);
}
console.log("plain reasons passed (" + cases.length + " cases, " + ruleIds.length + " sentences)");
