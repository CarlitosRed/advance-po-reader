"use strict";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {csrf:"",workspace:null,catalog:null,catalogs:[],pools:[],defaultPool:null,library:[],configuration:null,readiness:null,summary:null,runReadiness:null,processingRequest:null,view:"upload",source:null,run:null,name:"",page:1,row:0,reviewer:"",reason:"",result:null,suggestions:[],events:[],urls:[],busy:false,poc:false,openAnswers:{},imageCache:new Map()};
function clearMessages(){ $("error").hidden=true; $("notice").hidden=true; }
function errorText(error){const messages={selected_candidate_outside_current_binding:"Select the product bound to this line, or save a new product binding before approving.",uncertain_requires_explicit_product_binding:"Save one of the three line answers before approving this uncertain product.",uncertain_requires_three_way_decision:"Choose a product, add a new product, or mark this as not a product.",choose_catalog_vendor:"Choose the catalog vendor for this new product.",product_exists_use_this_is_product:"This product code already exists. Choose that catalog product instead.",review_idempotency_payload_conflict:"This saved decision has different product fields. Reload the line before changing it.",cancelled_by_local_user:"This run was cancelled. Any request already submitted may still finish; its receipt remains in the saved attempt.",remote_outcome_unknown_no_retry:"The provider connection was interrupted and its outcome is unknown. No automatic retry was made.",provider_server_outcome_unknown_no_retry:"The provider returned a server error with an unknown outcome. Keep this attempt before considering another request.",provider_unfinished_no_retry:"The provider result is unfinished. No automatic retry was made.",processing_in_progress_or_unknown_outcome:"An attempt is already running or its outcome is unknown. Check its saved status before continuing.",provider_http_401:"OpenAI rejected the server credential. Check the server API setup before starting a new run.",provider_http_429:"OpenAI returned a rate or quota limit. No automatic retry was made.",provider_not_configured:"Configure and enable the server API connection before real extraction.",external_processing_authorization_required:"Record authorization for this exact source before real processing.",local_database_unavailable:"Start the preserved local PostgreSQL database and check the connection.",database_unavailable:"The local database is unavailable. Check the connection before continuing.",provider_incomplete:"The provider returned an incomplete result. Keep this attempt for review.",upload_too_large:"This file exceeds the upload limit.",page_outside_document:"That page is outside the document.",malformed_pdf:"This PDF is damaged or cannot be decoded. Choose another original file.",encrypted_pdf:"Choose an unencrypted PDF for this local workflow.",pdf_page_limit:"This PDF exceeds the page limit.",pdf_dimensions_invalid:"This PDF has unsupported page dimensions.",unsupported_media_type:"Choose a PDF, JPG or PNG file.",animated_image_unsupported:"Choose a still image.",image_dimension_limit:"The image dimensions exceed the supported limit.",file_decode_failed:"This file cannot be decoded as a supported document.",file_decode_failed_or_timed_out:"This file could not be decoded within the supported limits.",website_csrf_required:"Reload the page to reopen your local browser session.",catalog_selection_required:"Choose a catalog for this document first.",default_catalog_pool_setup_required:"Configure a tenant default All products catalog before uploading or searching.",review_attribution_required:"Enter your name before saving an answer.",choose_candidate:"Pick a product before confirming.",poc_unknown_fixture_bytes:"This free preview can only read the sample orders. Try one from “Try a sample order”.",preview_unavailable:"The picture of this line could not be drawn.",choose_one_document:"Choose one document at a time.",unsupported_file_type:"Choose a PDF, JPG or PNG file.",selected_candidate_outside_snapshot:"Choose or propose a product from this catalog before approving.",unresolved_rows_remain:"Review every source row before finishing.",resolved_review_is_immutable_create_new_run:"This review is complete. Start a new run for further changes.",website_session_required:"Reload this page to reopen your local session.",source_integrity_failed:"The stored source failed its integrity check.",invalid_request:"Check the required fields and try again."}; return messages[error.message] || ("The action could not be completed ("+error.message+").");}
function fail(error){if(error.message==="local_api_token_required")error=new Error("website_session_required");$("error").textContent=errorText(error);$("error").hidden=false;$("error").scrollIntoView({block:"nearest"});}
async function api(path, options={}){
  const headers=new Headers(options.headers||{});
  if(state.workspace) headers.set("X-Tenant-ID",state.workspace.id);
  if(options.method && options.method!=="GET")headers.set("X-Website-CSRF",state.csrf);
  if(options.json){headers.set("Content-Type","application/json");options.body=JSON.stringify(options.json);delete options.json;}
  const response=await fetch(path,{...options,headers,credentials:"same-origin",cache:"no-store"});
  if(!response.ok){let problem;try{problem=await response.json();}catch{problem={error:"server_unavailable"};}throw new Error(problem.error||"request_failed");}
  return options.binary?response.blob():response.json();
}
function revokeImages(){for(const url of state.urls)URL.revokeObjectURL(url);state.urls=[];}
async function imageInto(element,path,attempt=0){
 const frame=element.closest(".img-frame");
 if(frame){frame.classList.remove("failed");frame.classList.add("loading");const retry=frame.querySelector("[data-retry-image]");if(retry)retry.onclick=()=>imageInto(element,path,0);}
 try{let blob=state.imageCache.get(path);
  if(!blob){blob=await api(path,{binary:true});if(!(blob.type||"").startsWith("image/"))throw new Error("preview_unavailable");state.imageCache.set(path,blob);if(state.imageCache.size>16)state.imageCache.delete(state.imageCache.keys().next().value);}
  if(!element.isConnected)return;
  const url=URL.createObjectURL(blob);state.urls.push(url);
  element.onload=()=>{if(frame)frame.classList.remove("loading");};
  element.onerror=()=>{if(frame){frame.classList.remove("loading");frame.classList.add("failed");}};
  element.src=url;
 }catch(error){
  if(!element.isConnected)return;
  // One quiet retry covers a slow first render; after that show an inline "Try again" instead of bare alt text.
  if(attempt<1){setTimeout(()=>imageInto(element,path,attempt+1),800);return;}
  if(frame){frame.classList.remove("loading");frame.classList.add("failed");}else{element.alt="Source preview unavailable";fail(error);}
 }
}
function toast(text){$("toast").textContent=text;$("toast").hidden=false;setTimeout(()=>{$("toast").hidden=true;},3500);}
function setView(view){if(state.poc){location.href="/poc-demo";return;}stopStatusPolling();if(location.hash!=="#"+view)history.pushState({view},"","#"+view);if(state.catalog?.synthetic)state.catalog=null;state.view=view;clearMessages();revokeImages();for(const button of document.querySelectorAll("[data-view]")){if(button.dataset.view===view)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");}if(view==="upload")renderUpload();else if(view==="library")renderLibrary();else if(view==="catalog")renderCatalog();}
function chooseCatalog(id){state.catalog=state.catalogs.find(c=>c.id===id)||state.pools.find(c=>c.id===id)||null;}
function catalogScopeQuery(catalog=state.catalog){return catalog?.is_pool?"pool_id="+encodeURIComponent(catalog.id):"vendor_id="+encodeURIComponent(catalog?.id||"");}
function renderUpload(){
 if(!state.defaultPool){$("view").innerHTML='<section class="panel"><h1>All products setup is required.</h1><p class="field">Configure a tenant default catalog pool before uploading a document. Existing vendor catalogs and saved runs remain available.</p></section>';return;}
 state.catalog=state.defaultPool;
 $("view").innerHTML='<section class="intro"><p class="eyebrow">PURCHASE ORDER IMPORT</p><h1>Start with your purchase order.</h1><p>Upload once. OrderLens searches the configured All products catalog and keeps each source catalog visible.</p></section><div class="upload-layout"><section class="panel"><div class="panel-heading"><h2>Upload a document</h2><span class="badge">Step 1 of 3</span></div><div class="callout"><strong>'+escapeHTML(state.defaultPool.name)+'</strong> · '+state.defaultPool.product_count.toLocaleString()+' products across '+state.defaultPool.member_count+' source catalogs</div><div class="dropzone" id="dropzone"><div class="upload-symbol" aria-hidden="true">↥</div><h3>Drop your purchase order here</h3><p>A PDF, a scan, or a photo of your order.</p><button class="button primary" id="browse-file">Choose a file</button><p class="hint">PDF, JPG or PNG · up to '+Math.floor(state.configuration.limits.upload_bytes/1048576)+' MB</p><input id="file-input" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" hidden></div><p class="privacy-note">Saved privately on this computer. You authorize each document before external reading.</p><button class="sample-button" id="sample-order"><span><strong>Try a sample purchase order</strong><small>Fictional products · saved review and audit</small></span><span class="badge">DEMO</span></button></section><aside class="panel"><h2>A little less manual entry.</h2><div class="flow-item"><span class="flow-number">01</span><div><h3>Search every authorized source</h3><p>All products appears as one catalog while each result keeps its original source and ID.</p></div></div><div class="flow-item"><span class="flow-number">02</span><div><h3>Check the source evidence</h3><p>Review descriptions, identifiers and raw quantities alongside the original document.</p></div></div><div class="flow-item"><span class="flow-number">03</span><div><h3>Confirm the reviewed products</h3><p>Your decisions are saved with your name, reason and source reference.</p></div></div><div class="callout">The '+state.library.length+' original PDFs are available in the document library, using the same default pool.</div><button class="button quiet" id="open-library">Open document library →</button></aside></div><section id="saved-documents"></section>';
 $("browse-file").onclick=()=>$("file-input").click();
 $("file-input").onchange=e=>{if(e.target.files[0])startUpload(e.target.files[0]).catch(fail);};
 $("open-library").onclick=()=>setView("library");
 $("sample-order").onclick=()=>startSample().catch(fail);
 const zone=$("dropzone");zone.ondragover=e=>{e.preventDefault();zone.classList.add("dragover");};zone.ondragleave=()=>zone.classList.remove("dragover");zone.ondrop=e=>{e.preventDefault();zone.classList.remove("dragover");if(e.dataTransfer.files.length!==1){fail(new Error("choose_one_document"));return;}startUpload(e.dataTransfer.files[0]).catch(fail);};
 loadSaved();
}
async function loadSaved(){const area=$("saved-documents");const selectedCatalog=state.catalog;if(!area)return;if(!state.defaultPool){area.innerHTML="";return;}try{const result=await api("/documents?pool_id="+encodeURIComponent(state.defaultPool.id));if(!area.isConnected||state.defaultPool?.id!==selectedCatalog.id)return;area.innerHTML='<div class="section-top"><div><h2>Saved in '+escapeHTML(state.defaultPool.name)+'</h2><p class="hint">Uploads and runs stay available after refresh.</p></div></div><div class="document-list">'+result.documents.map(d=>'<div class="document-row"><div class="document-copy"><strong>Document · '+escapeHTML(d.sha256.slice(0,12))+'</strong><p>'+d.page_count+' page(s) · '+new Date(d.created_at).toLocaleString()+'</p></div><button class="button secondary" data-source="'+d.id+'">Open document</button></div>').join("")+'</div>';for(const button of area.querySelectorAll("[data-source]"))button.onclick=()=>openSource(button.dataset.source).catch(fail);}catch(error){fail(error);}}
function showLoading(title,copy){$("view").innerHTML='<section class="panel loading-panel"><div class="loading-brands"><img src="/web-assets/assets/smartercommerce.png" alt="SmarterCommerce"><span class="loading-dot" aria-hidden="true"></span><span class="werner-logo"><img src="/web-assets/assets/werner.jpg" alt="Werner"></span></div><h1>'+escapeHTML(title)+'</h1><p>'+escapeHTML(copy)+'</p><progress aria-label="'+escapeHTML(title)+'"></progress></section>';}
async function startUpload(file,synthetic=false){
 if(state.busy)return;if(!synthetic&&!state.defaultPool)throw new Error("default_catalog_pool_setup_required");
 if(file.size>state.configuration.limits.upload_bytes)throw new Error("upload_too_large");
 if(!/\.(pdf|jpe?g|png)$/i.test(file.name))throw new Error("unsupported_file_type");
 clearMessages();state.busy=true;showLoading("Saving your document","Validating the file and preserving its original source.");
 try{const body=new FormData();if(synthetic)body.set("vendor_id",state.catalog.id);body.set("file",file);
 state.source=await api("/documents",{method:"POST",body,headers:{"Idempotency-Key":crypto.randomUUID()}});
 state.name=file.name;state.page=1;state.row=0;
 state.run=await api("/documents/"+state.source.id+"/runs",{method:"POST",json:synthetic?{provider:"synthetic",fixture_name:"purchase_order"}:{provider:"openai"},headers:{"Idempotency-Key":crypto.randomUUID()}});
 if(synthetic){showLoading("Preparing the sample review","Using known fictional source bytes. No external provider request.");await api("/runs/"+state.run.id+"/process",{method:"POST"});state.run=await api("/runs/"+state.run.id);}
 await loadRun();renderDocument();
 }catch(error){renderUpload();throw error;}finally{state.busy=false;}
}
async function startSample(){const catalog=state.catalogs.find(c=>c.synthetic);if(!catalog)throw new Error("sample_not_available");chooseCatalog(catalog.id);const blob=await api("/website/demo-document",{binary:true});await startUpload(new File([blob],"synthetic-purchase-order.pdf",{type:"application/pdf"}),true);}
async function openSource(id,runId=null){stopStatusPolling();state.source=await api("/documents/"+id);state.catalog=state.source.catalog_pool_id?state.pools.find(c=>c.id===state.source.catalog_pool_id):state.catalogs.find(c=>c.id===state.source.vendor_id);state.name=state.library.find(d=>d.sha256===state.source.sha256)?.filename||(state.catalog?.synthetic?"synthetic-purchase-order.pdf":"Saved document · "+state.source.sha256.slice(0,12));state.page=1;const result=await api("/documents/"+id+"/runs");state.run=(runId?result.runs.find(r=>r.id===runId):null)||result.runs.at(-1)||null;if(state.run)state.run=await api("/runs/"+state.run.id);await loadRun();renderDocument();}
async function loadRun(){if(!state.run){state.result=null;state.summary=null;state.runReadiness=null;state.events=[];state.suggestions=[];return;}const runId=state.run.id;const results=await Promise.all([api("/runs/"+runId+"/result"),api("/runs/"+runId+"/suggestions"),api("/runs/"+runId+"/reviews"),api("/runs/"+runId+"/summary"),api("/runs/"+runId+"/readiness")]);if(state.run?.id!==runId)return;[state.result,{suggestions:state.suggestions},{events:state.events},state.summary,state.runReadiness]=results;}
function renderPendingDocument(){revokeImages();$("view").innerHTML='<div class="section-top"><div><p class="eyebrow">DOCUMENT SAVED</p><h1>Your source is ready.</h1><p class="hint">'+escapeHTML(state.name)+' · '+escapeHTML(state.catalog.name)+'</p></div><button id="back-upload" class="button secondary">Back to upload</button></div><div class="review-layout"><aside class="panel source-panel"><h2>Source document</h2>'+imageFrameHTML("source-page","Original document page")+'<p class="source-meta">'+state.source.page_count+' page(s) · SHA-256 '+escapeHTML(state.source.sha256.slice(0,16))+'…</p></aside><section class="panel"><span class="badge amber">Awaiting API setup</span><h2 class="field">Document reading is the next connection.</h2><p>The original file is saved. No products have been extracted from this document yet.</p><div class="callout">You can browse the real catalogs and use the fictional sample to exercise the review workflow.</div><div class="button-row"><button class="button secondary" id="view-catalog">Browse this catalog</button><button class="button secondary" id="use-sample">Try the sample review</button></div></section></div>';
 $("back-upload").onclick=()=>setView("upload");$("view-catalog").onclick=()=>setView("catalog");$("use-sample").onclick=()=>startSample().catch(fail);imageInto($("source-page"),"/documents/"+state.source.id+"/pages/"+state.page);}
function renderLibrary(){ if(!state.defaultPool){$("view").innerHTML='<section class="panel"><h1>All products setup is required.</h1><p class="field">Configure a tenant default catalog pool before starting a library document.</p></section>';return;}state.catalog=state.defaultPool;$("view").innerHTML='<section class="intro"><p class="eyebrow">ORIGINAL EMAIL BATCH</p><h1>Your document library.</h1><p>'+state.library.length+' original PDFs, preserved locally. New runs use '+escapeHTML(state.defaultPool.name)+' ('+state.defaultPool.product_count.toLocaleString()+' products).</p></section><div class="document-list">'+state.library.map(d=>'<div class="document-row"><div class="document-copy"><strong>'+escapeHTML(d.document_id)+' · '+escapeHTML(d.filename)+'</strong><p>'+d.page_count+' page(s) · awaiting extraction</p></div><button class="button secondary" data-library="'+d.sha256+'">Use document</button></div>').join("")+'</div>';
 for(const button of document.querySelectorAll("[data-library]"))button.onclick=async()=>{try{const d=state.library.find(d=>d.sha256===button.dataset.library);const blob=await api("/website/corpus/"+d.sha256+"/content",{binary:true});await startUpload(new File([blob],d.filename,{type:"application/pdf"}));}catch(error){fail(error);}};}
function renderCatalog(offset=0,q=""){const catalogVersion=(state.catalogVersion||0)+1;state.catalogVersion=catalogVersion;if(!state.defaultPool){$("view").innerHTML='<section class="panel"><h1>All products setup is required.</h1><p class="field">Configure a tenant default catalog pool before browsing the aggregate catalog.</p></section>';return;}state.catalog=state.defaultPool;const selectedCatalog=state.defaultPool;$("view").innerHTML='<section class="intro"><p class="eyebrow">ALL PRODUCTS</p><h1>Find the right product.</h1><p>One searchable view across '+selectedCatalog.member_count+' authorized source catalogs. Every result keeps its original product ID and source.</p></section><div class="callout"><strong>'+escapeHTML(selectedCatalog.name)+'</strong> · '+selectedCatalog.product_count.toLocaleString()+' products</div><form id="catalog-search" class="search-bar"><label class="sr-only" for="catalog-query">Search products by ID or name</label><input class="search-input" id="catalog-query" value="'+escapeHTML(q)+'" placeholder="Search by product ID or name" maxlength="120"><button class="button primary">Search</button></form><p id="catalog-count" class="hint"></p><div id="catalog-results" class="product-list"></div><div id="catalog-pager" class="pager"></div>';
 $("catalog-search").onsubmit=e=>{e.preventDefault();renderCatalog(0,$("catalog-query").value);};
 api("/website/catalog?pool_id="+selectedCatalog.id+"&offset="+offset+"&q="+encodeURIComponent(q)).then(result=>{if(!$("catalog-results")||state.defaultPool?.id!==selectedCatalog.id||state.catalogVersion!==catalogVersion||state.view!=="catalog")return;$("catalog-count").textContent=result.total.toLocaleString()+" products in "+selectedCatalog.name;$("catalog-results").innerHTML=result.products.map(p=>'<div class="product-row"><div class="product-copy"><span class="product-id">'+escapeHTML(p.sku)+'</span><strong>'+escapeHTML(p.description)+'</strong><small>'+escapeHTML(p.origin_vendor)+' · '+escapeHTML(p.origin_catalog)+'</small></div><button class="button secondary" data-detail="'+p.id+'">Details</button></div>').join("")||'<div class="panel empty">No products found in this pool.</div>';for(const button of document.querySelectorAll("[data-detail]"))button.onclick=()=>productDetail(button.dataset.detail).catch(fail);$("catalog-pager").innerHTML=(offset?'<button id="previous-products" class="button secondary">Previous</button>':'')+(result.next_offset!==null?'<button id="next-products" class="button secondary">Next</button>':'');if($("previous-products"))$("previous-products").onclick=()=>renderCatalog(Math.max(0,offset-30),q);if($("next-products"))$("next-products").onclick=()=>renderCatalog(result.next_offset,q);}).catch(fail);
}
async function productDetail(id){const detail=await api("/website/catalog/"+id+"?"+catalogScopeQuery());$("dialog-title").textContent=detail.product.description;$("dialog-content").innerHTML='<span class="product-id">'+escapeHTML(detail.product.sku)+'</span><p>Origin: '+escapeHTML(detail.product.origin||"import")+'</p><p class="hint">'+escapeHTML(detail.source?.origin_vendor||"Source")+' · '+escapeHTML(detail.source?.origin_catalog||"")+' · source row '+escapeHTML(detail.source?.source_row_number??"fictional sample")+'</p>'+(detail.source?'<dl class="detail-grid">'+Object.entries(detail.source.raw_fields).filter(([k,v])=>v!==null&&v!==""&&!k.endsWith("_json")&&!["catalog_id","source_row_number"].includes(k)).map(([k,v])=>'<div><dt>'+escapeHTML(k.replaceAll("_"," "))+'</dt><dd>'+escapeHTML(v)+'</dd></div>').join("")+'</dl><h3>Attributes</h3><dl class="detail-grid">'+detail.source.attributes.map(a=>'<div><dt>'+escapeHTML(a.attribute_label_raw)+'</dt><dd>'+escapeHTML(a.attribute_value_display??a.attribute_value_raw)+'</dd></div>').join("")+'</dl>':(detail.product.origin==="review"?'<p>Product added by a customer during review.</p>':'<p>Fictional product used only by the synthetic sample.</p>'));if(detail.source?.detail_sections?.length){$("dialog-content").insertAdjacentHTML("beforeend",'<h3>Catalog detail sections</h3>'+detail.source.detail_sections.map(section=>{let fields={};try{fields=JSON.parse(section.raw_detail_fields_json);}catch{}return '<details class="audit"><summary>'+escapeHTML(section.detail_section_label_raw||"Details")+'</summary><dl class="detail-grid">'+Object.entries(fields).filter(([k,v])=>v!==null&&v!=="").map(([k,v])=>'<div><dt>'+escapeHTML(k)+'</dt><dd>'+escapeHTML(typeof v==="object"?JSON.stringify(v):v)+'</dd></div>').join("")+'</dl></details>';}).join(""));}$("detail-dialog").showModal();}
document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>setView(button.dataset.view));$("close-dialog").onclick=()=>$("detail-dialog").close();
function latestDecision(rowId){return state.events.filter(e=>e.row_id===rowId).at(-1)||null;}
function effectiveValue(row,field){const change=state.events.filter(e=>e.row_id===row.row_id&&e.action==="correct"&&e.new_value.field_name===field).at(-1);return change?change.new_value.value:row[field]?.raw_value;}
function rowState(row){const event=latestDecision(row.row_id);if(event?.action==="no_match"&&(row.row_kind==="unknown"||state.suggestions.find(s=>s.row_id===row.row_id)?.tier==="uncertain"))return "unresolved";return event&&["approve","no_match","not_a_product","not_product"].includes(event.action)?event.action:"unresolved";}
function rowRole(row,payload){if(payload.schema_version==="1.2")return row.row_role;if(row.row_kind==="product")return "product_item";if(["charge","tax","subtotal","total","note"].includes(row.row_kind))return "document_detail";return "unknown";}
function productCardCount(payload){return new Set(payload.rows.filter(row=>rowRole(row,payload)==="product_item").map(row=>row.item_group_id||row.row_id)).size;}
function rememberDocument(summary=false){const target="#document="+state.source.id+"&run="+(state.run?.id||"")+(summary?"&summary=1":"");if(location.hash!==target)history.pushState({source:state.source.id},"",target);}
function renderDocument(){stopStatusPolling();
 revokeImages();rememberDocument();
 state.view="upload";document.querySelectorAll("[data-view]").forEach(b=>{if(b.dataset.view==="upload")b.setAttribute("aria-current","page");else b.removeAttribute("aria-current");});
 if(state.result?.extraction && ["completed","partial"].includes(state.run?.state)){renderReview();return;}
 renderPendingDocument();enhancePending();
}
function sourcePanel(){return '<aside class="panel source-panel"><div class="panel-heading"><h2>Source document</h2><span class="badge '+(state.run?.provider==="synthetic"?"blue":"amber")+'">'+(state.run?.provider==="synthetic"?"Fictional sample":"Original file")+'</span></div>'+imageFrameHTML("source-page","Original source page "+state.page)+'<div class="source-nav"><button id="previous-page" class="button secondary" '+(state.page<=1?'disabled':'')+' aria-label="Previous document page">←</button><span>Page '+state.page+' of '+state.source.page_count+'</span><button id="next-page" class="button secondary" '+(state.page>=state.source.page_count?'disabled':'')+' aria-label="Next document page">→</button></div><p class="source-meta">'+escapeHTML(state.name)+'<br>Catalog: '+escapeHTML(state.catalog.name)+'<br>SHA-256: '+escapeHTML(state.source.sha256.slice(0,16))+'…</p><div class="button-row"><button class="button secondary" id="enlarge-source">Enlarge source</button><button class="button quiet" id="download-source">Download original file</button></div></aside>';}
function wireSource(){if($("enlarge-source"))$("enlarge-source").onclick=()=>openEnlarged(state.page);imageInto($("source-page"),"/documents/"+state.source.id+"/pages/"+state.page);if($("previous-page"))$("previous-page").onclick=()=>{state.page--;renderDocument();};if($("next-page"))$("next-page").onclick=()=>{state.page++;renderDocument();};if($("download-source"))$("download-source").onclick=async()=>{try{const blob=await api("/documents/"+state.source.id+"/content",{binary:true});const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=state.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){fail(error);}};}
/* ---------- Reviewer identity: asked once, remembered on this device ---------- */
const REVIEWER_KEY="advance-po-reader.reviewer";
function storedReviewer(){try{return localStorage.getItem(REVIEWER_KEY)||"";}catch{return "";}}
function rememberReviewer(name){try{localStorage.setItem(REVIEWER_KEY,name);}catch{}}
state.reviewer=storedReviewer();
function defaultReason(){return state.run?.provider==="synthetic"?"Reviewed in the demo":"Reviewed against the source document";}
function readAttribution(){const reviewer=String(state.reviewer||"").trim();if(!reviewer)throw new Error("review_attribution_required");return {reviewer,reason:String(state.reason||"").trim()||defaultReason()};}
function reviewerBarHTML(){return '<div class="reviewer-bar">'+(state.poc?'<a class="link-button" href="/poc-demo">← Orders</a>':'<button class="link-button" id="back-upload">← Back to upload</button>')+'<span class="reviewer-name">Reviewing as <strong>'+escapeHTML(state.reviewer)+'</strong> · <button class="link-button" id="change-reviewer">Change</button></span></div>';}
function wireReviewerBar(next){if($("back-upload"))$("back-upload").onclick=()=>setView("upload");if($("change-reviewer"))$("change-reviewer").onclick=()=>renderReviewerGate(next,true);}
function renderReviewerGate(next,changing=false){
 stopStatusPolling();revokeImages();
 $("view").innerHTML='<section class="panel gate"><p class="eyebrow">'+(changing?'REVIEWER':'BEFORE YOU START')+'</p><h1>Who is reviewing?</h1><p>Your name is saved with every answer so the team knows who checked what. We remember it on this device.</p><form id="reviewer-form"><div class="field"><label for="reviewer">Your name</label><input id="reviewer" maxlength="120" autocomplete="name" value="'+escapeHTML(state.reviewer)+'" required></div><div class="stack"><button class="button primary big">'+(changing?'Save name':'Start reviewing')+'</button>'+(changing&&state.reviewer.trim()?'<button type="button" id="cancel-reviewer" class="button secondary big">Cancel</button>':'')+'</div></form></section>';
 $("reviewer").focus();
 $("reviewer-form").onsubmit=e=>{e.preventDefault();const name=$("reviewer").value.trim();if(!name)return;state.reviewer=name;rememberReviewer(name);next();};
 if($("cancel-reviewer"))$("cancel-reviewer").onclick=()=>next();
}

/* ---------- Line helpers ---------- */
function lineList(payload){return payload.rows.filter(r=>["product_item","unknown"].includes(rowRole(r,payload)));}
function rowCode(row){const id=row.identifiers.find(i=>i.raw_value);return id?id.raw_value:"";}
function lineTitle(row){const code=rowCode(row);if(code)return code;const words=String(row.description?.raw_value||"").trim().split(/\s+/).filter(Boolean).slice(0,5).join(" ");return words||"Unnamed line";}
function candidatesFor(row){const original=state.suggestions.find(s=>s.row_id===row.row_id)?.candidates||[];const proposals=state.events.filter(e=>e.row_id===row.row_id&&["propose_candidate","this_is_product","new_product"].includes(e.action)).flatMap(e=>e.new_value.candidates);return [...new Map([...original,...proposals].map(c=>[c.candidate_id,c])).values()];}
function lineModel(row){
 const suggestion=state.suggestions.find(s=>s.row_id===row.row_id);const candidates=candidatesFor(row);const status=rowState(row);const tier=suggestion?.tier||"uncertain";
 const last=state.events.filter(e=>e.row_id===row.row_id&&["this_is_product","new_product","not_a_product","not_product"].includes(e.action)).at(-1);
 const bound=last&&["this_is_product","new_product"].includes(last.action)?last.new_value?.candidates?.[0]?.candidate_id:null;
 // Only a Certain match is pre-selected; Probable is shown as a suggestion; Uncertain needs one of the three answers.
 const guessId=bound||(tier==="certain"?suggestion.suggested_candidate_id:tier==="probable"?candidates[0]?.candidate_id:null);
 return {row,suggestion,candidates,status,tier,guess:candidates.find(c=>c.candidate_id===guessId)||null,preselected:!bound&&tier==="certain",chosen:Boolean(bound),decided:status!=="unresolved"};
}
function pillFor(m){if(m.status==="approve")return ["green","Confirmed"];if(m.decided)return ["gray","Not a product"];if(m.guess)return ["blue","Looks right"];return ["amber","Needs your help"];}
function pillHTML(m){const [tone,text]=pillFor(m);return '<span class="pill '+tone+'">'+text+'</span>';}
function fact(label,html){return '<div class="fact"><dt>'+label+'</dt><dd>'+html+'</dd></div>';}
function alternatives(observation){return observation?.alternative_readings?.length?'<small class="alt">Could also read as: '+escapeHTML(observation.alternative_readings.join(" / "))+'</small>':"";}
function correctedNote(printed,effective){return effective!==printed?'<small class="alt">Printed as '+escapeHTML(printed??"nothing")+' · corrected by you</small>':"";}
function factsHTML(row,payload,role){
 const code=rowCode(row);const printedDescription=row.description?.raw_value;const description=effectiveValue(row,"description");
 const continuations=payload.rows.filter(item=>rowRole(item,payload)==="continuation"&&(payload.schema_version==="1.2"?item.continuation_of===row.row_id:item.item_group_id===(row.item_group_id||row.row_id)));
 const quantity=effectiveValue(row,"quantity");const unit=effectiveValue(row,"unit");const price=effectiveValue(row,"unit_price");const total=effectiveValue(row,"line_total");
 const empty='<span class="none">Not printed</span>';
 const quantityText=[quantity,unit].filter(v=>v!==null&&v!==undefined&&String(v).trim()!=="").join(" ");
 const priceFact=(price!==null&&price!==undefined&&String(price).trim()!=="")?fact("Price",escapeHTML(price)+alternatives(row.unit_price)+correctedNote(row.unit_price?.raw_value,price)):(total!==null&&total!==undefined&&String(total).trim()!==""?fact("Line total",escapeHTML(total)+correctedNote(row.line_total?.raw_value,total)):"");
 return '<dl class="facts">'+fact("Code",code?escapeHTML(code)+row.identifiers.filter(i=>i.raw_value).map(alternatives).join(""):'<span class="none">No code printed</span>')
  +fact("Description",(description?'<span class="desc-line">'+escapeHTML(description)+'</span>':empty)+continuations.map(item=>'<span class="desc-line">'+escapeHTML(item.description.raw_value)+'</span>').join("")+alternatives(row.description)+correctedNote(printedDescription,description))
  +fact("Quantity",(quantityText?escapeHTML(quantityText):empty)+alternatives(row.quantity)+correctedNote(row.quantity?.raw_value,quantity))+priceFact+'</dl>';
}
function imageFrameHTML(id,label,extra=""){return '<div class="img-frame loading '+extra+'" role="img" aria-label="'+escapeHTML(label)+'"><img id="'+id+'" alt=""><div class="img-skeleton">Loading the picture…</div><div class="img-fallback"><span>The picture did not load.</span> <button type="button" class="link-button" data-retry-image>Try again</button></div></div>';}
function openEnlarged(page){$("dialog-title").textContent="Source page "+page;$("dialog-content").innerHTML='<p class="hint">Scroll to read the printed values.</p><div class="enlarged-source">'+imageFrameHTML("enlarged-page","Enlarged source page "+page)+'</div>';$("detail-dialog").showModal();imageInto($("enlarged-page"),"/documents/"+state.source.id+"/pages/"+page);}
function candidateCardHTML(c,label,preselected){return '<div class="guess" data-preselected="'+Boolean(preselected)+'"><span class="guess-label">'+label+'</span><strong class="guess-code">'+escapeHTML(c.sku)+'</strong><span class="guess-desc">'+escapeHTML(c.description)+'</span>'+(c.origin==="review"?'<small>Added by a reviewer</small>':'')+'</div>';}

function detailsHTML(m,payload){
 const row=m.row;const why=row.uncertainty||m.suggestion?.tier_reason||m.suggestion?.reason||"";
 return '<details class="more"><summary>Details</summary><dl class="detail-grid"><div><dt>Source file</dt><dd>'+escapeHTML(state.name)+'</dd></div><div><dt>Catalog</dt><dd>'+escapeHTML(state.catalog?.name||"")+'</dd></div><div><dt>Source page</dt><dd>'+(row.evidence[0]?.page_number||"unknown")+' of '+state.source.page_count+'</dd></div><div><dt>Line id</dt><dd>'+escapeHTML(row.row_id)+'</dd></div><div><dt>SHA-256</dt><dd>'+escapeHTML(state.source.sha256)+'</dd></div><div><dt>Run id</dt><dd>'+escapeHTML(state.run.id)+'</dd></div></dl>'+(why?'<p class="hint">'+escapeHTML(why)+'</p>':"")+'<div class="button-row"><button class="button secondary" id="download-source">Download original file</button></div>'+auditHTML()+'</details>';
}
function auditHTML(){return '<details class="audit"><summary>Review history · '+state.events.length+' event(s)</summary>'+state.events.map(e=>'<div class="audit-event"><strong>'+escapeHTML(e.action.replaceAll("_"," "))+'</strong> · '+escapeHTML(e.reviewer)+'<p>'+escapeHTML(e.row_id||"Whole document")+' · '+new Date(e.created_at).toLocaleString()+'</p><p>'+escapeHTML(e.reason)+'</p>'+(e.action==="correct"?'<p>'+escapeHTML(e.new_value.field_name)+': '+escapeHTML(e.old_value?.value??"[empty]")+' → '+escapeHTML(e.new_value.value??"[cleared]")+'</p>':'')+'</div>').join("")+'</details>';}
function correctionHTML(row){
 const names={description:"Description",quantity:"Quantity",unit:"Unit",unit_price:"Price",line_total:"Line total"};
 return '<details class="more"><summary>Something misread? Correct a value</summary><p class="hint">The printed value stays on record. Enter the value you read on the source.</p><form id="correction-form"><div class="field"><label for="correction-field">Which value</label><select id="correction-field">'+Object.entries(names).map(([f,n])=>'<option value="'+f+'">'+n+'</option>').join("")+row.identifiers.flatMap((id,i)=>[["raw_value","printed text"],["source_label","label"],["source_role","type"]].map(([f,n])=>'<option value="identifier.'+f+':'+i+'">Code '+(i+1)+' · '+n+'</option>')).join("")+'</select></div><div class="field"><label for="correction-value">Correct value</label><input id="correction-value" maxlength="2000" type="text"></div><label class="hint"><input id="clear-value" type="checkbox"> Clear the value instead</label><div class="button-row"><button class="button secondary">Save correction</button></div></form></details>';
}

function questionHTML(m){
 const vendors=(state.catalogs||[]).filter(v=>!state.run.catalog_pool_id||(state.catalog.vendor_ids||[]).includes(v.id));
 const vendorHTML=state.run.catalog_pool_id?'<div class="field"><label for="new-product-vendor">Which catalog</label><select id="new-product-vendor" required><option value="">Choose catalog</option>'+vendors.map(v=>'<option value="'+escapeHTML(v.id)+'">'+escapeHTML(v.name)+'</option>').join('')+'</select></div>':'';
 const suggestions=m.candidates.map(c=>'<div class="product-row"><div class="product-copy"><span class="product-id">'+escapeHTML(c.sku)+'</span><strong>'+escapeHTML(c.description)+'</strong></div><button class="button secondary" data-propose="'+escapeHTML(c.candidate_id)+'">Choose</button></div>').join("");
 return '<section class="question review-answers"><h3>Which product is this?</h3><div class="answers"><button class="answer" id="answer-existing" aria-expanded="false" aria-controls="panel-existing"><strong>Pick an existing product</strong><small>Search the catalog</small></button><button class="answer" id="answer-new" aria-expanded="false" aria-controls="panel-new"><strong>It’s a new product</strong><small>Add it to the catalog</small></button><button class="answer" id="answer-not-product"><strong>Not a product</strong><small>For example a note, charge or delivery line</small></button></div>'
  +'<div class="answer-panel" id="panel-existing" hidden>'+(suggestions?'<p class="hint">From the catalog:</p><div class="search-results">'+suggestions+'</div>':'')+'<form id="manual-search" class="search-bar"><label class="sr-only" for="manual-query">Search the catalog by code or name</label><input id="manual-query" class="search-input" maxlength="120" placeholder="Code or name"><button class="button secondary">Search</button></form><div id="manual-results" class="search-results"></div></div>'
  +'<div class="answer-panel" id="panel-new" hidden><form id="new-product-form"><div class="field"><label for="new-product-sku">Product code</label><input id="new-product-sku" maxlength="200" required></div><div class="field"><label for="new-product-description">Product description</label><input id="new-product-description" maxlength="4000" required></div>'+vendorHTML+'<button class="button primary big">Save new product</button></form></div>'
  +(m.decided?'<button id="keep-answer" class="link-button">← Keep my current answer</button>':m.guess?'<button id="back-to-guess" class="link-button">← Back to the suggestion</button>':'')+'</section>';
}

function noteHTML(){return '<details class="note"><summary>Add a note (optional)</summary><input id="review-reason" maxlength="500" value="'+escapeHTML(state.reason)+'" placeholder="Anything worth remembering about this line"></details>';}
function decisionAreaHTML(m,resolved){
 const row=m.row;
 if(m.decided&&!state.openAnswers[row.row_id]){
  const approved=state.summary?.approved_products?.find(a=>a.row_id===row.row_id)?.candidate;
  return '<div class="decided">'+(m.status==="approve"&&approved?'<span class="check" aria-hidden="true">✓</span><p>You confirmed <strong>'+escapeHTML(approved.sku)+'</strong> · '+escapeHTML(approved.description)+'</p>':'<span class="check muted" aria-hidden="true">–</span><p>You marked this line as <strong>not a product</strong>. It will not be ordered.</p>')+'</div>'+(resolved?'<p class="hint">This review is finished.</p>':'<button class="button secondary big" id="change-answer">Change my answer</button>');
 }
 if(resolved)return '<p class="hint">This review is finished.</p>';
 if(m.guess&&!state.openAnswers[row.row_id]){
  return candidateCardHTML(m.guess,m.preselected?"Best guess · matches the printed code":m.chosen?"Your choice · please confirm":"Best guess · please check",m.preselected)+'<button class="button primary big" id="approve-row">Yes, this one</button><button class="button secondary big" id="pick-another">Pick another</button>'+noteHTML();
 }
 return questionHTML(m)+noteHTML();
}

function renderReview(){
 const payload=state.result.extraction;
 if(!state.reviewer.trim()){renderReviewerGate(()=>renderDocument());return;}
 const lines=lineList(payload);state.row=Math.min(Math.max(state.row,0),Math.max(lines.length-1,0));
 const resolved=state.run.review_state==="resolved";const models=lines.map(lineModel);const left=models.filter(m=>!m.decided).length;
 const m=models[state.row];
 const header=reviewerBarHTML();
 if(!m){$("view").innerHTML=header+'<section class="panel"><h2>No product lines were found.</h2><p>This document needs a new reading before it can be reviewed.</p></section>';wireReviewerBar(()=>renderDocument());return;}
 const row=m.row;const page=row.evidence[0]?.page_number||state.page;
 $("view").innerHTML=header+'<section class="progress-block"><div class="progress-text"><strong>Line '+(state.row+1)+' of '+lines.length+'</strong> · '+(left?left+' left to check':'all checked')+'</div><button id="reviewed-products" class="link-button">'+(resolved?'Results':'Summary')+'</button></section><progress id="review-progress" max="'+lines.length+'" value="'+(lines.length-left)+'" aria-label="'+(lines.length-left)+' of '+lines.length+' lines checked"></progress>'
  +'<article class="line-card" id="decision-panel" aria-live="polite"><div class="card-head"><h2 class="line-title">'+escapeHTML(lineTitle(row))+'</h2>'+pillHTML(m)+'</div>'
  +'<div class="evidence">'+imageFrameHTML("row-preview","Printed line "+(state.row+1)+" from the source document")+'<button id="enlarge-source" class="link-button">Enlarge source</button></div>'
  +factsHTML(row,payload,rowRole(row,payload))+'<div class="decision-area">'+decisionAreaHTML(m,resolved)+'</div></article>'
  +'<nav class="line-nav" aria-label="Lines"><button id="prev-line" class="button secondary" '+(state.row<=0?'disabled':'')+'>← Back</button><button id="next-line" class="button secondary">'+(state.row>=lines.length-1?'Summary →':'Next →')+'</button></nav>'
  +'<details class="more all-lines"><summary>All lines · '+lines.length+'</summary><div class="line-list">'+models.map((x,i)=>'<button class="queue-button" data-row="'+i+'" aria-pressed="'+(i===state.row)+'"><span>Line '+(i+1)+' · '+escapeHTML(lineTitle(x.row))+'</span><small>'+pillHTML(x)+'</small></button>').join("")+'</div></details>'
  +(resolved?"":correctionHTML(row))+detailsHTML(m,payload);
 wireReviewerBar(()=>renderDocument());
 const go=index=>{state.row=index;state.page=lines[index].evidence[0]?.page_number||state.page;renderDocument();};
 $("reviewed-products").onclick=()=>renderSummary();
 $("prev-line").onclick=()=>go(state.row-1);
 $("next-line").onclick=()=>{if(state.row>=lines.length-1)renderSummary();else go(state.row+1);};
 for(const button of document.querySelectorAll("[data-row]"))button.onclick=()=>go(Number(button.dataset.row));
 $("enlarge-source").onclick=()=>openEnlarged(page);
 if($("download-source"))$("download-source").onclick=async()=>{try{const blob=await api("/documents/"+state.source.id+"/content",{binary:true});const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=state.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){fail(error);}};
 imageInto($("row-preview"),"/runs/"+state.run.id+"/rows/"+encodeURIComponent(row.row_id)+"/preview");
 if(resolved)return;
 const advance={advance:true};
 if($("change-answer"))$("change-answer").onclick=()=>{state.openAnswers[row.row_id]=true;renderDocument();};
 if($("approve-row"))$("approve-row").onclick=()=>saveReview("approve",{selected_candidate_id:m.guess.candidate_id},row,advance).catch(fail);
 if($("pick-another"))$("pick-another").onclick=()=>{state.openAnswers[row.row_id]=true;renderDocument();};
 if($("keep-answer"))$("keep-answer").onclick=()=>{delete state.openAnswers[row.row_id];renderDocument();};
 if($("back-to-guess"))$("back-to-guess").onclick=()=>{delete state.openAnswers[row.row_id];renderDocument();};
 wireQuestion(row);
 if($("review-reason"))$("review-reason").oninput=e=>{state.reason=e.target.value;};
 $("correction-form").onsubmit=e=>{e.preventDefault();const [field,index]=$("correction-field").value.split(":");saveReview("correct",{field_name:field,new_value:$("clear-value").checked?null:$("correction-value").value,...(index!==undefined?{identifier_index:Number(index)}:{})},row).catch(fail);};
}

function wireQuestion(row){
 if(!$("answer-existing"))return;
 const toggle=(button,panel)=>{const open=$(panel).hidden;for(const [b,p] of [["answer-existing","panel-existing"],["answer-new","panel-new"]]){$(p).hidden=true;$(b).setAttribute("aria-expanded","false");}$(panel).hidden=!open;button.setAttribute("aria-expanded",String(open));if(open)$(panel).querySelector("input")?.focus();};
 $("answer-existing").onclick=e=>toggle(e.currentTarget,"panel-existing");
 $("answer-new").onclick=e=>toggle(e.currentTarget,"panel-new");
 $("answer-not-product").onclick=()=>saveReview("not_a_product",{},row,{advance:true}).catch(fail);
 const choose=target=>{for(const button of target.querySelectorAll("[data-propose]"))button.onclick=()=>saveReview("this_is_product",{catalog_id:button.dataset.propose},row).catch(fail);};
 choose($("panel-existing"));
 $("manual-search").onsubmit=async e=>{e.preventDefault();try{const target=$("manual-results");const currentRun=state.run.id;const query=state.run.catalog_pool_id?"pool_id="+state.run.catalog_pool_id:"vendor_id="+state.run.vendor_id;const result=await api("/website/catalog?"+query+"&q="+encodeURIComponent($("manual-query").value));if(!target.isConnected||state.run.id!==currentRun)return;target.innerHTML=result.products.map(p=>'<div class="product-row"><div class="product-copy"><span class="product-id">'+escapeHTML(p.sku)+'</span><strong>'+escapeHTML(p.description)+'</strong></div><button class="button secondary" data-propose="'+p.id+'">Choose</button></div>').join("")||'<p class="hint">No products found. Try fewer letters, or add it as a new product.</p>';choose(target);}catch(error){fail(error);}};
 const form=$("new-product-form");form.dataset.decisionKey=crypto.randomUUID();
 form.onsubmit=event=>{event.preventDefault();const vendor=$("new-product-vendor")?.value;if(state.run.catalog_pool_id&&!vendor){fail(new Error("choose_catalog_vendor"));return;}saveReview("new_product",{product:{sku:$("new-product-sku").value,description:$("new-product-description").value},decision_key:form.dataset.decisionKey,...(vendor?{vendor_id:vendor}:{})},row).catch(fail);};
}

async function saveReview(action, extra={}, row=null, options={}){
 if(state.busy)return;const attribution=readAttribution();state.busy=true;clearMessages();
 try{const body={action,...attribution,evidence_reference:row?.evidence||[],...(row?{row_id:row.row_id}:{}),...extra};
 await api("/runs/"+state.run.id+"/reviews",{method:"POST",json:body});state.run=await api("/runs/"+state.run.id);await loadRun();state.reason="";toast("Saved.");
 if(row)delete state.openAnswers[row.row_id];
 if(options.advance&&row&&advanceAfterDecision(row))return;
 renderDocument();
 }finally{state.busy=false;}
}
function advanceAfterDecision(row){
 // After an explicit answer, move to the next line that still needs one; show the summary when none is left.
 const payload=state.result.extraction;const lines=lineList(payload);const here=lines.findIndex(r=>r.row_id===row.row_id);
 for(let step=1;step<=lines.length;step++){const index=(here+step)%lines.length;if(rowState(lines[index])==="unresolved"){state.row=index;state.page=lines[index].evidence[0]?.page_number||state.page;renderDocument();return true;}}
 renderSummary();return true;
}

async function restoreRoute(){const hash=location.hash.slice(1);if(hash.startsWith("document=")){const parameters=new URLSearchParams(hash);const id=parameters.get("document");if(/^[a-f0-9-]{36}$/.test(id||"")){await openSource(id,parameters.get("run"));if(parameters.get("summary")==="1"&&state.result?.extraction)renderSummary();return;}}setView(["upload","library","catalog"].includes(hash)?hash:"upload");}
window.addEventListener("popstate",()=>restoreRoute().catch(fail));
function registerBrowserTools(){
 const context=document.modelContext;if(!context?.registerTool)return;
 const lifecycle=new AbortController();window.addEventListener("pagehide",()=>lifecycle.abort(),{once:true});
 const tools=[
  {name:"get_local_reader_state",title:"Read local reader state",description:"Read the currently selected catalog, source run state and review counts. Does not approve products or process documents.",
   inputSchema:{type:"object",properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},
   execute(input){if(!input||typeof input!=="object"||Object.keys(input).length)throw new Error("invalid_input");const runCatalog=state.run?.catalog_pool_id?state.pools.find(c=>c.id===state.run.catalog_pool_id):state.catalogs.find(c=>c.id===state.source?.vendor_id);return {view:state.view,selected_catalog:state.catalog?{name:state.catalog.name,product_count:state.catalog.product_count,synthetic:state.catalog.synthetic}:null,default_catalog_pool:state.defaultPool?{name:state.defaultPool.name,product_count:state.defaultPool.product_count,member_count:state.defaultPool.member_count}:null,library_documents:state.library.length,last_open_run:state.run?{catalog:runCatalog?{name:runCatalog.name,synthetic:runCatalog.synthetic}:null,processing_state:state.run.state,review_state:state.run.review_state,review_events:state.events.length}:null,provider_configured:state.configuration?.provider_configured||false};}},
  {name:"search_selected_catalog",title:"Search selected catalog",description:"Read products by ID or name within the catalog already selected in the interface. Returns catalog records only; no match, proposal or approval is made.",
   inputSchema:{type:"object",properties:{query:{type:"string",maxLength:120}},required:["query"],additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},
   async execute(input){if(!input||typeof input.query!=="string"||input.query.length>120||Object.keys(input).some(k=>k!=="query"))throw new Error("invalid_input");if(!state.defaultPool)throw new Error("default_catalog_pool_setup_required");const result=await api("/website/catalog?pool_id="+state.defaultPool.id+"&q="+encodeURIComponent(input.query));return {catalog:state.defaultPool.name,products:result.products,total:result.total};}}
 ];
 for(const tool of tools){try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}}
}
registerBrowserTools();
initialize();
