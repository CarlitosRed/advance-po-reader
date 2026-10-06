"use strict";
/* tabs:start */
// Pure helpers for the three-tab review page: no DOM, no network, no global state.
// A row belongs to exactly one tab. Only `approve` events ever reach the spreadsheet.
const TAB_IDS = ["sure", "check", "not"];
const EXCLUDING_ACTIONS = ["not_a_product", "not_product"];
const BINDING_ACTIONS_UI = ["this_is_product", "new_product"];
const KIND_LABELS = {charge: "Charge", tax: "Tax", subtotal: "Subtotal", total: "Total", note: "Note"};

function rowRoleOf(row, schemaVersion) {
  if (schemaVersion === "1.2") return row.row_role;
  if (row.row_kind === "product") return "product_item";
  if (["charge", "tax", "subtotal", "total", "note"].includes(row.row_kind)) return "document_detail";
  return "unknown";
}
function rowStatusOf(row, events, suggestion) {
  const own = events.filter(e => e.row_id === row.row_id);
  const event = own.length ? own[own.length - 1] : null;
  if (event?.action === "no_match" && (row.row_kind === "unknown" || suggestion?.tier === "uncertain")) return "unresolved";
  return event && ["approve", "no_match", "not_a_product", "not_product"].includes(event.action) ? event.action : "unresolved";
}
function candidatesOf(rowId, suggestions, events) {
  const original = suggestions.find(s => s.row_id === rowId)?.candidates || [];
  const proposals = events.filter(e => e.row_id === rowId && ["propose_candidate", "this_is_product", "new_product"].includes(e.action))
    .flatMap(e => e.new_value.candidates);
  return [...new Map([...original, ...proposals].map(c => [c.candidate_id, c])).values()];
}
function boundCandidateOf(rowId, events) {
  const last = events.filter(e => e.row_id === rowId && [...BINDING_ACTIONS_UI, ...EXCLUDING_ACTIONS].includes(e.action)).at(-1);
  return last && BINDING_ACTIONS_UI.includes(last.action) ? (last.new_value?.candidates?.[0]?.candidate_id ?? null) : null;
}
function emptyMarks() { return {agreed: [], flagged: [], moved: []}; }
function assignTabs(payload, suggestions, events, marks) {
  const kept = {...emptyMarks(), ...(marks || {})};
  const groups = {sure: [], check: [], not: []};
  let lineIndex = 0;
  for (const row of payload.rows) {
    const role = rowRoleOf(row, payload.schema_version);
    if (role === "continuation") continue;
    const suggestion = suggestions.find(s => s.row_id === row.row_id) || null;
    const entry = {row, role, suggestion, tier: suggestion?.tier || "uncertain", lineIndex: -1, kind: "product",
      status: "unresolved", candidates: [], boundId: null, agreed: false, flagged: false, done: false, tab: "check"};
    if (role === "document_detail") {
      entry.kind = "system";
      entry.tab = "not";
      entry.agreed = kept.agreed.includes(row.row_id);
      entry.flagged = kept.flagged.includes(row.row_id);
      // Ignored lines are optional: they never count as work and never block the summary or Finish.
      entry.done = true;
    } else {
      entry.lineIndex = lineIndex++;
      entry.status = rowStatusOf(row, events, suggestion);
      entry.candidates = candidatesOf(row.row_id, suggestions, events);
      entry.boundId = boundCandidateOf(row.row_id, events);
      const excluded = ["not_a_product", "not_product", "no_match"].includes(entry.status);
      if (kept.moved.includes(row.row_id)) entry.tab = "check";
      else if (excluded) { entry.tab = "not"; entry.kind = "person"; }
      else if (entry.boundId) entry.tab = "check";
      else entry.tab = entry.tier === "certain" && entry.suggestion?.suggested_candidate_id ? "sure" : "check";
      entry.done = entry.tab === "not" ? true : entry.status === "approve";
    }
    groups[entry.tab].push(entry);
  }
  return groups;
}
function tabCounts(groups) {
  return Object.fromEntries(TAB_IDS.map(id => [id, {total: groups[id].length, todo: id === "not" ? 0 : groups[id].filter(e => !e.done).length}]));
}
// The first tab that still has work; if everything is done, the first of Sure/Check that has any line; the optional
// Ignored lines tab is only a first screen when it is the only tab with lines; an empty page opens on Sure.
function defaultTabOf(counts) {
  return TAB_IDS.find(id => counts[id].todo > 0) || TAB_IDS.find(id => id !== "not" && counts[id].total > 0) ||
    TAB_IDS.find(id => counts[id].total > 0) || "sure";
}
// Plain words for a tab with nothing to show, and the tab that is worth opening instead (or null).
function emptyTabCopy(tab, counts, filtering) {
  // Ignored lines is optional, so it is only suggested from its own page.
  const pool = tab === "not" ? TAB_IDS : TAB_IDS.filter(id => id !== "not");
  const other = pool.find(id => id !== tab && counts[id].todo > 0) || pool.find(id => id !== tab && counts[id].total > 0) || null;
  if (filtering) return {text: "No line matches the filter.", goto: null};
  if (counts[tab].total > 0) return {text: "Everything in this tab is done.", goto: pool.find(id => id !== tab && counts[id].todo > 0) || null};
  if (tab === "sure") return {
    text: "No line was sure this time. That is normal: a line is only “sure” when its printed code matches exactly one product. " +
      (other ? "Every product line is in Check, where you confirm each one against its picture." : "There are no product lines to confirm."),
    goto: other};
  if (tab === "check") return {text: "Nothing needs a closer look. Every product line was sure or already answered.", goto: other};
  return {text: "No totals, notes or charges were found, and no line was marked as not a product.", goto: other};
}
// ---- Plain reasons: one short sentence for why a line is in Check. Pure: data in, a sentence out. ----
// Inputs are fields the review API already returns (candidates, method, tier, tier_reason, evidence entries with no
// values) plus the extracted row. First matching case wins; the order is the table in tests/goal/reasons.cjs.
function hasPrintedCode(row) {
  return printedCodes(row).length > 0;
}
function printedCodes(row) {
  return (row?.identifiers || []).map(item => String(item?.raw_value ?? "").trim()).filter(Boolean);
}
function fieldIsUnclear(item) {
  return Boolean(item) && (["uncertain", "unreadable"].includes(item.state) || (item.alternative_readings || []).length > 0);
}
function hasUnclearReading(row) {
  return [...(row?.identifiers || []), row?.description, row?.quantity, row?.unit].some(fieldIsUnclear);
}
// Two catalog products where one code is the other with a printed vendor prefix ("WERNER D6224-2" and "D6224-2").
// Same shape as the server's tier rule: letters-only prefix, then a space, dash or slash before the shorter code.
function vendorPrefixPair(candidates) {
  const skus = (candidates || []).map(c => String(c?.sku ?? "").trim()).filter(Boolean);
  for (const long of skus) for (const short of skus) {
    if (long.length <= short.length + 1 || !long.toUpperCase().endsWith(short.toUpperCase())) continue;
    if (!" -/".includes(long[long.length - short.length - 1])) continue;
    const prefix = long.slice(0, long.length - short.length).split(/[\s/-]+/).filter(Boolean);
    if (prefix.length && prefix.every(token => /^[A-Za-z]+$/.test(token))) return [short, long];
  }
  return null;
}
function plainReason(row, suggestion) {
  const candidates = suggestion?.candidates || [];
  const method = suggestion?.method || "none";
  const tierReason = String(suggestion?.tier_reason || "");
  const evidence = suggestion?.evidence || [];
  const printed = hasPrintedCode(row);
  if (candidates.length > 1) {
    const pair = vendorPrefixPair(candidates);
    if (pair) return "The catalog has both '" + pair[0] + "' and '" + pair[1] + "'.";
    return candidates.length + " catalog products look alike; pick the right one.";
  }
  if (!candidates.length) return "No catalog product matches this code or name.";
  if (/conflict/i.test(tierReason)) return "The code and the description do not agree.";
  if (hasUnclearReading(row)) return "Part of this line is hard to read.";
  if (row && (row.row_kind !== "product" || row.uncertainty)) return "The app could not tell for sure that this line is a product.";
  if (method === "normalized") return "The printed code is written a little differently from the catalog code.";
  const squash = value => String(value ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (method === "exact" && printed && !printedCodes(row).some(code => squash(code) === squash(candidates[0].sku))) {
    return "The printed code is not the catalog's main code for this product.";
  }
  if (method === "description_code_hint" || method === "description_numeric_code_hint") {
    return printed ? "The printed code does not match, but a code in the description does."
      : "No code column on this line; the code was found inside the description.";
  }
  if (method === "description_code_hint_trigram") return "The code in the description is close to this catalog code, but not the same.";
  if (method === "trigram") return printed ? "The printed code or name is close to this product, but not the same."
    : "No product code on this line; matched by name only.";
  if (evidence.some(item => ["description_hint_ignored", "code_reading_ignored"].includes(item?.kind))) {
    return "Other codes or sizes on this line were set aside; please check the match.";
  }
  return "The app is not sure enough to confirm this one by itself.";
}
// How many lines per page have no exact spot on the page (their snapshot shows the whole page instead).
function wholePageCounts(payload, groups) {
  const counts = {};
  for (const entry of Object.values(groups).flat()) {
    if (regionBox(payload, entry.row)) continue;
    const page = entry.row.evidence?.[0]?.page_number || 1;
    counts[page] = (counts[page] || 0) + 1;
  }
  return counts;
}
function bulkTargets(entries, visibleIds) {
  const visible = new Set(visibleIds);
  return entries.filter(e => e.tab === "sure" && e.status === "unresolved" && visible.has(e.row.row_id) &&
    e.suggestion?.suggested_candidate_id).map(e => ({rowId: e.row.row_id, candidateId: e.suggestion.suggested_candidate_id}));
}
function regionBox(payload, row) {
  const ref = row.evidence?.[0];
  if (!ref) return null;
  const page = payload.pages.find(p => p.page_number === ref.page_number);
  const region = page?.regions.find(r => r.region_reference === ref.region_reference);
  return region?.bbox || null;
}
// Crop rectangle (in image pixels) around a normalized row box, plus the highlight inside the crop.
function snapshotGeometry(bbox, width, height, options = {}) {
  const whole = {sx: 0, sy: 0, sw: width, sh: height, highlight: null};
  if (!bbox || !(width > 0) || !(height > 0)) return whole;
  const clamp = value => Math.min(1, Math.max(0, Number(value)));
  const [x0, y0, x1, y1] = [bbox.x0, bbox.y0, bbox.x1, bbox.y1].map(clamp);
  if (![x0, y0, x1, y1].every(Number.isFinite) || !(x1 > x0) || !(y1 > y0)) return whole;
  const box = {x: Math.round(x0 * width), y: Math.round(y0 * height), w: Math.max(1, Math.round((x1 - x0) * width)), h: Math.max(1, Math.round((y1 - y0) * height))};
  if (options.page) return {...whole, highlight: box};
  const padY = options.padY ?? Math.min(0.04, Math.max(0.012, (y1 - y0) * 0.5));
  const minWidth = options.minWidth ?? 0.6;
  let left = Math.max(0, x0 - 0.012), right = Math.min(1, x1 + 0.012);
  if (right - left < minWidth) {
    left = Math.max(0, Math.min(1 - minWidth, (x0 + x1) / 2 - minWidth / 2));
    right = left + minWidth;
  }
  const top = Math.max(0, y0 - padY), bottom = Math.min(1, y1 + padY);
  const sx = Math.round(left * width), sy = Math.round(top * height);
  const sw = Math.max(1, Math.round((right - left) * width)), sh = Math.max(1, Math.round((bottom - top) * height));
  return {sx, sy, sw, sh, highlight: {x: box.x - sx, y: box.y - sy, w: box.w, h: box.h}};
}
/* tabs:end */
let statusPollTimer = null;
let pollGeneration = 0;

function stopStatusPolling() {
  clearTimeout(statusPollTimer);
  statusPollTimer = null;
  pollGeneration++;
}

function renderReadiness() {
  const report = state.readiness;
  if (!report) return;
  // The free proof of concept never connects a provider, so the pending-connection banner would only confuse.
  if (state.poc) { $("demo-readiness").hidden = true; return; }
  const databaseReady = report.database === "ready";
  const title = !databaseReady ? "Local database needs to start" :
    report.provider_configured ? "Live document reading is connected" : "API connection pending";
  const copy = !databaseReady ? "Your stored documents and catalogs will be available when the local database is running." :
    report.provider_configured ? "Authorize an original document, run extraction here or through your agent, then review the source." :
    "The catalogs and document library are local. Try the fictional sample now; configure the server API key to read an original document.";
  $("demo-readiness").hidden = false;
  $("demo-readiness").innerHTML = `<div><span class="badge ${report.provider_configured ? "green" : "amber"}">${escapeHTML(title)}</span><p>${escapeHTML(copy)}</p></div><button id="refresh-readiness" class="button secondary">Check connection</button>`;
  $("refresh-readiness").onclick = async () => {
    try {
      state.readiness = await api("/website/readiness");
      state.configuration = await api("/configuration");
      renderReadiness();
      if (state.readiness.database === "ready" && !state.workspace) await initialize();
    } catch (error) { fail(error); }
  };
}

async function initialize() {
  try {
    const session = await api("/website/session");
    state.csrf = session.csrf;
    state.readiness = await api("/website/readiness");
    if (state.readiness.database !== "ready") {
      renderReadiness();
      $("view").innerHTML = '<section class="panel"><h1>Your local database is stopped.</h1><p class="field">Start the preserved local database, then use Check connection above. Your documents and catalogs remain saved.</p></section>';
      return;
    }
    const [scopes, configuration] = await Promise.all([
      api("/website/workspaces"), api("/configuration")]);
    state.workspace = scopes.workspaces[0] || null;
    if (!state.workspace) throw new Error("local_catalog_setup_required");
    const corpus = await api("/website/corpus");
    state.catalogs = state.workspace.catalogs;
    state.pools = (state.workspace.catalog_pools || []).map(pool => ({...pool, is_pool:true}));
    state.defaultPool = corpus.default_catalog_pool ? {...corpus.default_catalog_pool, is_pool:true, synthetic:false} : null;
    state.catalog = state.defaultPool;
    state.configuration = configuration;
    state.library = corpus.documents;
    $("library-count").textContent = state.library.length;
    // Free proof of concept: only synthetic catalogs, no default pool and no provider.
    state.poc = !state.defaultPool && state.catalogs.length > 0 && state.catalogs.every(c => c.synthetic);
    if (state.poc) document.querySelector(".main-nav").hidden = true;
    renderReadiness();
    await restoreRoute();
  } catch (error) {
    fail(error);
    $("view").innerHTML = '<section class="panel"><h1>The local workspace needs setup.</h1><p class="field">Start the website with its configured local database and source import. Reload once it is ready.</p></section>';
  }
}

function scheduleStatusPolling() {
  const runId = state.run?.id;
  if (!runId || !(["processing", "validating"].includes(state.run.state) || state.processingRequest === runId ||
      (state.run.state === "created" && state.runReadiness?.source_authorized))) return;
  const generation = pollGeneration;
  statusPollTimer = setTimeout(async () => {
    if (generation !== pollGeneration || state.run?.id !== runId || document.hidden) {
      if (document.hidden && generation === pollGeneration) scheduleStatusPolling();
      return;
    }
    try {
      const run = await api("/runs/" + runId);
      if (generation !== pollGeneration || state.run?.id !== runId) return;
      const unchanged = run.state === state.run.state && run.review_state === state.run.review_state;
      state.run = run;
      // Preserve expanded handoff details and source previews while status is
      // unchanged. A poll needs one status read, not a new PDF render.
      if (unchanged) { scheduleStatusPolling(); return; }
      await loadRun();
      if (generation !== pollGeneration || state.run?.id !== runId) return;
      renderDocument();
    } catch (error) {
      // A status request can fail without granting a retry of processing.
      if (generation === pollGeneration) {
        fail(error);
        scheduleStatusPolling();
      }
    }
  }, 2000);
}

function csvCell(value) {
  let text = String(value ?? "");
  // Spreadsheet programs run text that starts with = + @ as a formula; a leading apostrophe keeps it plain text.
  if (/^[=+@\t\r]/.test(text) || (/^-/.test(text) && !/^-?[\d.,]+$/.test(text))) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}

function downloadCSV(items) {
  const header = ["product_id", "product", "description", "quantity", "unit", "quantity_as_printed", "price"];
  const rows = items.map(item => [item.id, item.name, item.printed, item.quantity, item.unit, item.quantityPrinted, item.price]);
  const text = "﻿" + [header, ...rows].map(row => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
  const url = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url; link.download = "confirmed-products.csv"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderSummary() {
  stopStatusPolling();
  revokeImages();
  rememberDocument(true);
  const summary = state.summary;
  if (!summary) { fail(new Error("review_summary_unavailable")); return; }
  if (!state.reviewer.trim()) { renderReviewerGate(() => renderSummary()); return; }
  const payload = state.result.extraction;
  const lines = lineList(payload);
  const approved = summary.approved_products;
  const pending = summary.pending_row_ids;
  const resolved = summary.review_state === "resolved";
  const bar = reviewerBarHTML();
  const details = (summary.document_details?.length ? `<details class="more"><summary>Other printed lines (totals, notes) · ${summary.document_details.length}</summary>${summary.document_details.map(item => `<div class="audit-event"><strong>${escapeHTML(item.row_kind)}</strong><p>${escapeHTML(item.description ?? item.raw_description ?? "")}</p>${item.line_total ? `<p>Amount: ${escapeHTML(item.line_total)}</p>` : ""}</div>`).join("")}</details>` : "") +
    `<details class="more"><summary>Details</summary><dl class="detail-grid"><div><dt>Source file</dt><dd>${escapeHTML(state.name)}</dd></div><div><dt>SHA-256</dt><dd>${escapeHTML(state.source.sha256)}</dd></div><div><dt>Run id</dt><dd>${escapeHTML(state.run.id)}</dd></div></dl>${auditHTML()}</details>`;
  if (pending.length) {
    const done = lines.length - pending.length;
    $("view").innerHTML = `${bar}<section class="panel summary-left"><p class="eyebrow">ALMOST THERE</p><h1>${pending.length} ${pending.length === 1 ? "line" : "lines"} left to check</h1><p class="hint">${done} of ${lines.length} checked. Products are listed here once every line has an answer.</p><progress max="${lines.length}" value="${done}" aria-label="${done} of ${lines.length} lines checked"></progress><div class="line-list">${pending.map(id => { const index = lines.findIndex(row => row.row_id === id); return index < 0 ? "" : `<button class="queue-button" data-row="${index}"><span>Line ${index + 1} · ${escapeHTML(lineTitle(lines[index]))}</span><small>${pillHTML(lineModel(lines[index]))}</small></button>`; }).join("")}</div><div class="stack"><button id="back-review" class="button primary big">Continue checking</button><button id="finish-review" class="button secondary big" disabled>Finish review</button></div></section>${flaggedNoticeHTML()}${details}`;
    wireReviewerBar(() => renderSummary());
    $("back-review").onclick = () => { state.mode = "tabs"; renderDocument(); };
    for (const button of document.querySelectorAll("[data-row]")) button.onclick = () => { state.mode = "line"; state.row = Number(button.dataset.row); renderDocument(); };
    return;
  }
  const filled = value => value !== null && value !== undefined && String(value).trim() !== "";
  const items = approved.map(item => {
    const row = payload.rows.find(candidate => candidate.row_id === item.row_id);
    const price = row ? effectiveValue(row, "unit_price") : null;
    const n = normalizeQuantity(item.quantity);
    const unit = filled(item.unit) ? String(item.unit).trim() : (n.unit || "");
    const shown = quantityDisplay(item.quantity, item.unit);
    return {id: item.candidate.sku, name: item.candidate.description, shown, quantity: n.ok ? n.text : "", unit,
      quantityPrinted: item.original_quantity ?? "",
      printed: [item.description, ...(item.continuation_descriptions || []).map(part => part.raw_description)].filter(filled).join(" "),
      price: filled(price) ? price : ""};
  });
  const excluded = summary.excluded_rows.length;
  const table = items.length ? `<div class="table-wrap"><table class="result-table"><thead><tr><th scope="col">ID</th><th scope="col">Product</th><th scope="col">Qty</th><th scope="col">Price</th></tr></thead><tbody>${items.map(item => `<tr><td class="cell-id">${escapeHTML(item.id)}</td><td>${escapeHTML(item.name)}${item.printed ? `<small>As printed: ${escapeHTML(item.printed)}</small>` : ""}</td><td>${escapeHTML(item.shown.text)}${item.shown.check ? ' <span class="check-flag">Check</span>' : ""}</td><td>${escapeHTML(item.price)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="panel empty">No line was confirmed as a product.</div>';
  $("view").innerHTML = `${bar}<section class="done-head"><span class="check big-check" aria-hidden="true">✓</span><h1>${items.length} ${items.length === 1 ? "product" : "products"} confirmed</h1><p class="hint">${excluded ? `${excluded} ${excluded === 1 ? "line was" : "lines were"} marked “not a product”. ` : ""}${resolved ? "Review saved." : "Every line has an answer."}</p></section>
    ${resolved ? "" : '<section class="panel finish"><h2>One last step</h2><p>Finish the review to lock your answers. They cannot be changed afterwards.</p><div id="document-acknowledgements"></div><button id="finish-review" class="button primary big"' + (summary.can_finish_review ? "" : " disabled") + '>Finish review</button></section>'}
    ${flaggedNoticeHTML()}${table}
    <div class="stack"><button id="download-csv" class="button ${resolved ? "primary" : "secondary"} big" ${items.length ? "" : "disabled"}>Download as spreadsheet</button><button id="back-review" class="button secondary big">← Back to the tabs</button></div>${details}`;
  wireReviewerBar(() => renderSummary());
  $("back-review").onclick = () => { state.mode = "tabs"; renderDocument(); };
  $("download-csv").onclick = () => downloadCSV(items);
  if (resolved) return;
  const partial = payload.pages.filter(page => page.state === "partial" && !state.events.some(event =>
    event.action === "acknowledge_page" && event.evidence_reference.some(ref => ref.page_number === page.page_number)));
  const needsWarnings = payload.warnings.length && !state.events.some(event => event.action === "acknowledge_document");
  $("document-acknowledgements").innerHTML = partial.map(page => `<div class="callout">Page ${page.page_number} was only partly read: ${escapeHTML(page.uncertainty || "check the whole page")}<div class="button-row"><button class="button secondary" data-ack-page="${page.page_number}">I checked this page</button></div></div>`).join("") +
    (needsWarnings ? `<div class="callout">${payload.warnings.map(escapeHTML).join("<br>")}<div class="button-row"><button class="button secondary" id="ack-warnings">I read these warnings</button></div></div>` : "") +
    (summary.blockers.includes("failed_pages_require_new_processing_run") ? '<div class="callout">A page failed. This review cannot be finished; start a new reading after checking the source.</div>' : "");
  for (const button of document.querySelectorAll("[data-ack-page]")) button.onclick = () => saveReview("acknowledge_page", {
    evidence_reference: [{page_number: Number(button.dataset.ackPage), region_reference: null}]}).then(renderSummary).catch(fail);
  if ($("ack-warnings")) $("ack-warnings").onclick = () => saveReview("acknowledge_document", {
    evidence_reference: [{page_number: payload.pages[0].page_number, region_reference: null}]}).then(renderSummary).catch(fail);
  $("finish-review").onclick = () => saveReview("resolve").then(renderSummary).catch(fail);
}

function agentHandoffHTML() {
  if (!state.run || !state.source) return "";
  return `<details class="audit"><summary>Continue with your agent</summary><p class="hint">Give your agent these saved identifiers and ask it to check this run. Processing needs authorization for this source; product decisions stay here.</p><dl class="detail-grid"><div><dt>Workspace ID</dt><dd>${escapeHTML(state.workspace.id)}</dd></div><div><dt>Catalog ID</dt><dd>${escapeHTML(state.source.vendor_id)}</dd></div><div><dt>Run ID</dt><dd>${escapeHTML(state.run.id)}</dd></div><div><dt>Source authorization</dt><dd>${state.runReadiness?.source_authorized ? "Recorded for this exact source" : "Required before real processing"}</dd></div></dl></details>`;
}

async function processSavedRun(runId) {
  const readiness = await api("/runs/" + runId + "/readiness");
  if (!readiness.can_process) throw new Error(readiness.blockers[0] || "processing_not_ready");
  state.processingRequest = runId;
  const processing = api("/runs/" + runId + "/process", {method: "POST"});
  renderDocument();
  try {
    await processing;
    if (state.run?.id !== runId) return;
    state.processingRequest = null;
    state.run = await api("/runs/" + runId);
    await loadRun();
    if (state.view === "upload") renderDocument();
  } finally { if (state.processingRequest === runId) state.processingRequest = null; }
}

function enhancePending() {
  const aside = document.querySelector(".source-panel");
  if (aside) { aside.outerHTML = sourcePanel(); wireSource(); }
  const status = state.run?.state;
  const requesting = state.processingRequest === state.run?.id;
  const active = requesting || ["processing", "validating"].includes(status);
  const unknown = state.result?.attempts?.some(attempt => attempt.state === "unknown_outcome");
  const section = document.querySelector(".review-layout>section");
  if (status && (status !== "created" || requesting)) {
    section.innerHTML = `<span class="badge amber">${escapeHTML(requesting && status === "created" ? "Processing requested" : status.replaceAll("_", " "))}</span><h2 class="field">${active ? "Reading this document" : "This run has no reviewable result."}</h2><p>${escapeHTML(state.run.outcome_code ? errorText(new Error(state.run.outcome_code)) : active ? "The saved run status refreshes automatically. You can leave this page and reopen the same run." : "The processing state is saved. Check its status before starting another run.")}</p><div class="button-row"><button id="refresh-run" class="button secondary">Refresh status</button>${active ? '<button id="cancel-run" class="button secondary">Cancel run</button>' : ""}</div>`;
  } else if (state.runReadiness?.source_authorized) {
    section.innerHTML = '<span class="badge green">Source authorization recorded</span><h2 class="field">Ready for your agent.</h2><p>This run is authorized for the exact saved source. Its status refreshes here when your agent starts processing.</p><div class="button-row">' +
      (state.configuration.provider_configured ? '<button id="process-authorized-run" class="button primary">Extract this authorized run</button>' : '<p class="hint">Configure the server API connection before real extraction.</p>') + '<button id="cancel-run" class="button secondary">Cancel this prepared run</button></div>';
  } else if (status === "created" && state.configuration.provider_configured) {
    section.innerHTML = '<span class="badge amber">Source authorization required</span><h2 class="field">The connection is ready.</h2><p>Confirm the applicable authorization for this saved source before extraction starts.</p>';
  }
  section.insertAdjacentHTML("beforeend", agentHandoffHTML());
  if ($("refresh-run")) $("refresh-run").onclick = async () => {
    try { state.run = await api("/runs/" + state.run.id); await loadRun(); renderDocument(); } catch (error) { fail(error); }
  };
  if ($("cancel-run")) $("cancel-run").onclick = async () => {
    try { await api("/runs/" + state.run.id + "/cancel", {method: "POST"}); state.processingRequest = null; state.run = await api("/runs/" + state.run.id); await loadRun(); renderDocument(); } catch (error) { fail(error); }
  };
  if ($("process-authorized-run")) $("process-authorized-run").onclick = async () => {
    if (state.busy) return;
    state.busy = true;
    try { await processSavedRun(state.run.id); } catch (error) { fail(error); }
    finally { state.busy = false; }
  };
  if (active) { scheduleStatusPolling(); return; }
  if (unknown) {
    section.insertAdjacentHTML("beforeend", '<div class="callout field">The provider outcome is unknown. Automatic retry is blocked. Keep this run and its attempt for investigation before making another request.</div>');
    return;
  }
  if (status === "created" && state.runReadiness?.source_authorized) { scheduleStatusPolling(); return; }
  section.insertAdjacentHTML("beforeend", `<hr class="separator"><h3>Authorize this source for extraction</h3><p class="hint">Record authorization for the exact source. When processing starts, the configured server sends this file to OpenAI.</p><form id="authorize-extraction"><div class="field"><label for="authorized-by">Authorized by</label><input id="authorized-by" maxlength="120" required></div><div class="field"><label for="policy-reference">Customer privacy policy / authorization reference</label><input id="policy-reference" maxlength="500" required></div><div class="field"><label for="authorization-reason">Purpose and reason</label><input id="authorization-reason" maxlength="500" required></div><label><input type="checkbox" id="allow-external" required> I am authorized to send this source to OpenAI.</label><p class="hint">Source SHA-256: ${escapeHTML(state.source.sha256)}</p><div class="button-row"><button class="button primary" name="mode" value="agent">Authorize for agent</button><button class="button secondary" name="mode" value="process" ${state.configuration.provider_configured ? "" : "disabled"}>Authorize and extract now</button></div>${state.configuration.provider_configured ? "" : '<p class="hint">Immediate extraction becomes available after server API setup.</p>'}</form>`);
  $("authorize-extraction").onsubmit = async event => {
    event.preventDefault();
    if (state.busy) return;
    const mode = event.submitter?.value || "agent";
    const auth = {authorized: $("allow-external").checked, source_sha256: state.source.sha256,
      authorized_by: $("authorized-by").value, policy_reference: $("policy-reference").value,
      reason: $("authorization-reason").value};
    state.busy = true;
    try {
      state.run = await api("/documents/" + state.source.id + "/runs", {method: "POST",
        json: {provider: "openai", external_authorization: auth}, headers: {"Idempotency-Key": crypto.randomUUID()}});
      await loadRun();
      renderDocument();
      if (mode === "process") {
        await processSavedRun(state.run.id);
      } else { toast("Authorization saved. Your agent can continue with this run."); }
    } catch (error) {
      state.processingRequest = null;
      try { if (state.run) { state.run = await api("/runs/" + state.run.id); await loadRun(); } } catch {}
      if (state.view === "upload") renderDocument();
      fail(error);
    } finally { state.busy = false; }
  };
}

/* ---------- Three-tab review page ---------- */
const TAB_INFO = {
  sure: {title: "Sure", tone: "green", color: "#167055", todoWord: "to confirm",
    intro: "The printed code matches exactly one product. Look at the picture, then tap the check mark."},
  check: {title: "Check", tone: "amber", color: "#c27a00", todoWord: "to check",
    intro: "Each line says why we are not sure. Confirm the best guess, pick another product, or mark the line as not a product."},
  not: {title: "Ignored lines", tone: "gray", color: "#4d5f70", todoWord: "optional",
    intro: "Totals, notes and charges the app ignored. You do not need to open this tab."}
};
const pageImages = new Map();

function marksKey() { return "advance-po-reader.marks." + (state.run?.id || ""); }
function loadMarks() {
  if (state.marks?.runId === state.run.id) return state.marks.value;
  let value = emptyMarks();
  try { value = {...emptyMarks(), ...JSON.parse(localStorage.getItem(marksKey()) || "{}")}; } catch {}
  state.marks = {runId: state.run.id, value};
  return value;
}
function saveMarks() {
  try { localStorage.setItem(marksKey(), JSON.stringify(state.marks.value)); } catch {}
}
function toggleMark(list, rowId, on) {
  const marks = loadMarks();
  marks[list] = marks[list].filter(id => id !== rowId);
  if (on) marks[list].push(rowId);
  saveMarks();
}

/* A page is fetched once and kept decoded; every row on it is cropped from that one picture. */
function pageImage(page) {
  const key = state.source.id + ":" + page;
  if (!pageImages.has(key)) {
    const loading = (async () => {
      const blob = await api("/documents/" + state.source.id + "/pages/" + page, {binary: true});
      if (!(blob.type || "").startsWith("image/")) throw new Error("preview_unavailable");
      return createImageBitmap(blob);
    })();
    loading.catch(() => pageImages.delete(key));
    pageImages.set(key, loading);
    if (pageImages.size > 12) pageImages.delete(pageImages.keys().next().value);
  }
  return pageImages.get(key);
}
function drawSnapshot(canvas, image, bbox, color, options = {}) {
  const g = snapshotGeometry(bbox, image.width, image.height, options);
  canvas.width = g.sw; canvas.height = g.sh;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, g.sx, g.sy, g.sw, g.sh, 0, 0, g.sw, g.sh);
  if (g.highlight) {
    const {x, y, w, h} = g.highlight;
    // Quiet everything except the row, then outline the row in the tab color.
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    ctx.fillRect(0, 0, g.sw, Math.max(0, y));
    ctx.fillRect(0, y + h, g.sw, Math.max(0, g.sh - y - h));
    ctx.fillRect(0, y, Math.max(0, x), h);
    ctx.fillRect(x + w, y, Math.max(0, g.sw - x - w), h);
    ctx.fillStyle = color + "22";
    ctx.fillRect(x, y, w, h);
    ctx.lineWidth = Math.max(3, Math.round(g.sw / 300));
    ctx.strokeStyle = color;
    ctx.strokeRect(x, y, w, h);
  }
  canvas.dataset.drawn = "1";
}
async function paintSnapshot(canvas) {
  const frame = canvas.closest(".snap-frame");
  const page = Number(canvas.dataset.page);
  frame.classList.remove("failed"); frame.classList.add("loading");
  try {
    const image = await pageImage(page);
    if (!canvas.isConnected) return;
    drawSnapshot(canvas, image, canvas.dataset.bbox ? JSON.parse(canvas.dataset.bbox) : null, canvas.dataset.color);
    frame.classList.remove("loading");
    if (state.tabs.snapFailed.delete(page)) updateSnapBanner();
  } catch {
    if (!canvas.isConnected) return;
    frame.classList.remove("loading"); frame.classList.add("failed");
    state.tabs.snapFailed.add(page);
    updateSnapBanner();
  }
}
// Page-level wording above the cards: pages whose picture could not load, and lines with no exact spot on the page.
function updateSnapBanner() {
  const banner = $("snap-banner");
  if (!banner) return;
  const failed = [...state.tabs.snapFailed].sort((a, b) => a - b);
  const whole = Object.entries(state.tabs.wholePage || {}).sort((a, b) => a[0] - b[0]);
  const parts = [];
  if (failed.length) parts.push('<p><strong>' + (failed.length === 1 ? "The picture of page " + failed[0] + " is" : "The pictures of pages " + failed.join(", ") + " are") +
    ' not available right now.</strong> Lines on ' + (failed.length === 1 ? "that page" : "those pages") + ' show no snapshot. You can still decide from the printed text on each line, or <button type="button" class="link-button" id="retry-snapshots">try again</button>.</p>');
  if (whole.length) parts.push('<p>' + whole.map(([page, n]) => "Page " + page + ": " + n + (n === 1 ? " line has" : " lines have")).join("; ") + ' no exact spot on the page, so its snapshot shows the whole page.</p>');
  banner.hidden = !parts.length;
  banner.innerHTML = parts.join("");
  if ($("retry-snapshots")) $("retry-snapshots").onclick = () => {
    for (const page of failed) pageImages.delete(state.source.id + ":" + page);
    state.tabs.snapFailed = new Set();
    updateSnapBanner();
    document.querySelectorAll("#tab-cards canvas.snap").forEach(canvas => { if (canvas.closest(".snap-frame").classList.contains("failed")) paintSnapshot(canvas); });
  };
}
function watchSnapshots(root) {
  state.snapObserver?.disconnect();
  const canvases = [...root.querySelectorAll("canvas.snap")];
  // A hidden tab never reports visibility, and every row on a page shares one decoded picture, so paint them all.
  if (!("IntersectionObserver" in window) || document.hidden) { canvases.forEach(paintSnapshot); return; }
  state.snapObserver = new IntersectionObserver(items => {
    for (const item of items) if (item.isIntersecting) { state.snapObserver.unobserve(item.target); paintSnapshot(item.target); }
  }, {rootMargin: "600px 0px"});
  canvases.forEach(canvas => state.snapObserver.observe(canvas));
}

function entryText(entry) {
  const row = entry.row;
  return [rowCode(row), row.description?.raw_value, ...entry.candidates.flatMap(c => [c.sku, c.description])].filter(Boolean).join(" ").toLowerCase();
}
function entryTitle(entry) {
  const n = entry.lineIndex >= 0 ? "Line " + (entry.lineIndex + 1) : "Printed line";
  return n + " · " + (entry.kind === "system" ? (KIND_LABELS[entry.row.row_kind] || "Not a product") : lineTitle(entry.row));
}
function snapshotHTML(entry, tab) {
  const row = entry.row, ref = row.evidence?.[0], box = regionBox(state.result.extraction, row);
  const page = ref?.page_number || 1;
  return '<div class="snap-frame loading"><canvas class="snap" role="img" aria-label="Snapshot of ' + escapeHTML(entryTitle(entry)) + ' on page ' + page +
    '" data-page="' + page + '" data-color="' + TAB_INFO[tab].color + '"' + (box ? ' data-bbox="' + escapeHTML(JSON.stringify(box)) + '"' : "") + '></canvas>' +
    '<div class="snap-skeleton">Loading the picture…</div><div class="snap-fallback"><span>No picture for this line. Use the printed text below.</span> <button type="button" class="link-button" data-act="retry-snap">Try again</button></div></div>';
}
// Sure tab: one sentence saying what the line matched.
function lookedLikeHTML(c) {
  return '<div class="proposal green"><span class="guess-label">Looks like</span><strong class="guess-name">' + escapeHTML(c.description) + '</strong><span class="guess-code">' + escapeHTML(c.sku) + '</span>' +
    (c.origin === "review" ? '<small>Added by a reviewer</small>' : "") + '</div>';
}
function productCardHTML(c, label, tone) {
  return '<div class="proposal ' + tone + '"><span class="guess-label">' + label + '</span><strong class="guess-code">' + escapeHTML(c.sku) + '</strong><span class="guess-desc">' + escapeHTML(c.description) + '</span>' + (c.origin === "review" ? '<small>Added by a reviewer</small>' : "") + '</div>';
}
function editPanelHTML() {
  const vendors = (state.catalogs || []).filter(v => !state.run.catalog_pool_id || (state.catalog?.vendor_ids || []).includes(v.id));
  const vendorField = state.run.catalog_pool_id ? '<div class="field"><label>Which catalog<select name="vendor" required><option value="">Choose catalog</option>' + vendors.map(v => '<option value="' + escapeHTML(v.id) + '">' + escapeHTML(v.name) + '</option>').join("") + '</select></label></div>' : "";
  return '<div class="answer-panel edit-panel"><form data-form="search" class="search-bar"><label class="sr-only">Search the catalog by code or name</label><input name="q" class="search-input" maxlength="120" placeholder="Search the catalog by code or name"><button class="button secondary">Search</button></form>' +
    '<div class="search-results" data-results></div>' +
    '<details class="more-inline"><summary>Not in the catalog? Add a new product</summary><form data-form="new" data-key="' + escapeHTML(crypto.randomUUID()) + '"><div class="field"><label>Product code<input name="sku" maxlength="200" required></label></div><div class="field"><label>Product description<input name="description" maxlength="4000" required></label></div>' + vendorField + '<button class="button secondary">Save new product</button></form></details></div>';
}
// Returns the pieces of one card: pill, printed facts, proposed product(s), action buttons and the optional edit panel.
function cardParts(entry, tab, resolved) {
  const row = entry.row, payload = state.result.extraction;
  const open = Boolean(state.tabs.edit[row.row_id]);
  const finished = '<p class="hint">This review is finished.</p>';
  if (tab === "not") {
    if (entry.kind === "system") {
      const amount = effectiveValue(row, "line_total");
      const body = '<dl class="facts">' + fact("Read as", escapeHTML(KIND_LABELS[row.row_kind] || "Not a product")) +
        fact("Printed text", row.description?.raw_value ? escapeHTML(row.description.raw_value) : '<span class="none">Nothing printed</span>') +
        (filledValue(amount) ? fact("Amount", escapeHTML(amount)) : "") + '</dl>';
      const pill = entry.flagged ? '<span class="pill amber">Flagged as a product</span>'
        : entry.agreed ? '<span class="pill gray">You agreed</span>' : '<span class="pill gray">Not a product</span>';
      let actions;
      if (resolved) actions = finished;
      else if (entry.flagged) actions = '<p class="hint">Flagged on this device only. The server cannot reclassify this kind of line yet, so it is not in the spreadsheet.</p><button class="button secondary" data-act="unflag">Undo flag</button>';
      else if (entry.agreed) actions = '<button class="button secondary" data-act="unagree">Undo</button>';
      else actions = '<button class="button primary" data-act="agree">Agree, not a product</button><button class="button secondary" data-act="flag">Actually a product</button>';
      return {pill, body, actions};
    }
    const who = state.events.filter(e => e.row_id === row.row_id && EXCLUDING_ACTIONS.includes(e.action)).at(-1)?.reviewer;
    return {pill: '<span class="pill gray">Marked not a product</span>', body: factsHTML(row, payload, entry.role),
      actions: (who ? '<p class="hint">Marked by ' + escapeHTML(who) + '.</p>' : "") + (resolved ? finished : '<button class="button secondary" data-act="edit">Actually a product</button>')};
  }
  const body = factsHTML(row, payload, entry.role);
  if (entry.status === "approve" && !open) {
    const approved = state.summary?.approved_products?.find(a => a.row_id === row.row_id)?.candidate;
    return {pill: '<span class="pill green">Confirmed</span>', body,
      proposal: approved ? '<div class="decided"><span class="check" aria-hidden="true">✓</span><p>Confirmed <strong>' + escapeHTML(approved.sku) + '</strong> · ' + escapeHTML(approved.description) + '</p></div>' : "",
      actions: resolved ? finished : '<button class="button secondary" data-act="edit">Change</button>'};
  }
  const pill = tab === "sure" ? '<span class="pill green">Sure</span>' : '<span class="pill amber">' + (entry.tier === "probable" ? "Probably right" : "Needs a look") + '</span>';
  const shown = entry.boundId ? entry.candidates.filter(c => c.candidate_id === entry.boundId)
    : tab === "sure" ? entry.candidates.filter(c => c.candidate_id === entry.suggestion?.suggested_candidate_id).slice(0, 1)
    : entry.candidates.slice(0, 3);
  let proposal = "";
  if (tab === "sure") {
    proposal = shown.map(c => lookedLikeHTML(c) + (resolved ? "" : '<button class="button primary confirm-button check-button" data-act="confirm" data-cid="' + escapeHTML(c.candidate_id) + '"><span aria-hidden="true">✓</span> This is the product</button>')).join("");
  } else {
    // Check: why we are not sure, then the best guess, then up to two other products it could be.
    const [first, ...others] = shown;
    const label = entry.boundId ? "Your choice · please confirm" : entry.tier === "probable" ? "Best guess · please check" : "Possible match";
    proposal = (entry.boundId ? "" : '<p class="reason" data-reason>' + escapeHTML(plainReason(row, entry.suggestion)) + '</p>');
    if (first) proposal += productCardHTML(first, label, "amber") +
      (resolved ? "" : '<button class="button primary confirm-button" data-act="confirm" data-cid="' + escapeHTML(first.candidate_id) + '">Confirm</button>');
    if (others.length) proposal += '<div class="could-be"><p class="could-label">Could also be:</p>' + others.slice(0, 2).map(c =>
      '<div class="could-row"><span class="could-text"><strong>' + escapeHTML(c.sku) + '</strong> ' + escapeHTML(c.description) + '</span>' +
      (resolved ? "" : '<button class="button secondary" data-act="confirm" data-cid="' + escapeHTML(c.candidate_id) + '">This one instead</button>') + '</div>').join("") + '</div>';
  }
  if (!shown.length) proposal += '<p class="hint">No suggestion. Search the catalog, or mark the line as not a product.</p>';
  let actions;
  if (resolved) actions = finished;
  else if (tab === "sure") actions = '<button class="link-button" data-act="move">Not right? Check it</button>';
  else actions = '<button class="button secondary" data-act="edit">' + (shown.length ? "Change product" : "Find the product") + '</button><button class="button secondary" data-act="not-product">Not a product</button>';
  const panel = !resolved && tab === "check" && (open || !shown.length) ? editPanelHTML() : "";
  return {pill, body, proposal, actions, panel};
}
function tabCardHTML(entry, tab, resolved) {
  const parts = cardParts(entry, tab, resolved);
  return '<article class="tab-card ' + TAB_INFO[tab].tone + '" data-row-id="' + escapeHTML(entry.row.row_id) + '" data-pending="' + (entry.done ? "0" : "1") + '" data-search="' + escapeHTML(entryText(entry)) + '">' +
    '<div class="card-head"><h3 class="line-title">' + escapeHTML(entryTitle(entry)) + '</h3>' + parts.pill + '</div>' +
    snapshotHTML(entry, tab) +
    '<div class="snap-tools"><button type="button" class="link-button" data-act="enlarge">Enlarge</button>' + (entry.lineIndex >= 0 ? '<button type="button" class="link-button" data-act="open-line">Open line</button>' : "") + '<span class="swipe-hint">Swipe sideways to see the whole line</span></div>' +
    '<div class="tab-card-body"><div class="tab-facts">' + parts.body + '</div><div class="tab-decision">' + (parts.proposal || "") + '<div class="tab-actions">' + parts.actions + '</div></div></div>' + (parts.panel || "") + '</article>';
}
function flaggedNoticeHTML() {
  if (!state.result?.extraction || !state.run) return "";
  const ids = loadMarks().flagged;
  const rows = state.result.extraction.rows.filter(row => ids.includes(row.row_id));
  if (!rows.length) return "";
  return '<div class="callout">' + rows.length + (rows.length === 1 ? " line was" : " lines were") + ' flagged as a possible product on this device: ' + rows.map(row => escapeHTML(row.description?.raw_value || "printed line")).join("; ") + '. The server cannot add them yet, so they are not in the spreadsheet.</div>';
}

function renderTabs() {
  stopStatusPolling(); revokeImages(); rememberDocument();
  const payload = state.result.extraction;
  if (!state.reviewer.trim()) { renderReviewerGate(() => renderDocument()); return; }
  const resolved = state.run.review_state === "resolved";
  const groups = assignTabs(payload, state.suggestions, state.events, loadMarks());
  const counts = tabCounts(groups);
  const ui = state.tabs;
  ui.snapFailed = new Set();
  ui.wholePage = wholePageCounts(payload, groups);
  if (!TAB_IDS.includes(ui.tab)) ui.tab = defaultTabOf(counts);
  const tab = ui.tab;
  const lines = Object.values(groups).flat().filter(e => e.lineIndex >= 0);
  const left = lines.filter(e => e.status === "unresolved").length;
  const total = lines.length;
  const show = ui.show[tab];
  // Ignored lines are always listed in full: nothing in that tab is ever "to do".
  const list = groups[tab].filter(e => tab === "not" || show === "all" || !e.done);
  const tabs = TAB_IDS.map(id => '<button role="tab" id="tab-' + id + '" class="tab ' + TAB_INFO[id].tone + (counts[id].total ? "" : " is-empty") + (id === "not" ? " quiet" : "") + '" aria-selected="' + (id === tab) + '" aria-controls="tab-panel" data-tab="' + id + '" tabindex="' + (id === tab ? 0 : -1) + '"><span class="tab-name">' + TAB_INFO[id].title + '</span><strong class="tab-count">' + counts[id].total + '</strong><small>' + (id === "not" ? (counts[id].total ? "optional" : "none") : counts[id].todo ? counts[id].todo + " " + TAB_INFO[id].todoWord : (counts[id].total ? "all done" : "none")) + '</small></button>').join("");
  const bulk = tab === "sure" && !resolved ? '<button id="bulk-confirm" class="button primary">Confirm all visible</button>' : "";
  const toolbar = '<div class="tab-toolbar"><label class="sr-only" for="tab-filter">Filter lines</label><input id="tab-filter" class="search-input" type="search" maxlength="80" placeholder="Filter lines" value="' + escapeHTML(ui.query) + '">' + (tab === "not" ? "" : '<div class="segmented" role="group" aria-label="Which lines"><button type="button" data-show="todo" aria-pressed="' + (show === "todo") + '">To do</button><button type="button" data-show="all" aria-pressed="' + (show === "all") + '">All</button></div>') + '' + bulk + '</div>';
  const emptyCopy = list.length ? null : emptyTabCopy(tab, counts, false);
  const intro = TAB_INFO[tab].intro + (tab === "check" && !counts.sure.total && counts.check.total ? " Nothing was sure this time, so every product line is here." : "");
  const emptyHTML = emptyCopy ? '<div class="tab-empty" id="tab-empty"><p>' + emptyCopy.text + '</p>' +
    (emptyCopy.goto ? '<button type="button" class="button primary" data-tab="' + emptyCopy.goto + '">Go to ' + TAB_INFO[emptyCopy.goto].title + ' (' + counts[emptyCopy.goto].total + ')</button>' : "") + '</div>'
    : '<p class="hint" id="tab-empty" hidden></p>';
  $("view").innerHTML = reviewerBarHTML() +
    '<section class="progress-block"><div class="progress-text"><strong>' + (left ? left + (left === 1 ? " line" : " lines") + " left to check" : "All lines checked") + '</strong> · ' + (total - left) + ' of ' + total + ' done</div><button id="reviewed-products" class="link-button">' + (resolved ? "Results" : "Summary") + '</button></section>' +
    '<progress id="review-progress" max="' + Math.max(total, 1) + '" value="' + (total - left) + '" aria-label="' + (total - left) + ' of ' + total + ' lines checked"></progress>' +
    '<div class="tablist" role="tablist" aria-label="Lines by confidence">' + tabs + '</div>' +
    '<section id="tab-panel" class="tab-panel ' + TAB_INFO[tab].tone + '" role="tabpanel" aria-labelledby="tab-' + tab + '"><p class="tab-intro">' + intro + '</p><div id="snap-banner" class="callout snap-banner" role="status" hidden></div>' + (groups[tab].length ? toolbar : "") +
    emptyHTML + '<div id="tab-cards">' + list.map(e => tabCardHTML(e, tab, resolved)).join("") + '</div></section>';
  wireReviewerBar(() => renderDocument());
  $("reviewed-products").onclick = () => renderSummary();
  wireTabs(groups, tab);
  applyFilter();
  updateSnapBanner();
  watchSnapshots($("tab-cards"));
}
function applyFilter() {
  const query = state.tabs.query.trim().toLowerCase();
  let visible = 0;
  const cards = [...document.querySelectorAll("#tab-cards .tab-card")];
  for (const card of cards) {
    const match = !query || card.dataset.search.includes(query);
    card.hidden = !match;
    if (match) visible++;
  }
  const empty = $("tab-empty");
  if (empty && cards.length) {
    empty.hidden = visible > 0;
    if (!visible) empty.textContent = "No line matches the filter.";
  }
  const bulk = $("bulk-confirm");
  if (bulk) {
    const n = document.querySelectorAll('#tab-cards .tab-card:not([hidden])[data-pending="1"]').length;
    bulk.textContent = n ? "Confirm all visible (" + n + ")" : "Confirm all visible";
    bulk.disabled = !n;
  }
}
function wireTabs(groups, tab) {
  const entries = Object.values(groups).flat();
  const find = id => entries.find(e => e.row.row_id === id);
  for (const button of document.querySelectorAll("[data-tab]")) button.onclick = () => { state.tabs.tab = button.dataset.tab; renderDocument(); };
  $("view").querySelector(".tablist").onkeydown = event => {
    const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
    if (!step) return;
    event.preventDefault();
    state.tabs.tab = TAB_IDS[(TAB_IDS.indexOf(tab) + step + TAB_IDS.length) % TAB_IDS.length];
    renderDocument();
    $("tab-" + state.tabs.tab)?.focus();
  };
  for (const button of document.querySelectorAll("[data-show]")) button.onclick = () => { state.tabs.show[tab] = button.dataset.show; renderDocument(); };
  // The toolbar is only rendered when the tab has lines, so an empty tab has no filter box.
  const filter = $("tab-filter");
  if (filter) filter.oninput = event => { state.tabs.query = event.target.value; applyFilter(); };
  if ($("bulk-confirm")) $("bulk-confirm").onclick = () => bulkConfirm(groups);
  const cards = $("tab-cards");
  cards.onclick = event => {
    const button = event.target.closest("[data-act]");
    const card = event.target.closest(".tab-card");
    if (!button || !card) return;
    const entry = find(card.dataset.rowId);
    if (entry) handleTabAction(button, card, entry, tab);
  };
  cards.onsubmit = event => {
    event.preventDefault();
    const form = event.target.closest("[data-form]");
    const card = event.target.closest(".tab-card");
    const entry = card && find(card.dataset.rowId);
    if (form && entry) handleTabForm(form, card, entry);
  };
}
async function reviewAction(work) {
  if (state.busy) return;
  state.busy = true; clearMessages();
  try { await work(); }
  catch (error) {
    try { await refreshAfterReview(); } catch {}
    fail(error);
    if (state.result?.extraction && state.mode === "tabs") renderDocument();
  } finally { state.busy = false; }
}
async function postReview(action, extra = {}, row = null) {
  const body = {action, ...readAttribution(), evidence_reference: row?.evidence || [], ...(row ? {row_id: row.row_id} : {}), ...extra};
  return api("/runs/" + state.run.id + "/reviews", {method: "POST", json: body});
}
async function refreshAfterReview() {
  state.run = await api("/runs/" + state.run.id);
  await loadRun();
  state.reason = "";
}
// One click on a suggestion is the human choice. An unclear line first records that exact choice, as the backend requires.
async function confirmEntry(entry, candidateId) {
  if (entry.tier === "uncertain" && entry.boundId !== candidateId) await postReview("this_is_product", {catalog_id: candidateId}, entry.row);
  await postReview("approve", {selected_candidate_id: candidateId}, entry.row);
}
function bulkConfirm(groups) {
  const visible = [...document.querySelectorAll("#tab-cards .tab-card:not([hidden])")].map(card => card.dataset.rowId);
  const targets = bulkTargets(groups.sure, visible);
  if (!targets.length) return;
  reviewAction(async () => {
    let saved = 0;
    try {
      for (const target of targets) {
        const entry = groups.sure.find(e => e.row.row_id === target.rowId);
        await postReview("approve", {selected_candidate_id: target.candidateId}, entry.row);
        saved++;
      }
    } finally {
      if (saved) await refreshAfterReview();
    }
    toast(saved + (saved === 1 ? " line confirmed." : " lines confirmed."));
    renderDocument();
  });
}
function handleTabAction(button, card, entry, tab) {
  const rowId = entry.row.row_id, act = button.dataset.act;
  if (act === "retry-snap") { pageImages.delete(state.source.id + ":" + (entry.row.evidence?.[0]?.page_number || 1)); paintSnapshot(card.querySelector("canvas.snap")); return; }
  if (act === "enlarge") { openSnapshot(entry, tab); return; }
  if (act === "open-line") { state.mode = "line"; state.row = entry.lineIndex; state.page = entry.row.evidence?.[0]?.page_number || state.page; renderDocument(); return; }
  if (act === "agree") { toggleMark("agreed", rowId, true); renderDocument(); return; }
  if (act === "unagree") { toggleMark("agreed", rowId, false); renderDocument(); return; }
  if (act === "flag") { toggleMark("flagged", rowId, true); renderDocument(); return; }
  if (act === "unflag") { toggleMark("flagged", rowId, false); renderDocument(); return; }
  if (act === "move") { toggleMark("moved", rowId, true); state.tabs.tab = "check"; renderDocument(); return; }
  if (act === "edit") { toggleMark("moved", rowId, true); state.tabs.edit[rowId] = true; state.tabs.tab = "check"; renderDocument(); return; }
  if (act === "confirm") {
    reviewAction(async () => {
      await confirmEntry(entry, button.dataset.cid);
      await refreshAfterReview();
      delete state.tabs.edit[rowId];
      toast("Confirmed.");
      renderDocument();
    });
    return;
  }
  if (act === "not-product") {
    reviewAction(async () => {
      await postReview("not_a_product", {}, entry.row);
      await refreshAfterReview();
      toggleMark("moved", rowId, false);
      delete state.tabs.edit[rowId];
      toast("Moved to Ignored lines.");
      renderDocument();
    });
    return;
  }
  if (act === "choose") {
    reviewAction(async () => {
      await postReview("this_is_product", {catalog_id: button.dataset.cid}, entry.row);
      await refreshAfterReview();
      delete state.tabs.edit[rowId];
      toast("Choice saved. Confirm it to finish this line.");
      renderDocument();
    });
  }
}
function handleTabForm(form, card, entry) {
  const row = entry.row;
  if (form.dataset.form === "search") {
    const target = card.querySelector("[data-results]");
    const runId = state.run.id;
    const query = state.run.catalog_pool_id ? "pool_id=" + state.run.catalog_pool_id : "vendor_id=" + state.run.vendor_id;
    api("/website/catalog?" + query + "&q=" + encodeURIComponent(form.elements.q.value)).then(result => {
      if (!target.isConnected || state.run.id !== runId) return;
      target.innerHTML = result.products.map(p => '<div class="product-row"><div class="product-copy"><span class="product-id">' + escapeHTML(p.sku) + '</span><strong>' + escapeHTML(p.description) + '</strong></div><button class="button secondary" data-act="choose" data-cid="' + escapeHTML(p.id) + '">Choose</button></div>').join("") || '<p class="hint">No products found. Try fewer letters, or add it as a new product.</p>';
    }).catch(fail);
    return;
  }
  const vendor = form.elements.vendor?.value;
  if (state.run.catalog_pool_id && !vendor) { fail(new Error("choose_catalog_vendor")); return; }
  reviewAction(async () => {
    await postReview("new_product", {product: {sku: form.elements.sku.value, description: form.elements.description.value}, decision_key: form.dataset.key, ...(vendor ? {vendor_id: vendor} : {})}, row);
    await refreshAfterReview();
    delete state.tabs.edit[row.row_id];
    toast("New product saved. Confirm it to finish this line.");
    renderDocument();
  });
}
async function openSnapshot(entry, tab) {
  const page = entry.row.evidence?.[0]?.page_number || 1;
  const box = regionBox(state.result.extraction, entry.row);
  $("dialog-title").textContent = entryTitle(entry);
  $("dialog-content").innerHTML = '<div class="segmented zoom-switch" role="group" aria-label="View"><button type="button" data-zoom="row" aria-pressed="true">This line</button><button type="button" data-zoom="page" aria-pressed="false">Whole page ' + page + '</button></div><div class="enlarged-source"><div class="snap-frame loading"><canvas class="snap zoom" role="img" aria-label="Enlarged snapshot"></canvas><div class="snap-skeleton">Loading the picture…</div><div class="snap-fallback"><span>The picture did not load.</span></div></div></div>';
  $("detail-dialog").showModal();
  const canvas = $("dialog-content").querySelector("canvas"), frame = canvas.closest(".snap-frame");
  const paint = async mode => {
    try {
      const image = await pageImage(page);
      drawSnapshot(canvas, image, box, TAB_INFO[tab].color, mode === "page" ? {page: true} : {padY: 0.07, minWidth: 0.85});
      frame.classList.remove("loading", "failed");
    } catch { frame.classList.remove("loading"); frame.classList.add("failed"); }
  };
  for (const button of $("dialog-content").querySelectorAll("[data-zoom]")) button.onclick = () => {
    for (const other of $("dialog-content").querySelectorAll("[data-zoom]")) other.setAttribute("aria-pressed", String(other === button));
    paint(button.dataset.zoom);
  };
  paint("row");
}

window.addEventListener("pagehide", stopStatusPolling);
