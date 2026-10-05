"use strict";
let pocInfo, pocCSRF;
const pocElement = id => document.getElementById(id);
const POC_SAMPLE_LABELS = {
  "demo-three-tiers": "Order with clear codes",
  "demo-description": "Order with codes inside descriptions",
  "demo-three-answers": "Order with unclear lines"
};
const POC_MESSAGES = {
  poc_unknown_fixture_bytes: "This free preview can only read the sample orders. Open one under “Try a sample order”.",
  unsupported_media_type: "Choose a PDF, PNG or JPG file.",
  unsupported_file_type: "Choose a PDF, PNG or JPG file.",
  upload_too_large: "That file is too large. Choose a smaller one.",
  malformed_pdf: "That PDF could not be opened. Choose another file.",
  encrypted_pdf: "That PDF is password-protected. Choose an unprotected file.",
  file_decode_failed: "That file could not be read. Choose a different PDF or photo.",
  file_decode_failed_or_timed_out: "That file could not be read. Choose a different PDF or photo.",
  pdf_page_limit: "That PDF has too many pages for this preview.",
  image_dimension_limit: "That photo is too large for this preview.",
  animated_image_unsupported: "Choose a still photo, not an animation.",
  website_session_required: "Reload this page and try again."
};
async function pocRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (pocInfo) headers.set("X-Tenant-ID", pocInfo.tenant_id);
  if (options.method) headers.set("X-Website-CSRF", pocCSRF);
  if (options.json) { headers.set("Content-Type", "application/json"); options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, {...options, headers, credentials: "same-origin", cache: "no-store"});
  let value;
  try { value = await response.json(); } catch { value = {}; }
  if (!response.ok) throw new Error(value.error || "request_failed");
  return value;
}
function pocFailure(error) {
  pocElement("poc-error").hidden = false;
  pocElement("poc-error").textContent = POC_MESSAGES[error.message] || "Something went wrong. Please try again.";
  pocElement("poc-error").scrollIntoView({block: "nearest"});
}
function pocLabel(item) { return POC_SAMPLE_LABELS[item.id] || item.title; }
function pocBusy(busy, title, hint) {
  const area = pocElement("poc-drop");
  area.setAttribute("aria-busy", String(busy));
  pocElement("poc-file").disabled = busy;
  pocElement("poc-drop-title").textContent = busy ? title : "Choose a PDF or photo";
  pocElement("poc-drop-hint").textContent = busy ? hint : "or drop it here · PDF, PNG or JPG";
}
async function pocUpload(file) {
  pocElement("poc-error").hidden = true;
  if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) { pocFailure(new Error("unsupported_file_type")); return; }
  pocBusy(true, "Reading your order…", "This takes a few seconds.");
  try {
    const body = new FormData(); body.set("vendor_id", pocInfo.vendor_id); body.set("file", file);
    const source = await pocRequest("/documents", {method: "POST", body, headers: {"Idempotency-Key": crypto.randomUUID()}});
    // The same file already has a review in progress: reopen it so earlier answers are kept.
    const earlier = (await pocRequest("/documents/" + source.id + "/runs")).runs.filter(run => ["completed", "partial"].includes(run.state)).at(-1);
    if (earlier) { location.href = "/#document=" + source.id + "&run=" + earlier.id; return; }
    let run = await pocRequest("/documents/" + source.id + "/runs", {method: "POST", json: {provider: "synthetic"}, headers: {"Idempotency-Key": crypto.randomUUID()}});
    run = await pocRequest("/runs/" + run.id + "/process", {method: "POST"});
    if (!["completed", "partial"].includes(run.state)) throw new Error(run.outcome_code || "poc_unknown_fixture_bytes");
    location.href = "/#document=" + source.id + "&run=" + run.id;
  } catch (error) { pocFailure(error); pocBusy(false); pocElement("poc-file").value = ""; }
}
function pocWhen(value) {
  const date = new Date(value);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? "Today " + date.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : date.toLocaleDateString([], {month: "short", day: "numeric"});
}
async function pocOrder(source) {
  const sample = pocInfo.cases.find(item => item.source_id === source.id);
  try {
    const run = (await pocRequest("/documents/" + source.id + "/runs")).runs.filter(item => ["completed", "partial"].includes(item.state)).at(-1);
    if (!run) return null;
    const [summary, result] = await Promise.all([pocRequest("/runs/" + run.id + "/summary"),
      sample ? Promise.resolve(null) : pocRequest("/runs/" + run.id + "/result").catch(() => null)]);
    const reviewed = summary.approved_products.length + summary.excluded_rows.length;
    const total = reviewed + summary.pending_row_ids.length;
    const number = result?.extraction?.document_number?.raw_value;
    return {href: "/#document=" + source.id + "&run=" + run.id, reviewed, total, created: source.created_at,
      label: sample ? pocLabel(sample) : (number ? "Order " + number : "Uploaded order")};
  } catch { return null; }
}
async function pocLoadOrders() {
  const list = pocElement("poc-orders");
  const documents = (await pocRequest("/documents?vendor_id=" + encodeURIComponent(pocInfo.vendor_id) + "&limit=12")).documents;
  const orders = (await Promise.all(documents.map(pocOrder))).filter(Boolean);
  list.replaceChildren();
  if (!orders.length) { const none = document.createElement("p"); none.className = "hint"; none.textContent = "No orders yet. Upload one above or try a sample."; list.append(none); return; }
  for (const order of orders) {
    const card = document.createElement("a"); card.className = "order-card"; card.href = order.href;
    const title = document.createElement("strong"); title.textContent = order.label;
    const meta = document.createElement("small");
    meta.textContent = (order.total && order.reviewed >= order.total ? "All " + order.total + " reviewed" : order.reviewed + " of " + order.total + " reviewed") + " · " + pocWhen(order.created);
    const bar = document.createElement("progress"); bar.max = Math.max(order.total, 1); bar.value = order.reviewed;
    bar.setAttribute("aria-label", order.reviewed + " of " + order.total + " reviewed");
    card.append(title, meta, bar); list.append(card);
  }
}
async function pocInitialize() {
  await fetch("/", {credentials: "same-origin", cache: "no-store"});
  pocCSRF = (await pocRequest("/website/session")).csrf;
  pocInfo = await pocRequest("/poc-demo/info");
  for (const item of pocInfo.cases) {
    const link = document.createElement("a");
    link.className = "button secondary big"; link.href = item.route;
    link.textContent = pocLabel(item); pocElement("poc-cases").append(link);
    const row = document.createElement("p"); row.append(pocLabel(item) + ": ");
    for (const [extension, name] of [["pdf", "PDF"], ["png", "Photo (PNG)"], ["jpg", "Photo (JPG)"]]) {
      const filename = item.id + "." + extension;
      if (!pocInfo.files.includes(filename)) continue;
      const file = document.createElement("a"); file.href = "/poc-demo/files/" + encodeURIComponent(filename);
      file.download = filename; file.textContent = name; row.append(file);
    }
    pocElement("poc-files").append(row);
  }
  const input = pocElement("poc-file"), area = pocElement("poc-drop");
  input.onchange = () => { if (input.files[0]) pocUpload(input.files[0]); };
  area.ondragover = event => { event.preventDefault(); area.classList.add("dragover"); };
  area.ondragleave = () => area.classList.remove("dragover");
  area.ondrop = event => {
    event.preventDefault(); area.classList.remove("dragover");
    if (event.dataTransfer.files.length !== 1) { pocFailure(new Error("unsupported_file_type")); return; }
    pocUpload(event.dataTransfer.files[0]);
  };
  await pocLoadOrders();
}
pocInitialize().catch(error => { pocFailure(error); pocElement("poc-orders").replaceChildren(); });
