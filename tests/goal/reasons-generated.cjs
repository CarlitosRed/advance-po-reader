"use strict";
// Generated check of plainReason: ALL combinations of the API facts a sentence can depend on (row kind, row note,
// retrieval result and reason text, method, tier and tier_reason, identifier states / labels / values, description,
// quantity and unit readings, ignored-reading evidence). No sampling, no randomness.
// For every combination, against an independent oracle written here over the RAW inputs (not over reasonFacts):
//   1. soundness: the sentence shown is one whose precondition holds for that combination;
//   2. priority: it is the first holding precondition in the documented order, so there is exactly one primary reason;
//   3. the neutral fallback is used only when no more specific precondition holds.
//   4. no unproven negative claim: a precondition is not enough for a sentence that says "no/not/none ... read/found/printed/
//      shown". Every such sentence must be scoped to what the precondition proves (see NEGATIVE_CLAIMS): the one scoped to
//      a printed label is checked against the not_present identifier of exactly that label; the "search found no product"
//      one against the API's own finished-empty reason. A global "no code was read" fails here for every combination.
// And over the whole space: every sentence is reachable, and no sentence is shown outside its precondition.
// Fictional data only; loads just the marked block of web/local-reader/workflow.js.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "workflow.js"), "utf8");
const block = source.slice(source.indexOf("/* tabs:start */"), source.indexOf("/* tabs:end */"));
const context = vm.createContext({});
vm.runInContext(block + "\nthis.api = {plainReasonRule, REASON_RULES};", context);
const {plainReasonRule, REASON_RULES} = context.api;

const EMPTY = "No candidate found in the supplied tenant/vendor catalog";
const REASONS = {
  empty: EMPTY,
  noFuzzy: EMPTY + "; pg_trgm unavailable, fuzzy retrieval disabled",
  unsearched: "Unknown source row requires an explicit three-way decision",
  failed: "Retrieval input exceeds the bounded search contract; human review required",
  other: "Something new",
  one: "Candidate requires explicit human approval",
  many: "Multiple candidates require human review; no candidate was selected",
};
const TIER_REASONS = [
  "Unresolved source evidence, classification or candidate ambiguity",
  "Code-column and description readings conflict with the candidate",
  "Description, embedded-code, alias or normalized match requires confirmation",
  "Too many code-like readings to verify against the catalog",
  "Catalog check skipped because the lookup budget for this run was spent",
  "Description, embedded-code, alias or normalized match requires confirmation; 1 other reading(s) ignored (measurement or not a catalog code)",
  "Something new",
];
const cand = sku => ({candidate_id: "id-" + sku, sku, description: "Fictional " + sku, method: "x", origin: "catalog"});
const obs = (value, over = {}) => ({state: "observed", raw_value: value, alternative_readings: [], ...over});
const ident = (state, raw, label, role = "vendor_sku", alternatives = []) =>
  ({state, raw_value: raw, source_label: label, source_role: role, alternative_readings: alternatives});

// ---- the dimensions (each value is a concrete thing the API can return) ----
const ROW_KINDS = ["product", "unknown", null];                                   // null = no row data
const NOTES = [null, "Unit price may exclude tax"];
const RETRIEVALS = [];                                                              // [label, candidates, reason, methods]
RETRIEVALS.push(["finished empty", [], REASONS.empty, ["none", "trigram"]]);
RETRIEVALS.push(["unknown row not searched", [], REASONS.unsearched, ["none"]]);
RETRIEVALS.push(["search input too large", [], REASONS.failed, ["none"]]);
RETRIEVALS.push(["fuzzy search unavailable", [], REASONS.noFuzzy, ["none"]]);
RETRIEVALS.push(["other reason, no candidate", [], REASONS.other, ["none"]]);
RETRIEVALS.push(["no suggestion", null, null, ["none"]]);
RETRIEVALS.push(["one candidate", [cand("POC-0101")], REASONS.one,
  ["exact", "normalized", "trigram", "description_code_hint", "description_numeric_code_hint", "description_code_hint_trigram", "none"]]);
RETRIEVALS.push(["two candidates", [cand("POC-1"), cand("POC-2")], REASONS.many, ["trigram", "exact"]]);
RETRIEVALS.push(["vendor-prefixed twin", [cand("D6224-2"), cand("WERNER D6224-2")], REASONS.many, ["trigram", "exact"]]);
const TIERS = ["probable", "uncertain", "certain"];
const IDENTIFIERS = [
  ["none", []],
  ["observed code", [ident("observed", "POC-0101", "Code")]],
  ["observed customer-role code", [ident("observed", "CUST-5", "Code", "customer_item_number")]],
  ["blank Code cell", [ident("not_present", null, "Code")]],
  ["blank cell, no label", [ident("not_present", null, null)]],
  ["not applicable", [ident("not_applicable", null, "Code")]],
  ["blank cells under two labels", [ident("not_present", null, "Code"), ident("not_present", null, "Item")]],
  ["blank cell and a code", [ident("not_present", null, "Code"), ident("observed", "ZZ-9", "Item")]],
  ["unclear code", [ident("uncertain", "POC-O101", "Code")]],
  ["code with another reading", [ident("observed", "POC-0101", "Code", "vendor_sku", ["POC-O101"])]],
];
const DESCRIPTIONS = [
  ["text", obs("Fictional ladder code 77")],
  ["blank", {state: "not_applicable", raw_value: null, alternative_readings: []}],
  ["unreadable", obs(null, {state: "unreadable"})],
  ["with another reading", obs("Fictional ladder", {alternative_readings: ["Fictional ladders"]})],
];
const QUANTITY_UNIT = [
  ["clear", obs("2"), obs("EA")],
  ["unclear quantity", obs("2", {state: "uncertain"}), obs("EA")],
  ["unclear unit", obs("2"), obs("EA", {alternative_readings: ["BX"]})],
];
const EVIDENCE = [[], [{kind: "description_hint_ignored", extractor: "numeric", reason: "measurement", length: 4}],
  [{kind: "code_reading_ignored", extractor: "code_column", reason: "not_a_catalog_code", length: 6}]];

// ---- the independent oracle: for each sentence, when is it TRUE, over raw inputs ----
const blank = value => value === null || value === undefined || String(value).trim() === "";
const unclear = item => Boolean(item) && (item.state === "uncertain" || item.state === "unreadable" || (item.alternative_readings || []).length > 0);
const ORDER = ["look_alikes_twin", "look_alikes", "not_searched", "search_failed", "nothing_to_search", "searched_none", "no_suggestion",
  "too_many_readings", "check_skipped", "conflict", "unclear_reading", "not_a_product", "row_note", "hint_with_code", "hint_blank_cell",
  "hint_no_code", "hint_rough", "approximate_code", "approximate_name", "set_aside", "normalized", "exact", "not_sure", "check"];
function twin(skus) {
  return skus.some(a => skus.some(b => a !== b && a.length > b.length &&
    new RegExp("^(?:[A-Za-z]+[ /-])+$").test(a.slice(0, a.length - b.length)) && a.toUpperCase().endsWith(b.toUpperCase())));
}
function truth(id, row, s) {
  const candidates = s ? s.candidates : [];
  const none = candidates.length === 0;
  const reason = s ? s.reason : "";
  const printed = row ? (row.identifiers || []).some(item => !blank(item.raw_value)) : false;
  const tierReason = s ? s.tier_reason : "";
  const method = s ? s.method : "none";
  const labels = row ? (row.identifiers || []).filter(item => item.state === "not_present" && blank(item.raw_value) && !blank(item.source_label)) : [];
  const hint = method === "description_code_hint" || method === "description_numeric_code_hint";
  switch (id) {
    case "look_alikes_twin": return candidates.length > 1 && twin(candidates.map(c => c.sku));
    case "look_alikes": return candidates.length > 1;
    case "not_searched": return none && /three-way/.test(reason) && Boolean(row) && row.row_kind === "unknown";
    case "search_failed": return none && /bounded search contract/.test(reason);
    case "nothing_to_search": return none && reason === EMPTY && method === "none" && !printed && Boolean(row) && blank(row.description.raw_value);
    case "searched_none": return none && reason === EMPTY && method === "none";
    case "no_suggestion": return none;
    case "too_many_readings": return tierReason.startsWith("Too many code-like readings");
    case "check_skipped": return tierReason.includes("lookup budget");
    case "conflict": return tierReason.includes("readings conflict with the candidate");
    case "unclear_reading": return Boolean(row) && [...row.identifiers, row.description, row.quantity, row.unit].some(unclear);
    case "not_a_product": return Boolean(row) && row.row_kind === "unknown";
    case "row_note": return Boolean(row) && !blank(row.uncertainty);
    case "hint_with_code": return hint && printed;
    case "hint_blank_cell": return hint && !printed && labels.length > 0;
    case "hint_no_code": return hint && !printed;
    case "hint_rough": return method === "description_code_hint_trigram";
    case "approximate_code": return method === "trigram" && printed;
    case "approximate_name": return method === "trigram" && !printed;
    case "set_aside": return s.evidence.some(item => item.kind === "description_hint_ignored" || item.kind === "code_reading_ignored");
    case "normalized": return method === "normalized" && printed;
    case "exact": return method === "exact" && printed;
    case "not_sure": return s.tier !== "certain";
    case "check": return true;
  }
  throw new Error("no oracle for " + id);
}
// Negative reading/finding claims (either word order). A shown sentence that matches must be one of these, and its claim is
// then verified against the raw inputs; any other match is an unreviewed overclaim.
const NEGATIVE = /\b(?:no|not|none|never|nothing)\b[^.;:]*\b(?:read|found|printed|shown|seen)\b|\b(?:read|found|printed|shown|seen)\b[^.;:]*\b(?:no|not|none|never|nothing)\b/i;
const NEGATIVE_CLAIMS = {
  hint_blank_cell: (text, row) => {
    const named = [...text.matchAll(/“([^”]+)”/g)].map(match => match[1]);
    return /^No code was read under “[^”]+”(?:, “[^”]+”)*(?: and “[^”]+”)?;/.test(text) && named.length > 0 &&
      named.every(label => row.identifiers.some(item => item.state === "not_present" && blank(item.raw_value) &&
        String(item.source_label).trim().replace(/\s+/g, " ").startsWith(label.replace(/…$/, ""))));
  },
  searched_none: (text, row, s) => text === "The catalog search found no product for this line." && s.reason === EMPTY && s.method === "none" &&
    s.candidates.length === 0,
};
assert.deepEqual(Array.from(REASON_RULES, rule => rule.id), ORDER, "the documented priority order is the rule order");

const seen = new Map();
let combinations = 0;
for (const kind of ROW_KINDS) for (const note of NOTES) for (const [, list, reason, methods] of RETRIEVALS)
  for (const method of methods) for (const tierReason of TIER_REASONS) for (const tier of TIERS)
  for (const [, identifiers] of IDENTIFIERS) for (const [, description] of DESCRIPTIONS)
  for (const [, quantity, unit] of QUANTITY_UNIT) for (const evidence of EVIDENCE) {
    // an unknown row with a note is how the backend contract builds it; a null row has no fields at all
    const row = kind === null ? null : {row_id: "r", row_kind: kind, uncertainty: kind === "unknown" ? note || "Fictional ambiguous row" : note,
      identifiers, description, quantity, unit};
    const s = list === null ? null : {method, candidates: list, tier, tier_reason: tierReason, reason, evidence,
      outcome: list.length === 1 ? "suggested" : list.length ? "ambiguous" : "no_match"};
    const oracleSuggestion = s || {candidates: [], reason: "", tier_reason: "", method: "none", evidence: [], tier: "uncertain"};
    const got = plainReasonRule(row, s);
    combinations++;
    const holding = ORDER.filter(id => truth(id, row, oracleSuggestion));
    // 1. soundness: the shown sentence's precondition holds
    assert.ok(holding.includes(got.id), "shown but its precondition is false: " + got.id + " " + JSON.stringify({row, s}));
    // 2. priority: the first holding precondition, so exactly one primary reason
    assert.equal(got.id, holding[0], "not the first holding precondition: " + JSON.stringify({row, s}));
    // 3. neutral fallback only when nothing more specific holds
    if (got.id === "not_sure" || got.id === "check") assert.deepEqual(holding.filter(id => id !== "not_sure" && id !== "check"), [], "fallback used though a specific sentence holds");
    // 4. a negative reading/finding claim must be a reviewed, scoped one whose own fact holds
    if (NEGATIVE.test(got.text)) {
      assert.ok(NEGATIVE_CLAIMS[got.id] && NEGATIVE_CLAIMS[got.id](got.text, row, oracleSuggestion),
        "unproven negative claim: " + JSON.stringify(got.text) + " " + JSON.stringify({row, s}));
    }
    assert.doesNotMatch(got.text, /no code was read on this line/i);
    assert.equal(typeof got.text, "string");
    assert.ok(got.text.length > 0);
    seen.set(got.id, (seen.get(got.id) || 0) + 1);
  }
for (const id of ORDER) assert.ok(seen.get(id) > 0, "sentence never shown (unreachable or untested): " + id);
console.log("plain reasons generated: " + combinations + " combinations, " + ORDER.length + " sentences all reachable, " +
  "shown counts " + JSON.stringify(Object.fromEntries(seen)));
