"""Create a portable, local page-by-page review UI for a private VLM dataset.

The HTML only downloads human-entered review records. It never writes labels,
contacts a model service, or changes a dataset's approval status on its own.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from po_reader.model_provider import PAGE_EXTRACTION_SCHEMA
from po_reader.vlm_dataset import validate_dataset


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_review(dataset_dir, output):
    dataset_dir, output = Path(dataset_dir), Path(output)
    validate_dataset(dataset_dir)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    pages = []
    for document in manifest["documents"]:
        for page in document["pages"]:
            candidate = (json.loads((dataset_dir / page["candidate_path"]).read_text(encoding="utf-8"))
                         if page.get("candidate_path") else {"target": None})
            image = (dataset_dir / page["image_path"]).read_bytes()
            if hashlib.sha256(image).hexdigest() != page["image_sha256"]:
                raise ValueError("Review image hash does not match source inventory")
            if digest(candidate["target"]) != page["candidate_sha256"]:
                raise ValueError("Review candidate hash does not match the built dataset")
            pages.append(dict(**page, id=document["document_id"] + f"P{page['page']:02d}",
                              archive_entry=document["aliases"][0]["archive_entry"],
                              target=candidate["target"], annotation_sha256=page["candidate_sha256"],
                              annotation_notes=candidate.get("notes", []),
                              image_data="data:image/png;base64," + base64.b64encode(image).decode()))
    payload = json.dumps(dict(archive_sha256=manifest["archive"]["sha256"], pages=pages,
                             schema=PAGE_EXTRACTION_SCHEMA), ensure_ascii=False).replace("<", "\\u003c")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__PAYLOAD__", payload), encoding="utf-8")
    return dict(path=str(output.resolve()), pages=len(pages), size_bytes=output.stat().st_size)


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PO dataset review</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f7;color:#182734;font:14px system-ui,sans-serif}
header{background:#142c3c;color:white;padding:20px 26px;display:flex;align-items:center;gap:24px;flex-wrap:wrap}
h1{font-size:23px;margin:0 0 4px}header p{margin:0;color:#ccdae3}.stats{margin-left:auto;font-size:14px}
.bar{padding:14px 26px;background:white;border-bottom:1px solid #d7e0e5;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button,input,select{font:inherit}button{border:1px solid #c9d5dd;border-radius:7px;background:white;padding:9px 13px;cursor:pointer}
button.primary{background:#116860;border-color:#116860;color:white}button:disabled{opacity:.4;cursor:default}
input[type=text],select{padding:9px;border:1px solid #c9d5dd;border-radius:7px}#reviewer{width:190px}
main{display:grid;grid-template-columns:minmax(380px,1.1fr) minmax(390px,1fr);gap:16px;padding:16px 26px}
.card{background:white;border:1px solid #d8e1e6;border-radius:9px;overflow:hidden}.card h2{font-size:16px;margin:0;padding:15px;border-bottom:1px solid #e0e7eb}
.source{height:calc(100vh - 230px);overflow:auto;background:#e8edef;padding:14px;text-align:center}.source img{max-width:100%;display:block;margin:auto;box-shadow:0 2px 8px #152a3a20}
.source.zoom img{max-width:none;width:155%;margin:0}.meta{padding:12px 15px;color:#4d6676;font-size:12px;word-break:break-word}
.right{display:flex;flex-direction:column}.summary{padding:13px 15px;line-height:1.6;border-bottom:1px solid #e2e8ec}
.badge{display:inline-block;background:#fff0c7;color:#735000;border-radius:4px;padding:2px 6px;margin-right:6px}
#editor{width:100%;min-height:350px;height:calc(100vh - 510px);resize:vertical;border:0;background:#fbfcfd;padding:15px;font:12px/1.5 ui-monospace,monospace;tab-size:2}
.review{padding:15px;border-top:1px solid #e1e7eb}.review label{display:flex;gap:9px;align-items:flex-start;line-height:1.5}.review input{margin-top:4px}
#notes{width:100%;margin-top:10px}.actions{display:flex;gap:8px;margin-top:11px}.help{font-size:12px;color:#5b7180;margin-top:10px;line-height:1.5}
#message{min-height:22px;padding:0 26px 15px;color:#9d3d1d}.ok{color:#116860!important}
@media(max-width:900px){main{grid-template-columns:1fr;padding:12px}.source{height:65vh}#editor{height:400px}header,.bar{padding:15px}}
</style></head><body>
<header><div><h1>PO dataset review</h1><p>Compare the source page with its candidate extraction. Correct every field before approving.</p></div><div class="stats" id="stats"></div></header>
<div class="bar"><button id="prev">Previous</button><select id="pageSelect" aria-label="Source page"></select><button id="next">Next</button><button id="zoom">Zoom source</button>
<input type="text" id="reviewer" placeholder="Human reviewer name" aria-label="Human reviewer name"><button id="download">Download reviews</button><button id="saveDraft">Download progress backup</button>
<label>Restore backup <input id="restore" type="file" accept="application/json,.json"></label>
<label><input type="checkbox" id="release"> Release completed reviewed documents for future training</label></div>
<main><section class="card"><h2 id="sourceTitle"></h2><div class="source" id="imagePane"><img id="sourceImage" alt="Original rendered PDF page"></div><div class="meta" id="meta"></div></section>
<section class="card right"><h2>Candidate JSON</h2><div class="summary" id="summary"></div><textarea id="editor" spellcheck="false" aria-label="Corrected extraction JSON"></textarea>
<div class="review"><label><input type="checkbox" id="checked">I visually checked this source page and every target field, including all rows, quantities, identifiers and address roles.</label>
<input type="text" id="notes" placeholder="Review notes or corrections" aria-label="Review notes"><div class="actions"><button class="primary" id="approve">Save human review</button><button id="exclude">Exclude page</button><button id="clear">Remove page review</button></div>
<div class="help">Approval records stay in this browser until downloaded. Editing a reviewed target removes its approval. Missing or ambiguous printed values should remain null or uncertain. Native text is retained separately in the dataset.</div></div></section></main><div id="message" role="status" aria-live="polite"></div>
<script id="dataset" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('dataset').textContent),$=id=>document.getElementById(id),key='po-review-'+data.archive_sha256;
let index=0,progress={};try{progress=JSON.parse(localStorage.getItem(key)||'{}')}catch{}
function persist(){try{localStorage.setItem(key,JSON.stringify(progress))}catch{message('Browser storage is full. Download a progress backup before closing.')}}
function message(text,ok=false){$('message').textContent=text;$('message').className=ok?'ok':''}
function validate(v,s,path='target'){
 const type=v===null?'null':Array.isArray(v)?'array':typeof v==='object'?'object':typeof v;
 if(!(Array.isArray(s.type)?s.type:[s.type]).includes(type))throw Error(path+': expected '+s.type);
 if(s.enum&&!s.enum.includes(v))throw Error(path+': invalid value');
 if(type==='object'){if(Object.keys(v).sort().join('|')!==Object.keys(s.properties).sort().join('|'))throw Error(path+': missing or extra fields');for(const k in s.properties)validate(v[k],s.properties[k],path+'.'+k)}
 if(type==='array'){if(v.length>1000)throw Error(path+': too many items');v.forEach((a,i)=>validate(a,s.items,path+'['+i+']'))}
 if(type==='string'&&v.length>100000)throw Error(path+': text too long');return v;
}
function state(){return progress[data.pages[index].page_id]||{}}
function storeEdit(){const p=data.pages[index],s=state();const text=$('editor').value;if(s.text!==text){progress[p.page_id]={...s,text,review:null};persist();} }
function redraw(){
 const p=data.pages[index],s=state();$('sourceTitle').textContent=p.id+' · PDF page '+p.page;$('sourceImage').src=p.image_data;$('imagePane').scrollTop=0;
 $('editor').value=s.text||JSON.stringify(p.target,null,2);$('notes').value=s.notes||'';$('checked').checked=false;$('pageSelect').value=String(index);
 $('meta').textContent=p.archive_entry+' | SHA-256 '+p.source_sha256;
 const t=p.target||{},unc=(t.lines||[]).filter(r=>(r.uncertainties||[]).length||r.identifiers.some(a=>a.status==='uncertain')).length;
 $('summary').replaceChildren();const badge=document.createElement('span');badge.className='badge';badge.textContent=s.review?'Human review saved':'Pending human review';$('summary').append(badge,document.createTextNode((t.document_type||'unresolved')+' · '+(t.lines||[]).length+' rows · '+unc+' rows with recorded uncertainty · '+(p.layout_family||'Unassigned layout')));
 for(const n of p.annotation_notes||[]){const el=document.createElement('div');el.textContent=n;$('summary').append(el)}
 $('prev').disabled=index===0;$('next').disabled=index===data.pages.length-1;updateStats();message('');
}
function updateStats(){const count=Object.values(progress).filter(v=>v.review).length;$('stats').textContent=data.pages.length+' pages · '+count+' reviewed';for(let i=0;i<data.pages.length;i++)$('pageSelect').options[i].textContent=data.pages[i].id+(progress[data.pages[i].page_id]?.review?' ✓':'')}
function download(name,value){const blob=new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
data.pages.forEach((p,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=p.id;$('pageSelect').append(o)});
$('prev').onclick=()=>{storeEdit();if(index>0)index--;redraw()};$('next').onclick=()=>{storeEdit();if(index<data.pages.length-1)index++;redraw()};$('pageSelect').onchange=()=>{storeEdit();index=Number($('pageSelect').value);redraw()};
$('zoom').onclick=()=>$('imagePane').classList.toggle('zoom');$('editor').oninput=()=>{storeEdit();$('checked').checked=false;updateStats()};
function saveReview(exclude=false){try{const name=$('reviewer').value.trim();if(!name)throw Error('Enter the name of the human who reviewed this page.');if(!$('checked').checked)throw Error('Check the page review declaration after inspecting every field.');const p=data.pages[index],target=exclude?null:validate(JSON.parse($('editor').value),data.schema);progress[p.page_id]={text:$('editor').value,notes:$('notes').value,review:{page_id:p.page_id,reviewer:name,reviewed_utc:new Date().toISOString(),page:p.page,source_page_sha256:p.source_page_sha256,source_page_hash_method:p.source_page_hash_method,image_sha256:p.image_sha256,candidate_sha256:p.annotation_sha256,decision:exclude?'exclude':JSON.stringify(target)===JSON.stringify(p.target)?'approve':'correct',approved_target:target,notes:[$('notes').value].filter(Boolean)}};persist();updateStats();message('Human review saved for '+p.id+'. Download reviews to import it into the dataset.',true)}catch(e){message(e.message)}}
$('approve').onclick=()=>saveReview(false);$('exclude').onclick=()=>saveReview(true);
$('clear').onclick=()=>{const p=data.pages[index];progress[p.page_id]={...state(),review:null};persist();redraw()};
$('download').onclick=()=>{if(!$('release').checked)return message('Select the release declaration to export complete reviewed documents. Use progress backup to save work without releasing labels.');const groups={};for(const p of data.pages)(groups[p.source_sha256]||=[]).push(p);const reviews=[];let partial=0;for(const [sha,pages]of Object.entries(groups)){const decisions=pages.map(p=>progress[p.page_id]?.review);if(decisions.some(r=>!r)){if(decisions.some(Boolean))partial++;continue}const reviewers=new Set(decisions.map(r=>r.reviewer));if(reviewers.size!==1)return message('All pages of a document must be reviewed by the same named reviewer before release.');reviews.push({schema_version:1,document_sha256:sha,reviewer:decisions[0].reviewer,reviewed_utc:decisions.map(r=>r.reviewed_utc).sort().at(-1),release_for_training:true,source_document_review_complete:true,pages:decisions.map(({page_id,reviewer,reviewed_utc,...page})=>page)})}if(!reviews.length)return message('No complete document has been reviewed yet. Review all pages of at least one PDF.');download('vlm-human-reviews.json',{schema_version:1,archive_sha256:data.archive_sha256,reviews});message('Downloaded '+reviews.length+' complete document reviews. '+partial+' partially reviewed documents remain in progress.',true)};
$('saveDraft').onclick=()=>download('vlm-review-progress.json',{schema_version:1,archive_sha256:data.archive_sha256,progress,reviewer:$('reviewer').value});
$('restore').onchange=async()=>{try{const f=$('restore').files[0];if(!f)return;const b=JSON.parse(await f.text());if(b.archive_sha256!==data.archive_sha256||!b.progress)throw Error('Backup belongs to another dataset.');const ids=new Set(data.pages.map(p=>p.page_id));for(const id in b.progress)if(!ids.has(id))throw Error('Backup has an unknown page.');progress=b.progress;$('reviewer').value=b.reviewer||'';persist();redraw();message('Progress backup restored.',true)}catch(e){message(e.message)}};
redraw();
</script></body></html>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=Path("output/vlm-dataset"))
    parser.add_argument("--output", type=Path, default=Path("output/vlm-dataset/review.html"))
    args = parser.parse_args()
    print(json.dumps(build_review(args.dataset_dir, args.output), indent=2))
