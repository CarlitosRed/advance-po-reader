/* Static sample workflow. No transport, persistence, or agent approval hooks. */
(() => {
  'use strict';
  const view = document.getElementById('view');
  const catalog = window.SAMPLE_CATALOG.map(product => ({...product}));
  const state = {stage:'upload', rows:[], drafts:{}, file:null, fileUrl:null, accepted:false, readingToken:0};
  const units = ['EA','PK','BOX'];
  const paths = {
    check:'<path d="m5 12 4 4L19 6"/>',
    arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
    upload:'<path d="M12 17V4m-5 5 5-5 5 5M5 16v4h14v-4"/>',
    file:'<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8m-8 4h6"/>',
    scan:'<path d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M7 12h10"/>',
    shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 11l3 3 5-5"/>',
    search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    minus:'<circle cx="12" cy="12" r="9"/><path d="M7 12h10"/>',
    eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    package:'<path d="m12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5m-9 5v8M7.5 5.5l9 5"/>'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const quantityValid = value => /^\d+(?:\.\d{1,3})?$/.test(value) && Number(value) > 0 && Number(value) <= 99999;
  const rowById = id => state.rows.find(row => row.id === id);
  const reviewed = () => state.rows.filter(row => row.decision !== null).length;
  const allReviewed = () => state.rows.length === 7 && reviewed() === state.rows.length;
  const productRows = () => state.rows.filter(row => row.decision && row.decision.kind !== 'ignored');
  let toastTimer;

  function announce(message) {
    clearTimeout(toastTimer);
    const toast = document.getElementById('status-message');
    toast.textContent = message;
    toast.classList.add('visible');
    toastTimer = setTimeout(() => toast.classList.remove('visible'), 2300);
  }

  // These seven literal observations are the existing synthetic sample PO.
  // Selection and customer decisions never change its source evidence.
  function sampleRows() {
    return [
      ['7140618','Werner MasterTrade 6 tread stepladder','2','EA','certain','7140618'],
      ['7140818','Werner MasterTrade 8 tread stepladder','1','EA','certain','7140818'],
      ['7160618','Werner fibreglass 6 tread stepladder','3','EA','certain','7160618'],
      ['7050718L','Werner 7 tread workstation - 7050718','2','EA','uncertain',null],
      ['79009','Werner roof rack clamps','1','PK','probable','79009'],
      ['','DELIVERY NOTE: call before arrival','','','uncertain',null],
      ['','Carriage / shipping charge','1','','uncertain',null]
    ].map(([sku,description,quantity,unit,tier,suggestion], index) => ({
      id:`line-${index+1}`, number:index+1, tier, suggestion, decision:null,
      source:Object.freeze({sku,description,quantity,unit})
    }));
  }

  function setStage(stage) {
    if (stage === 'approve' && !allReviewed()) return;
    state.stage = stage;
    render();
    window.scrollTo(0,0);
    view.querySelector('h1')?.focus({preventScroll:true});
  }

  function render() {
    const step = state.stage === 'reading' ? 'upload' : state.stage;
    const order = ['upload','review','approve'];
    order.forEach((name,index) => {
      const el = document.getElementById(`step-${name}`);
      el.classList.toggle('complete', index < order.indexOf(step));
      if (step === name) el.setAttribute('aria-current','step');
      else el.removeAttribute('aria-current');
    });
    if (state.stage === 'upload') renderUpload();
    if (state.stage === 'reading') renderReading();
    if (state.stage === 'review') renderReview();
    if (state.stage === 'approve') renderFinal();
  }

  function renderUpload() {
    view.innerHTML = `<section class="intro"><p class="eyebrow">PURCHASE ORDER IMPORT</p><h1 tabindex="-1">Your order.<br>A little less typing.</h1><p>Add a purchase order, check each line, and approve the products you want.</p></section>
      <div class="upload-layout"><section class="panel upload-panel" aria-labelledby="upload-title"><h2 id="upload-title">Start with a PDF or photo</h2>
      <div id="dropzone" class="dropzone"><div class="upload-symbol">${icon('upload')}</div><h3>Add your purchase order</h3><p>A scan, a PDF, or a clear phone photo.</p><button id="browse-file" class="button primary">${icon('plus')}Choose a file</button><p>PDF, JPG, PNG or WebP · up to 25 MB</p><input id="file-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" hidden></div>
      <p id="upload-error" class="inline-error" role="alert"></p><div class="privacy-note">${icon('shield')}<p>Your file stays in this browser. This demo shows sample results.</p></div>
      <div class="or-divider">Or see how it works</div><button id="sample-order" class="sample-order">${icon('file')}<span><strong>Try the sample purchase order</strong><small>7 sample lines · includes unclear and non-product lines</small></span>${icon('arrow')}</button></section>
      <aside class="panel flow-panel"><h2>Good matches. A human final say.</h2>${[
        ['We read the document','The demo walks through reading, with the existing sample purchase order.'],
        ['You review every line','Clear matches start selected. Unclear lines keep their original image.'],
        ['You approve the full review','Products stay pending until you tap the final approval.']
      ].map(([title,text],i) => `<div class="flow-item"><span class="flow-number">0${i+1}</span><div><strong>${title}</strong><p>${text}</p></div></div>`).join('')}<p class="field-hint">Synthetic sample data · no sign-in required.</p></aside></div>`;
    document.getElementById('browse-file').onclick = () => document.getElementById('file-input').click();
    document.getElementById('file-input').onchange = event => {
      if (event.target.files.length) handleFile(event.target.files[0]);
    };
    document.getElementById('sample-order').onclick = () => beginReading(null);
    const zone = document.getElementById('dropzone');
    zone.ondragover = event => {event.preventDefault(); zone.classList.add('dragging');};
    zone.ondragleave = () => zone.classList.remove('dragging');
    zone.ondrop = event => {
      event.preventDefault(); zone.classList.remove('dragging');
      if (event.dataTransfer.files.length !== 1) showUploadError('Choose one PDF or photo at a time.');
      else handleFile(event.dataTransfer.files[0]);
    };
  }

  function showUploadError(message) {
    const el = document.getElementById('upload-error');
    if (el) el.textContent = message;
  }

  async function handleFile(file) {
    if (!file.size) return showUploadError('This file is empty. Choose another document.');
    if (file.size > 25*1024*1024) return showUploadError('Choose a file smaller than 25 MB.');
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['pdf','jpg','jpeg','png','webp'].includes(ext)) return showUploadError('Choose a PDF, JPG, PNG or WebP file.');
    const token = ++state.readingToken;
    try {
      const bytes = new Uint8Array(await file.slice(0,16).arrayBuffer());
      const text = String.fromCharCode(...bytes);
      const valid = ext === 'pdf' ? text.startsWith('%PDF-') : ext === 'png' ? [137,80,78,71,13,10,26,10].every((b,i) => bytes[i] === b) : ['jpg','jpeg'].includes(ext) ? bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 : text.startsWith('RIFF') && text.slice(8,12) === 'WEBP';
      if (token !== state.readingToken || state.stage !== 'upload') return;
      if (!valid) return showUploadError('The file content does not match its file type. Choose another document.');
      beginReading(file);
    } catch {showUploadError('We could not open this file. Choose another PDF or photo.');}
  }

  function clearFile() {
    if (state.fileUrl) URL.revokeObjectURL(state.fileUrl);
    state.fileUrl = null; state.file = null;
  }

  function beginReading(file) {
    clearFile();
    state.file = file; state.fileUrl = file ? URL.createObjectURL(file) : null;
    state.rows = []; state.drafts = {}; state.accepted = false;
    catalog.splice(0,catalog.length,...window.SAMPLE_CATALOG.map(product => ({...product})));
    const token = ++state.readingToken;
    setStage('reading');
    setTimeout(() => {
      if (token !== state.readingToken || state.stage !== 'reading') return;
      state.rows = sampleRows();
      setStage('review');
      announce('Sample ready. All seven lines need your review.');
    },1800);
  }

  function renderReading() {
    view.innerHTML = `<section class="panel loading-panel"><div class="reading-symbol">${icon('scan')}</div><p class="eyebrow">SAMPLE WALKTHROUGH</p><h1 tabindex="-1">Reading your<br>purchase order.</h1><p>${safe(state.file?.name || 'sample-purchase-order.pdf')}</p><div class="loading-track" aria-hidden="true"><div class="loading-fill"></div></div><p role="status">Finding lines and preparing suggestions…</p><p class="field-hint">Simulated reading. The next screen uses the existing synthetic sample, even when you choose your own file.</p><button id="cancel-reading" class="button secondary">Cancel</button></section>`;
    document.getElementById('cancel-reading').onclick = () => {++state.readingToken; clearFile(); setStage('upload'); announce('Reading cancelled.');};
  }

  function demoNote() {
    return `<div class="notice"><p><strong>Sample PO · DEMO-1042.</strong> All suggestions and source snippets below come from the synthetic sample.</p>${state.file ? `<p>Your selected file, <strong>${safe(state.file.name)}</strong>, is for local preview only.</p><button class="button text" data-action="preview-file">${icon('eye')}Preview selected file</button>` : ''}</div>`;
  }

  function sourceSnippet(row) {
    return `<div class="source-snippet"><div class="snippet-heading"><span>ORIGINAL SAMPLE · PAGE 1 · LINE ${row.number}</span><button class="button text" data-action="preview-line" data-id="${row.id}" aria-label="Enlarge source for line ${row.number}">Enlarge ${icon('eye')}</button></div><button class="snippet-image" data-action="preview-line" data-id="${row.id}" aria-label="Open source image for line ${row.number}"><img src="assets/${row.id}.png" alt="Original synthetic purchase order line ${row.number}: ${safe(row.source.description)}" width="1030" height="116"></button><div class="raw-observation">${row.source.sku ? `Printed code: <strong>${safe(row.source.sku)}</strong><br>` : ''}Printed text: <strong>${safe(row.source.description)}</strong><br>Printed quantity: <strong>${safe(row.source.quantity || 'Not present')}</strong> · Unit: <strong>${safe(row.source.unit || 'Not present')}</strong></div></div>`;
  }

  function sourceDetails(row) {
    return `<details class="source-details"><summary>Compare with the original line</summary>${sourceSnippet(row)}</details>`;
  }

  function card(row) {
    const product = catalog.find(p => p.id === (row.decision?.productId || row.suggestion));
    const decision = row.decision;
    const draft = state.drafts[row.id];
    const tone = decision ? 'certain' : row.tier;
    const status = decision ? 'Reviewed' : {certain:'Pre-selected · pending',probable:'Confirm the suggestion',uncertain:'Your answer needed'}[row.tier];
    let content;
    if (decision) {
      content = `<h3>${safe(decision.name)}</h3><div class="product-meta"><span>Code <code>${safe(decision.productId)}</code></span><span>${safe(decision.quantity)} ${safe(decision.unit)}</span>${decision.kind === 'new' ? '<span>Added to sample catalog</span>' : ''}</div><p class="reviewed-note">${state.accepted ? 'Approved by you with the full review.' : 'Reviewed by you · final approval still required.'}</p><div class="line-actions"><button class="button text" data-action="edit" data-id="${row.id}">Edit decision</button></div>${sourceDetails(row)}`;
    } else if (row.tier === 'certain') {
      content = `<h3>${safe(product.name)}</h3><div class="product-meta"><span>Code <code>${safe(product.id)}</code></span><span>${safe(row.source.quantity)} ${safe(row.source.unit)}</span></div><p class="line-reason">Exact code match. Selected for you to check.</p>${draft ? '<p class="field-hint">Choose and approve your revised product in the form below.</p>' : `<div class="line-actions"><button class="button primary" data-action="approve" data-id="${row.id}">${icon('check')}Approve line</button><button class="button text" data-action="choose-existing" data-id="${row.id}">Change</button></div>`}${sourceDetails(row)}`;
    } else if (row.tier === 'probable') {
      content = `<h3>${safe(product.name)}</h3><div class="product-meta"><span>Suggested code <code>${safe(product.id)}</code></span><span>Printed: ${safe(row.source.quantity)} ${safe(row.source.unit)}</span></div><p class="line-reason">The product looks right. Check that “1 PK” means one pack before confirming.</p>${sourceSnippet(row)}${draft ? '<p class="field-hint">Choose and approve your revised product in the form below.</p>' : `<div class="line-actions"><button class="button primary" data-action="approve" data-id="${row.id}">${icon('check')}Confirm product &amp; unit</button><button class="button text" data-action="choose-existing" data-id="${row.id}">Pick another</button></div>`}`;
    } else {
      const reason = row.id === 'line-4' ? 'The code column says 7050718L, but the description says 7050718. Which product is intended?' : row.id === 'line-6' ? 'This looks like a delivery instruction. You decide whether it is a product.' : 'This looks like a shipping charge. Confirm how this line should be treated.';
      content = `<h3>${safe(row.source.description)}</h3><p class="line-reason">${reason}</p>${sourceSnippet(row)}<p class="question">What is this line?</p><div class="answer-choices" role="group" aria-label="Answers for line ${row.number}"><button class="button secondary ${draft?.mode === 'existing' ? 'chosen' : ''}" data-action="choose-existing" data-id="${row.id}">${icon('search')}<span>This is product X</span>${icon('arrow')}</button><button class="button secondary ${draft?.mode === 'new' ? 'chosen' : ''}" data-action="create-new" data-id="${row.id}">${icon('plus')}<span>New product</span>${icon('arrow')}</button><button class="button secondary" data-action="ignore" data-id="${row.id}">${icon('minus')}<span>Not a product</span>${icon('arrow')}</button></div>`;
    }
    return `<article class="line-card ${row.tier}" data-row="${row.id}" data-reviewed="${Boolean(decision)}"><div class="card-top"><span class="line-label">LINE ${row.number}</span><span class="status-badge ${tone}-tone">${decision ? icon('check') : ''}${status}</span></div>${content}${!decision && draft ? resolutionForm(row,draft) : ''}</article>`;
  }

  function quantityFields(row,draft) {
    return `<div class="quantity-fields"><div class="field"><label for="quantity-${row.id}">Quantity</label><input id="quantity-${row.id}" name="quantity" type="text" inputmode="decimal" value="${safe(draft.quantity)}" maxlength="12" aria-describedby="form-error-${row.id}"></div><div class="field"><label for="unit-${row.id}">Ordering unit</label><select id="unit-${row.id}" name="unit" aria-describedby="form-error-${row.id}"><option value="">Choose unit</option>${units.map(unit => `<option ${draft.unit === unit ? 'selected' : ''} value="${unit}">${unit === 'EA' ? 'EA · each' : unit === 'PK' ? 'PK · pack' : 'BOX · box'}</option>`).join('')}</select></div></div><p class="field-hint">Printed quantity stays ${safe(row.source.quantity || 'not present')}; printed unit stays ${safe(row.source.unit || 'not present')}. Packs are never converted to each.</p>`;
  }

  function resultButtons(row,draft) {
    const query = draft.query.toLowerCase().trim();
    const products = catalog.filter(p => !query || `${p.id} ${p.name}`.toLowerCase().includes(query));
    return products.length ? products.map(product => `<button type="button" class="search-result ${draft.productId === product.id ? 'selected' : ''}" data-product="${safe(product.id)}" data-id="${row.id}" aria-pressed="${draft.productId === product.id}">${icon(draft.productId === product.id ? 'check' : 'package')}<span><strong>${safe(product.name)}</strong><small>Code ${safe(product.id)}</small></span></button>`).join('') : '<p class="field-hint">No sample products found. Try another code or name.</p>';
  }

  function resolutionForm(row,draft) {
    const existing = draft.mode === 'existing';
    const selected = catalog.find(p => p.id === draft.productId);
    return `<form class="resolution-form" data-form="${draft.mode}" data-row="${row.id}" novalidate>${existing ? `<div class="field"><label for="search-${row.id}">Search the sample catalog</label><input id="search-${row.id}" name="query" type="search" value="${safe(draft.query)}" placeholder="Product code or name" maxlength="120" autocomplete="off"></div><div class="search-results">${resultButtons(row,draft)}</div><div class="selected-product">${selected ? `Selected: <strong>${safe(selected.name)}</strong> · ${safe(selected.id)}` : 'Choose a product above. Selection is still pending.'}</div>` : `<p class="answer-subtitle">Add a product to this demo’s sample catalog. It lasts only for this review.</p><div class="field"><label for="productId-${row.id}">New product code</label><input id="productId-${row.id}" name="productId" value="${safe(draft.productId)}" maxlength="60" autocomplete="off"></div><div class="field"><label for="productName-${row.id}">Product name</label><input id="productName-${row.id}" name="productName" value="${safe(draft.productName)}" maxlength="160"></div>`}${quantityFields(row,draft)}<p id="form-error-${row.id}" class="inline-error" role="alert"></p><button type="submit" class="button primary wide">${icon('check')}${existing ? 'Approve line' : 'Add sample product & review line'}</button><p class="field-hint">This tap reviews the line. Final approval comes after every line is reviewed.</p></form>`;
  }

  function ignoredSection(canEdit = true) {
    const rows = state.rows.filter(row => row.decision?.kind === 'ignored');
    return `<details id="ignored-lines" class="ignored-section"><summary>Ignored · ${rows.length} ${rows.length === 1 ? 'line' : 'lines'}</summary>${rows.length ? rows.map(row => `<article class="ignored-item" data-row="${row.id}"><h3>Line ${row.number} · ${safe(row.source.description)}</h3><p>You chose “Not a product”. This source line is preserved.</p>${sourceSnippet(row)}${canEdit ? `<div class="line-actions"><button class="button text" data-action="edit" data-id="${row.id}">Review this line again</button></div>` : ''}</article>`).join('') : '<p>Lines you mark “Not a product” will stay here with their original snippets.</p>'}</details>`;
  }

  function renderReview() {
    const count = reviewed();
    const tiers = [
      ['certain','Certain','Exact code matches. Pre-selected, waiting for your tap.'],
      ['probable','Probable','Check the suggestion, or choose a different product.'],
      ['uncertain','Uncertain','Keep the source in view. Choose one of three answers.']
    ];
    view.innerHTML = `<section class="intro"><p class="eyebrow">REVIEW YOUR PURCHASE ORDER</p><div class="intro-row"><h1 tabindex="-1">A match is a suggestion.<br>You decide.</h1></div><p>Check each line against the source. Nothing is accepted until you approve the full review.</p></section>${demoNote()}
      <div class="tier-guide" aria-label="Three review tiers"><div class="certain-tone"><strong>Certain</strong><small>Pre-selected.<br>Tap to approve.</small></div><div class="probable-tone"><strong>Probable</strong><small>Confirm it.<br>Or pick another.</small></div><div class="uncertain-tone"><strong>Uncertain</strong><small>See the source.<br>Give your answer.</small></div></div>
      <div class="review-progress"><div class="progress-label"><strong id="review-progress">${count} of 7 lines reviewed</strong><span>${state.accepted ? productRows().length : 0} accepted</span></div><div class="progress-track"><progress value="${count}" max="7" aria-label="Reviewed lines"></progress></div><p class="progress-note">Review every line, including anything that isn’t a product.</p></div>
      <div class="review-layout"><div class="review-workspace">${tiers.map(([tier,title,description]) => {const rows = state.rows.filter(row => row.tier === tier && row.decision?.kind !== 'ignored'); return `<section class="tier-section ${tier}" aria-labelledby="tier-${tier}"><div class="tier-heading"><h2 id="tier-${tier}" class="tier-name"><span class="tier-dot"></span>${title}</h2><span class="tier-count">${rows.length} ${rows.length === 1 ? 'line' : 'lines'}</span></div><p class="tier-description">${description}</p>${rows.length ? rows.map(card).join('') : '<p class="field-hint">All lines in this tier were reviewed as non-products. See Ignored below.</p>'}</section>`;}).join('')}${ignoredSection()}<div class="review-footer"><div><p>${allReviewed() ? 'Every line has your decision. One final check.' : 'Your decisions stay pending until the final approval.'}</p><p class="remaining">${allReviewed() ? `${productRows().length} product lines · ${7-productRows().length} ignored` : `${7-count} ${7-count === 1 ? 'line needs' : 'lines need'} your review`}</p></div><button id="review-final" class="button primary" ${allReviewed() ? '' : 'disabled'}>Review final summary ${icon('arrow')}</button></div><div class="restart-row"><button class="button text" data-action="restart">Start a new sample review</button></div></div>
      <aside class="panel source-panel"><h2>Original sample purchase order</h2><p>DEMO-1042 · page 1 of 1<br>Compare any line with the full page.</p><button class="source-page" data-action="preview-document" aria-label="Enlarge original sample purchase order"><img src="assets/sample-page.png" alt="Synthetic sample purchase order DEMO-1042, all seven source lines" width="1191" height="1684"></button><button class="button secondary" data-action="preview-document">${icon('eye')}Open full page</button></aside></div><button id="document-preview" class="button text" data-action="preview-document">${icon('eye')}View original sample document</button>`;
    document.getElementById('review-final').onclick = () => setStage('approve');
  }

  function renderFinal() {
    const products = productRows();
    const totals = products.reduce((acc,row) => {const d=row.decision;acc[d.unit]=(acc[d.unit] || 0)+Math.round(Number(d.quantity)*1000);return acc;},{});
    view.innerHTML = `${state.accepted ? `<section class="panel success-panel"><div class="success-symbol">${icon('check')}</div><p class="eyebrow">SAMPLE REVIEW COMPLETE</p><h1 tabindex="-1">Approved by you.</h1><p>${products.length} product lines approved. The original evidence and ${7-products.length} ignored lines are still available below.</p><p>Demo complete. No order has been placed.</p></section>` : `<section class="intro"><p class="eyebrow">ONE LAST CHECK</p><h1 tabindex="-1">Your review.<br>Ready for your approval.</h1><p>Every line has a decision. Check the products and quantities, then approve all reviewed lines.</p></section>`}${demoNote()}
      <div class="final-layout"><section class="panel"><h2>Reviewed products · ${products.length}</h2><p class="field-hint">${state.accepted ? 'Approved with your final tap.' : 'Pending your final approval.'}</p><div class="final-list">${products.length ? products.map(row => {const d=row.decision;return `<article class="final-item" data-final-row="${row.id}">${icon('check')}<div><h3>${safe(d.name)}</h3><p>Code ${safe(d.productId)} · ${safe(d.quantity)} ${safe(d.unit)}<br>Sample PO · line ${row.number}${d.kind === 'new' ? ' · new sample product' : ''}</p><button class="button text" data-action="edit" data-id="${row.id}">Edit this line</button></div></article>`;}).join('') : '<p class="field-hint">All seven lines were reviewed as non-products. No products will be accepted.</p>'}</div>${ignoredSection()}</section>
      <aside class="panel summary-panel"><h2>Review summary</h2><div class="summary-stat"><span>Lines reviewed by you</span><strong>7 / 7</strong></div><div class="summary-stat"><span>Product lines</span><strong>${products.length}</strong></div><div class="summary-stat"><span>Ignored as non-products</span><strong>${7-products.length}</strong></div><div class="summary-stat"><span>Accepted</span><strong id="accepted-count">${state.accepted ? products.length : 0}</strong></div><div class="unit-totals"><p>Quantity by ordering unit</p>${Object.entries(totals).map(([unit,amount]) => `<strong>${amount/1000} ${safe(unit)}</strong><br>`).join('') || '<strong>No product quantities</strong>'}</div><button id="approve-all" class="button primary wide" ${state.accepted || !allReviewed() ? 'disabled' : ''}>${icon('check')}${state.accepted ? 'All reviewed lines approved' : 'Approve all reviewed lines'}</button><p>${state.accepted ? 'Approval is saved for this sample session only.' : 'Your tap approves these product decisions and preserves the ignored lines.'}</p><p>Sample only · no order is sent.</p></aside></div><button id="back-review" class="button text">Back to review</button>`;
    document.getElementById('back-review').onclick = () => setStage('review');
    document.getElementById('approve-all').onclick = () => {
      if (!allReviewed() || state.accepted) return;
      state.accepted = true; renderFinal();
      window.scrollTo(0,0); view.querySelector('h1')?.focus({preventScroll:true});
      announce('All reviewed sample lines approved.');
    };
  }

  function updateRow(row,message) {
    state.accepted = false;
    const y = window.scrollY;
    if (state.stage !== 'review') setStage('review');
    else renderReview();
    window.scrollTo(0,y);
    const reviewedControl = view.querySelector(`[data-row="${row.id}"] [data-action="edit"]`);
    reviewedControl?.focus({preventScroll:true});
    reviewedControl?.scrollIntoView({block:'nearest'});
    announce(message);
  }

  function openDraft(row,mode) {
    if (row.decision) return;
    const old = state.drafts[row.id];
    state.drafts[row.id] = {
      mode, query:old?.mode === mode ? old.query : '',
      productId:old?.mode === mode ? old.productId : '',
      productName:old?.productName || row.source.description,
      quantity:old?.quantity ?? row.source.quantity,
      unit:old?.unit ?? row.source.unit
    };
    const y = window.scrollY;
    renderReview(); window.scrollTo(0,y);
    const input = document.getElementById(`${mode === 'existing' ? 'search' : 'productId'}-${row.id}`);
    input?.focus({preventScroll:true});
    input?.scrollIntoView({block:'center'});
  }

  function approveSuggestion(row) {
    if (row.decision || state.drafts[row.id]) return;
    const p = catalog.find(product => product.id === row.suggestion);
    if (!p || !quantityValid(row.source.quantity) || !units.includes(row.source.unit)) return;
    row.decision = {kind:'existing',productId:p.id,name:p.name,quantity:row.source.quantity,unit:row.source.unit};
    updateRow(row,`Line ${row.number} reviewed. Final approval still required.`);
  }

  function showPreview(kind,row) {
    const content = document.getElementById('preview-content');
    const title = document.getElementById('preview-title');
    if (kind === 'file' && state.file) {
      title.textContent = 'Your selected file · local preview only';
      const pdf = state.file.name.toLowerCase().endsWith('.pdf');
      content.innerHTML = `<p class="preview-note">This selected file is never read by the demo. Review results use the original synthetic sample.</p>${pdf ? `<a class="preview-download" href="${safe(state.fileUrl)}" target="_blank" rel="noopener noreferrer">Open selected PDF in a local browser tab</a>` : `<img src="${safe(state.fileUrl)}" alt="Your selected photo, preview only">`}`;
    } else {
      title.textContent = row ? `Original sample · line ${row.number}` : 'Original sample purchase order';
      content.innerHTML = `<p class="preview-note">Synthetic sample · DEMO-1042 · page 1. Source evidence stays unchanged.</p><img src="assets/${row ? row.id : 'sample-page'}.png" alt="${row ? `Original sample line ${row.number}: ${safe(row.source.description)}` : 'Full synthetic sample purchase order'}">${!row ? '<a class="preview-download" href="assets/sample-purchase-order.pdf" target="_blank" rel="noopener noreferrer">Open the sample PDF</a>' : ''}`;
    }
    document.getElementById('preview-dialog').showModal();
  }

  view.addEventListener('click',event => {
    const productButton = event.target.closest('[data-product]');
    if (productButton) {
      const row = rowById(productButton.dataset.id);
      const draft = state.drafts[row.id];
      if (!draft || draft.mode !== 'existing' || row.decision) return;
      draft.productId = productButton.dataset.product;
      const form = productButton.closest('form');
      form.querySelector('.search-results').innerHTML = resultButtons(row,draft);
      const p = catalog.find(product => product.id === draft.productId);
      form.querySelector('.selected-product').innerHTML = `Selected: <strong>${safe(p.name)}</strong> · ${safe(p.id)}`;
      form.querySelector(`[data-product="${CSS.escape(p.id)}"]`)?.focus({preventScroll:true});
      return;
    }
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const row = rowById(button.dataset.id);
    switch (button.dataset.action) {
      case 'approve': approveSuggestion(row); break;
      case 'choose-existing': openDraft(row,'existing'); break;
      case 'create-new': openDraft(row,'new'); break;
      case 'ignore':
        if (!row.decision) {
          row.decision={kind:'ignored'}; delete state.drafts[row.id];updateRow(row,`Line ${row.number} preserved in Ignored.`);
          const summary = document.getElementById('ignored-lines').querySelector('summary');
          summary.focus({preventScroll:true});summary.scrollIntoView({block:'nearest'});
        }
        break;
      case 'edit': {
        row.decision=null; delete state.drafts[row.id]; state.accepted=false; setStage('review');
        const article=view.querySelector(`[data-row="${row.id}"]`);
        article.scrollIntoView({block:'start'});article.querySelector('button')?.focus({preventScroll:true});announce(`Line ${row.number} is pending again.`);break;
      }
      case 'preview-line': showPreview('sample',row); break;
      case 'preview-document': showPreview('sample'); break;
      case 'preview-file': showPreview('file'); break;
      case 'restart': ++state.readingToken; clearFile(); state.rows=[]; state.drafts={}; state.accepted=false; setStage('upload'); break;
    }
  });

  view.addEventListener('input',event => {
    const form = event.target.closest('form[data-row]');
    if (!form) return;
    const row = rowById(form.dataset.row);
    const draft = state.drafts[row.id];
    if (!draft || row.decision) return;
    const input = event.target;
    draft[input.name] = input.value;
    if (input.name === 'query') form.querySelector('.search-results').innerHTML = resultButtons(row,draft);
    if (input.name === 'quantity') {
      input.setAttribute('aria-invalid',String(!quantityValid(input.value.trim())));
      form.querySelector('.inline-error').textContent = quantityValid(input.value.trim()) ? '' : 'Enter a positive quantity up to 99,999, with at most 3 decimal places.';
    }
  });
  view.addEventListener('change',event => {
    const form = event.target.closest('form[data-row]');
    if (form && event.target.name === 'unit') state.drafts[form.dataset.row].unit = event.target.value;
  });

  view.addEventListener('submit',event => {
    const form = event.target.closest('form[data-row]');
    if (!form) return;
    event.preventDefault();
    const row = rowById(form.dataset.row);
    const draft = state.drafts[row.id];
    if (!draft || row.decision) return;
    const values = new FormData(form);
    const quantity = String(values.get('quantity')).trim();
    const unit = String(values.get('unit'));
    let error = '';
    const quantityInput = form.elements.quantity;
    quantityInput.setAttribute('aria-invalid',String(!quantityValid(quantity)));
    form.elements.unit.setAttribute('aria-invalid',String(!units.includes(unit)));
    if (!quantityValid(quantity)) error = 'Enter a positive quantity up to 99,999, with at most 3 decimal places.';
    else if (!units.includes(unit)) error = 'Choose the ordering unit printed on the line, or confirm it manually.';
    let product;
    if (draft.mode === 'existing') {
      product = catalog.find(p => p.id === draft.productId);
      if (!error && !product) error = 'Choose a product from the sample catalog first.';
    } else {
      const id = String(values.get('productId')).trim();
      const name = String(values.get('productName')).trim();
      if (!error && (!id || !name)) error = 'Enter a new product code and name.';
      if (!error && catalog.some(p => p.id.toLowerCase() === id.toLowerCase())) error = 'This code is already in the sample catalog. Choose “This is product X” to find it.';
      if (!error) product = {id,name};
    }
    if (error) {form.querySelector('.inline-error').textContent=error;return;}
    if (draft.mode === 'new') catalog.push(product);
    row.decision={kind:draft.mode,productId:product.id,name:product.name,quantity,unit};
    delete state.drafts[row.id];
    updateRow(row,`Line ${row.number} reviewed${draft.mode === 'new' ? '; product added to the sample catalog' : ''}.`);
  });

  document.getElementById('close-preview').onclick = () => document.getElementById('preview-dialog').close();
  render();
})();
