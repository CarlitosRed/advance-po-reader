"use strict";
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
    state.poc = !state.defaultPool && state.catalogs.length > 0 && state.catalogs.every(c => c.synthetic) && !configuration.provider_configured;
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
    $("view").innerHTML = `${bar}<section class="panel summary-left"><p class="eyebrow">ALMOST THERE</p><h1>${pending.length} ${pending.length === 1 ? "line" : "lines"} left to check</h1><p class="hint">${done} of ${lines.length} checked. Products are listed here once every line has an answer.</p><progress max="${lines.length}" value="${done}" aria-label="${done} of ${lines.length} lines checked"></progress><div class="line-list">${pending.map(id => { const index = lines.findIndex(row => row.row_id === id); return index < 0 ? "" : `<button class="queue-button" data-row="${index}"><span>Line ${index + 1} · ${escapeHTML(lineTitle(lines[index]))}</span><small>${pillHTML(lineModel(lines[index]))}</small></button>`; }).join("")}</div><div class="stack"><button id="back-review" class="button primary big">Continue checking</button><button id="finish-review" class="button secondary big" disabled>Finish review</button></div></section>${details}`;
    wireReviewerBar(() => renderSummary());
    $("back-review").onclick = () => { state.row = Math.max(0, lines.findIndex(row => row.row_id === pending[0])); renderDocument(); };
    for (const button of document.querySelectorAll("[data-row]")) button.onclick = () => { state.row = Number(button.dataset.row); renderDocument(); };
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
    ${table}
    <div class="stack"><button id="download-csv" class="button ${resolved ? "primary" : "secondary"} big" ${items.length ? "" : "disabled"}>Download as spreadsheet</button><button id="back-review" class="button secondary big">← Back to the lines</button></div>${details}`;
  wireReviewerBar(() => renderSummary());
  $("back-review").onclick = () => renderDocument();
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

window.addEventListener("pagehide", stopStatusPolling);
