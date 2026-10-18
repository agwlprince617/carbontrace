import {requestLocal as api} from "./api-client.mjs";
const get=id=>document.getElementById(id);
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const state={examples:[],workloads:{},run:null,timer:null,deadline:0,sequence:0};
const money=value=>value===null||value===undefined ? "unavailable" : "$"+Number(value).toFixed(7).replace(/0+$/,"").replace(/\.$/,"")+" USD";
const number=value=>Number(value).toPrecision(7).replace(/0+$/,"").replace(/\.$/,"");
let onError=()=>{};

function quoteQuality(q) {
  const task=q.schema_version===2 ? q.quality_task : q.draft.quality_task;
  return task ? "Quality check: correct implementation + four seeded faults." : "Custom request · quality is not independently evaluated.";
}

export async function loadLive() {
  if(state.examples.length) return;
  const [tasks,catalog]=await Promise.all([api("/api/tasks"),api("/api/research/catalog")]);
  state.examples=tasks;
  state.workloads=catalog.workloads;
  get("live-workload").innerHTML='<option value="">Choose a reference workload…</option>'+Object.keys(state.workloads).sort().map(w=>'<option value="'+escape(w)+'">'+escape(w.replace("."," · "))+'</option>').join("");
}

export async function showPrepared(view) {
  await loadLive();
  if(view.quote.schema_version!==2) throw new Error("Expected a selected-model quote.");
  state.sequence+=1; render(view); state.deadline=Date.now()+600000; schedule();
}

export async function showExistingOrRecorded() {
  if(state.run) render(state.run);
  else await openPrepared("recorded");
}

export async function openPrepared(id) {
  if(id!=="recorded" && !/^[a-f0-9]{32}$/.test(id)) throw new Error("Invalid comparison ID.");
  await loadLive();
  const view=await api(id==="recorded" ? "/api/demo-comparison" : "/api/live-comparisons/"+id);
  if(view.quote.schema_version===2) { await showPrepared(view); return; }
  const d=view.quote.draft;
  get("live-example").value=d.quality_task||"";
  get("live-instruction").value=d.instruction;
  get("live-source").value=d.source_code;
  get("live-context").value=d.context;
  get("live-workload").value=d.workload;
  get("live-grid").value=d.grid_g_per_kwh;
  get("live-save-consent").checked=false;
  state.sequence+=1; render(view); state.deadline=Date.now()+600000; schedule();
}

function stopFollowing() { clearTimeout(state.timer); state.timer=null; }
function invalidate() {
  stopFollowing(); state.sequence+=1; state.run=null;
  get("live-plan").hidden=true;
  get("live-status").textContent="Draft changed. Prepare a new exact quote; existing runs keep their original request.";
}

function render(view) {
  state.run=view;
  const q=view.quote, r=view.result;
  const single=q.schema_version===2;
  get("live-plan-title").textContent=single ? "Review the selected-model run" : "Review the frozen comparison";
  if(view.read_only) get("live-plan-title").textContent="Recorded Gemini comparison";
  document.querySelector(".runner-details").hidden=Boolean(view.read_only);
  get("live-model-list").textContent=(r?.status==="completed" ? "Models used: " : single ? "Selected model: " : "Models planned: ")+q.models.map(m=>m.model_name).join(" / ");
  get("live-precall-note").hidden=!single;
  if(single) get("live-precall-note").textContent="Pre-call choice: "+q.precall_decision.headline;
  get("live-form").hidden=true;
  get("live-new-pair").hidden=document.body.dataset.deploymentMode!=="local";
  get("live-intro").hidden=true;
  if(single) { get("page-label").textContent="Selected model run"; get("hero").querySelector("h1").innerHTML="One chosen model.<br><span>Approve before execution.</span>"; get("hero").querySelector("p").textContent="Review the quote, then approve execution in the local runner."; }
  get("live-plan").hidden=false;
  get("live-run-state").textContent=view.status.replaceAll("_"," ").toUpperCase();
  get("live-status").textContent="Saved run · "+view.status.replaceAll("_"," ")+" · no new model calls.";
  get("live-cost-summary").hidden=r?.status==="completed";
  document.querySelector(".live-entry-actions").hidden=Boolean(view.read_only);
  get("live-follow").parentElement.hidden=["completed","stopped"].includes(view.status);
  get("live-refresh").hidden=Boolean(view.read_only);
  get("live-cost-summary").textContent=q.generation_calls+(q.generation_calls===1 ? " generation" : " generations")+": conservative estimate "+money(q.estimated_cost_usd)+"; stress estimate "+money(q.stress_cost_usd)+"; proposed allowance "+money(q.allowance_usd)+". Estimates before tax/FX; allowance is not a billing cap.";
  get("live-limits").textContent="Project "+q.project+" · global Standard PayGo · "+q.thinking_level+" thinking · at most 4096 input tokens and a requested 4096 generated-token cap per response. "+q.token_count_calls+(q.token_count_calls===1 ? " token count, " : " token counts, ")+q.metadata_reads+(q.metadata_reads===1 ? " metadata read" : " metadata reads")+", zero retries, no tools, no automatic continuation or deployment.";
  if(single) get("live-limits").textContent+=" The advisor used "+q.draft.generated_low+"–"+q.draft.generated_high+" assumed output tokens for its forecasts; this execution quote reserves the larger 4096-token requested cap.";
  get("live-quality-note").textContent=quoteQuality(q);
  get("live-frozen-payload").textContent=q.exact_payload;
  get("live-plan-hash").textContent="Plan SHA256: "+q.plan_sha256+"\nPrompt SHA256: "+q.prompt_sha256+"\nExpires: "+q.expires_at;
  get("live-run-command").textContent="Run ID: "+q.id;
  get("live-slot-note").textContent=(view.remaining_demo_runs??0)+" of 3 local demo run slots remain. A dispatched or interrupted run cannot be replayed.";
  get("live-reopen").href="/?live="+(view.read_only ? "recorded" : q.id);
  get("live-export").href=view.read_only ? "/api/demo-comparison/export" : "/api/live-comparisons/"+q.id+"/export";
  const operations=r?.operations||[];
  get("live-operations").innerHTML=operations.map(op=>"<li>"+escape(op.kind)+" · "+escape(op.model_id)+" · "+escape(op.status)+(op.input_tokens!==undefined ? " · "+escape(op.input_tokens)+" input tokens" : "")+"</li>").join("");
  get("live-result-summary").textContent=r ? "Recorded usage cost: "+money(r.known_catalog_cost_usd)+(r.billing_uncertain ? ". Billing is uncertain for a dispatched generation; this is not a complete total." : ". Before credits/tax/FX; not an invoice.")+(r.stop_reason ? " Stop reason: "+r.stop_reason : "") : "No response yet. Execution requires local approval.";
  const responses=r?.responses||[];
  get("live-responses").innerHTML=responses.map((row,index)=>'<article class="workflow-response"><span class="micro-pill">ACTUAL RUNNER RESPONSE</span><h3>'+escape(row.model_name)+'</h3><p>Provider input / candidate / thinking tokens: '+escape(row.usage.input_tokens??"unknown")+" / "+escape(row.usage.candidate_tokens??"unknown")+" / "+escape(row.usage.thinking_tokens??"omitted")+'</p><p>Response time: '+escape(row.elapsed_seconds.toFixed(2))+' s · recorded-usage cost: '+escape(money(row.catalog_cost_usd))+'</p><p class="live-quality" id="live-quality-'+index+'"></p><details><summary>Inspect returned Python as text</summary><pre id="live-output-'+index+'" class="workflow-code"></pre></details><details><summary>Quality details and provenance</summary><pre id="live-detail-'+index+'" class="workflow-code"></pre></details></article>').join("");
  responses.forEach((row,index)=>{
    get("live-output-"+index).textContent=row.source_text;
    get("live-detail-"+index).textContent=JSON.stringify({model_version:row.model_version,finish_reason:row.finish_reason,quality:row.quality,usage:row.usage,effective_usage:row.effective_usage,suite_sha256:row.suite_sha256},null,2);
    const quality=row.quality;
    get("live-quality-"+index).textContent=quality.status==="not_evaluated" ? "Quality not evaluated: custom code has no independent oracle. Returned Python was not executed." : quality.status==="evaluated" ? (quality.accepted ? "Quality gate passed" : "Quality gate failed")+" · reference "+quality.reference.status+" · "+quality.detected+"/"+quality.total_mutations+" seeded faults detected." : "Quality "+quality.status+(quality.reason ? ": "+quality.reason : "");
  });
  get("live-choice").textContent=single ? (r?.status==="completed" ? "Completed only the selected model. Its result does not establish a comparison with an uncalled model." : "Only the selected model is included.") : r?.recommended_model ? "Suggested for this checked task: "+r.recommended_model+". Both passed the quality gate; this model has the lower CLEER reference energy. Request-carbon savings are unmeasured." : "No model recommendation without completed, independently evaluated quality evidence.";
  const research=q.research;
  if(!research) { get("live-research-note").textContent="No CLEER reference workload was selected; no benchmark was inferred from your draft."; get("live-research-models").replaceChildren(); get("live-research-source").textContent="Actual request energy and carbon are unmeasured."; ["live-research-report","live-research-data","live-research-license"].forEach(id=>{get(id).removeAttribute("href");get(id).hidden=true;}); return; }
  ["live-research-report","live-research-data","live-research-license"].forEach(id=>get(id).hidden=false);
  get("live-research-note").textContent=research.request.workload+" · "+research.request.grid_g_per_kwh+" gCO₂e/kWh assumed · one benchmark session per model.";
  get("live-research-models").innerHTML=research.models.map(model=>'<article class="workflow-response"><span class="micro-pill">PUBLISHED ESTIMATE · SEPARATE FROM THIS RUN</span><h3>'+escape(model.model_name)+'</h3><p>Facility energy: '+escape(number(model.total_energy_wh))+' Wh/session<br>Published per-session SD: '+escape(number(model.evidence.energy_wh_sd))+' Wh<br>Operational carbon under your electricity assumption: '+escape(number(model.operational_carbon_g))+' gCO₂e/session</p></article>').join("");
  get("live-research-source").textContent=research.source.publisher+" · dataset "+research.source.dataset_generated_at+" · "+research.source.dataset_engine+" · related report "+research.source.related_report_version+" · "+research.source.license+". "+research.source.modifications;
  get("live-research-report").href=research.source.report_url;
  get("live-research-data").href=research.source.source_url;
  get("live-research-license").href=research.source.license_url;
}

async function refresh() {
  if(!state.run) return;
  const id=state.run.quote.id, sequence=state.sequence;
  const view=await api(state.run.read_only ? "/api/demo-comparison" : "/api/live-comparisons/"+id);
  if(sequence!==state.sequence || state.run?.quote.id!==id) return;
  render(view);
  schedule();
}
function schedule() {
  stopFollowing();
  if(!state.run || state.run.read_only || !get("live-follow").checked || Date.now()>state.deadline || ["completed","stopped"].includes(state.run.status)) return;
  state.timer=setTimeout(async()=>{
    if(get("live-view").hidden || document.hidden) { schedule(); return; }
    try { await refresh(); } catch(error) { stopFollowing(); onError(error); }
  },2000);
}

export function importDraft(prompt,context,workload,grid) {
  get("live-form").hidden=false;
  get("live-intro").hidden=false;
  invalidate();
  get("live-example").value="";
  get("live-source").value=prompt;
  get("live-context").value=context;
  get("live-instruction").value="Generate pytest tests following the request and source text below. Return Python code only.";
  if(workload) get("live-workload").value=workload;
  get("live-grid").value=grid;
  get("live-save-consent").checked=false;
}

export function wireLive(error,clear) {
  onError=error;
  get("live-new-pair").addEventListener("click",()=>{invalidate();get("live-form").hidden=false;get("live-intro").hidden=false;get("page-label").textContent="Paired validation experiment";get("hero").querySelector("h1").innerHTML="Optional validation.<br><span>Compare two models.</span>";});
  get("live-example").addEventListener("change",()=>{
    const task=state.examples.find(t=>t.id===get("live-example").value);
    if(task) { get("live-source").value=task.source; get("live-context").value=""; }
    invalidate();
  });
  get("live-source").addEventListener("input",()=>{
    const task=state.examples.find(t=>t.id===get("live-example").value);
    if(task && task.source!==get("live-source").value) get("live-example").value="";
  });
  ["live-instruction","live-source","live-context","live-workload","live-grid"].forEach(id=>get(id).addEventListener("input",invalidate));
  get("live-workload").addEventListener("change",()=>{get("live-workload-note").textContent=(state.workloads[get("live-workload").value]||"Choose a reference workload.")+" This does not classify the request or measure its emissions.";});
  get("live-form").addEventListener("submit",async event=>{
    event.preventDefault(); clear();
    const sequence=++state.sequence;
    get("live-prepare").disabled=true;
    stopFollowing();
    try {
      const view=await api("/api/live-comparisons/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({instruction:get("live-instruction").value,source_code:get("live-source").value,context:get("live-context").value,quality_task:get("live-example").value||null,workload:get("live-workload").value,grid_g_per_kwh:Number(get("live-grid").value)})});
      if(sequence!==state.sequence) return;
      render(view); state.deadline=Date.now()+600000; schedule();
    } catch(error) { if(sequence===state.sequence) onError(error); }
    finally { get("live-prepare").disabled=false; }
  });
  get("live-refresh").addEventListener("click",async()=>{clear();state.deadline=Date.now()+600000;try{await refresh();}catch(error){onError(error);}});
  get("live-follow").addEventListener("change",()=>{state.deadline=Date.now()+600000;schedule();});
}
