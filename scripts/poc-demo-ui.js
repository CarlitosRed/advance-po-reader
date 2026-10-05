"use strict";
let pocInfo, pocCSRF;
const pocElement = id => document.getElementById(id);
async function pocRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (pocInfo) headers.set("X-Tenant-ID", pocInfo.tenant_id);
  if (options.method) headers.set("X-Website-CSRF", pocCSRF);
  if (options.json) { headers.set("Content-Type", "application/json"); options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, {...options, headers, credentials:"same-origin", cache:"no-store"});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "request_failed");
  return value;
}
function pocFailure(error) {
  pocElement("poc-error").hidden = false;
  pocElement("poc-error").textContent = error.message;
}
async function pocInitialize() {
  await fetch("/", {credentials:"same-origin", cache:"no-store"});
  pocCSRF = (await pocRequest("/website/session")).csrf;
  pocInfo = await pocRequest("/poc-demo/info");
  for (const item of pocInfo.cases) {
    const link = document.createElement("a");
    link.className = "button secondary"; link.href = item.route;
    link.textContent = item.title; pocElement("poc-cases").append(link);
  }
  for (const filename of pocInfo.files) {
    const link = document.createElement("a"); link.className = "button quiet";
    link.href = "/poc-demo/files/" + encodeURIComponent(filename); link.textContent = filename;
    link.download = filename; pocElement("poc-files").append(link);
  }
  pocElement("poc-upload").onsubmit = async event => {
    event.preventDefault(); const button = pocElement("poc-submit"); button.disabled = true;
    pocElement("poc-error").hidden = true;
    try {
      const body = new FormData(); body.set("vendor_id", pocInfo.vendor_id); body.set("file", pocElement("poc-file").files[0]);
      const source = await pocRequest("/documents", {method:"POST", body, headers:{"Idempotency-Key":crypto.randomUUID()}});
      let run = await pocRequest("/documents/" + source.id + "/runs", {method:"POST", json:{provider:"synthetic"}, headers:{"Idempotency-Key":crypto.randomUUID()}});
      run = await pocRequest("/runs/" + run.id + "/process", {method:"POST"});
      if (!["completed", "partial"].includes(run.state)) throw new Error(run.outcome_code || "poc_unknown_fixture_bytes");
      location.href = "/#document=" + source.id + "&run=" + run.id;
    } catch (error) { pocFailure(error); button.disabled = false; }
  };
}
pocInitialize().catch(pocFailure);
