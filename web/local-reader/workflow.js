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
    renderReadiness();
    if (state.readiness.database !== "ready") {
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

function renderSummary() {
  stopStatusPolling();
  revokeImages();
  rememberDocument(true);
  const summary = state.summary;
  if (!summary) { fail(new Error("review_summary_unavailable")); return; }
  const approved = summary.approved_products;
  const pending = summary.pending_row_ids;
  const resolved = summary.review_state === "resolved";
  const payload = state.result.extraction;
  $("view").innerHTML = `<div class="section-top"><div><p class="eyebrow">REVIEWED PRODUCTS · STEP 3 OF 3</p><h1>Your reviewed products.</h1><p class="hint">${approved.length} approved product line(s) · ${pending.length} source row(s) still need review${state.run.provider === "synthetic" ? " · fictional sample" : ""}</p></div><button id="back-review" class="button secondary">Back to source review</button></div>
    <div class="summary-list">${approved.map(item => `<div class="summary-row"><div><span class="product-id">${escapeHTML(item.candidate.sku)}</span><strong>${escapeHTML(item.candidate.description)}</strong><p>${escapeHTML(item.description || "")}${(item.continuation_descriptions || []).map(part => `<br><span class="hint">${escapeHTML(part.raw_description)}</span>`).join("")}</p><p>Approved by ${escapeHTML(item.reviewer)} · source ${escapeHTML(item.row_id)}</p></div><div class="summary-quantity"><strong>${escapeHTML(item.quantity ?? "[unresolved]")}</strong><span>${escapeHTML(item.unit ?? "[unit unresolved]")}</span></div></div>`).join("")}</div>
    ${approved.length ? "" : '<div class="panel empty">No product has been approved yet.</div>'}
    ${summary.document_details?.length ? `<details class="panel field document-details"><summary>Document details and other source evidence · ${summary.document_details.length}</summary>${summary.document_details.map(item => `<div class="audit-event"><strong>${escapeHTML(item.row_kind)} · ${escapeHTML(item.role)}</strong><p>${escapeHTML(item.description ?? item.raw_description ?? "")}</p><p>Amount: ${escapeHTML(item.line_total ?? "[not present]")}</p><small>${escapeHTML(item.row_id)}</small></div>`).join("")}</details>` : ""}
    <section class="panel field"><h2>${resolved ? "Review complete" : "Finish the source review"}</h2><p class="field">Product rows require candidate approval or a no-match decision. Ambiguous item rows require clarification. Typed charges, totals and notes remain inspectable under document details.</p>
    ${pending.length ? `<div class="callout">${pending.length} row(s) remain unresolved. Return to the source review to decide them.</div>` : ""}
    ${summary.excluded_rows.length ? `<p class="hint">${summary.excluded_rows.length} non-product or no-match line(s) are retained in the audit history.</p>` : ""}
    ${resolved ? '<span class="badge green">Saved · review resolved</span>' : attributionHTML() + '<div id="page-count-checks"></div><div id="document-acknowledgements"></div><div class="button-row"><button id="finish-review" class="button primary" ' + (summary.can_finish_review ? "" : "disabled") + '>Finish review</button></div>'}
    ${auditHTML()}</section>`;
  $("back-review").onclick = () => renderDocument();
  wireAttribution();
  if (resolved) return;
  renderPageCounts();
  const partial = payload.pages.filter(page => page.state === "partial" && !state.events.some(event =>
    event.action === "acknowledge_page" && event.evidence_reference.some(ref => ref.page_number === page.page_number)));
  const needsWarnings = payload.warnings.length && !state.events.some(event => event.action === "acknowledge_document");
  $("document-acknowledgements").innerHTML = partial.map(page => `<div class="callout">Page ${page.page_number} was only partially observed: ${escapeHTML(page.uncertainty || "check the whole page")}<div class="button-row"><button class="button secondary" data-ack-page="${page.page_number}">Acknowledge page uncertainty</button></div></div>`).join("") +
    (needsWarnings ? `<div class="callout">${payload.warnings.map(escapeHTML).join("<br>")}<div class="button-row"><button class="button secondary" id="ack-warnings">Acknowledge document warnings</button></div></div>` : "") +
    (summary.blockers.includes("failed_pages_require_new_processing_run") ? '<div class="callout">A page failed. This review cannot be completed; create a new processing run after checking the source.</div>' : "");
  for (const button of document.querySelectorAll("[data-ack-page]")) button.onclick = () => saveReview("acknowledge_page", {
    evidence_reference: [{page_number: Number(button.dataset.ackPage), region_reference: null}]}).then(renderSummary).catch(fail);
  if ($("ack-warnings")) $("ack-warnings").onclick = () => saveReview("acknowledge_document", {
    evidence_reference: [{page_number: payload.pages[0].page_number, region_reference: null}]}).then(renderSummary).catch(fail);
  $("finish-review").onclick = () => saveReview("resolve").then(renderSummary).catch(fail);
}

function renderPageCounts() {
  $("page-count-checks").innerHTML = (state.summary.page_coverage || []).map(check => `
    <div class="callout" data-coverage-page="${check.page_number}"><h3>Page ${check.page_number} · product count ${escapeHTML(check.status)}</h3>
    <p>Extracted product items: ${check.provider_product_count}. Independent source count: ${check.independent_product_count ?? "not yet counted"}.</p>
    ${check.reviewer ? `<p class="hint">Counted by ${escapeHTML(check.reviewer)} · ${escapeHTML(check.reason)}</p>` : ""}
    <button class="button secondary" data-count-source="${check.page_number}">Inspect this source page</button>
    ${check.status === "mismatch" ? '<p>A source line discrepancy requires a new run of this same saved document, with fresh page checks and product approvals. Keep this run and its evidence. Do not lower the count to hide a missing line.</p><button class="button secondary" data-new-count-run>Prepare a new run of this source</button>' : ""}
    ${check.source_discrepancy ? '<p>The reviewer confirmed a source discrepancy. This run stays blocked.</p>' : `
    <form data-page-count="${check.page_number}"><label>Products on this source page <input name="product_count" type="number" min="0" max="100000" step="1" required value="${check.independent_product_count ?? ""}"></label>
    <p class="hint">Count each source product once; omit description continuations, charges, totals and notes. This count does not approve any product.</p>
    ${check.latest_event_id ? '<label><input name="count_error" type="checkbox" required> My prior independent count was mistaken. I rechecked the source; this corrects count evidence only.</label>' : '<label><input name="source_discrepancy" type="checkbox"> The source still has missing or extra product lines in this extraction; a new run is required.</label>'}
    <button class="button secondary">${check.latest_event_id ? "Save attributed count correction" : "Confirm independent source count"}</button></form>`}</div>`).join("");
  for (const button of document.querySelectorAll("[data-count-source]")) button.onclick = () => {
    state.page = Number(button.dataset.countSource); renderDocument();
  };
  for (const button of document.querySelectorAll("[data-new-count-run]")) button.onclick = async () => {
    if (state.busy) return;
    state.busy = true;
    try {
      state.run = await api("/documents/" + state.source.id + "/runs", {method: "POST",
        json: {provider: state.run.provider}, headers: {"Idempotency-Key": crypto.randomUUID()}});
      await loadRun(); renderDocument();
    } catch (error) { fail(error); } finally { state.busy = false; }
  };
  for (const form of document.querySelectorAll("[data-page-count]")) form.onsubmit = async event => {
    event.preventDefault();
    if (state.busy) return;
    try {
      const attribution = readAttribution();
      const page = Number(form.dataset.pageCount);
      const check = state.summary.page_coverage.find(value => value.page_number === page);
      state.busy = true;
      await api("/runs/" + state.run.id + "/page-counts", {method: "POST", json: {
        ...attribution, page_number: page, source_sha256: state.source.sha256,
        product_count: Number(form.elements.product_count.value),
        source_discrepancy: form.elements.source_discrepancy?.checked || false,
        ...(check.latest_event_id ? {corrects_event_id: check.latest_event_id, correction_kind: "independent_count_error"} : {})}});
      state.run = await api("/runs/" + state.run.id); await loadRun(); renderSummary();
    } catch (error) { fail(error); } finally { state.busy = false; }
  };
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
