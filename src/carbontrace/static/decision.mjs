import {requestLocal} from "./api-client.mjs";
import {renderWorkflow} from "./workflow.mjs";

const get = id => document.getElementById(id);
const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const number = value => Number(value).toLocaleString("en-US",{maximumSignificantDigits:6});
const money = value => Number(value).toLocaleString("en-US",{minimumFractionDigits:5,maximumFractionDigits:7});
const state = {result:null,sequence:0,loaded:false,error:null,clearError:null};

function invalidate() {
  state.sequence += 1;
  state.result = null;
  get("decision-results").hidden = true;
  get("decision-export").disabled = true;
  get("decision-calculate").disabled = false;
  get("decision-status").textContent = "Settings changed · review to update the decision evidence.";
}

function render(result) {
  state.result=result;
  renderWorkflow(result,()=>state.result===result,state.error);
  const pending=result.status === "awaiting_pair";
  get("decision-conclusion").innerHTML=`<span class="eyebrow">${pending ? "PAIRED DECISION PENDING" : result.recommended_model ? "TASK-SCOPED CANDIDATE" : "NO PASSING CANDIDATE"}</span><h2>${escape(result.task_title)}</h2><p>${escape(result.explanation)}</p><p>Known comparison-response cost: $${money(result.known_comparison_cost_usd)} USD${pending ? " · incomplete pair" : " · includes both model responses"}. This is separate from the cost of choosing one model.</p>`;
  get("decision-requirements").textContent=result.requirements;
  get("decision-source").textContent=result.source;
  get("decision-models").innerHTML=result.models.map((model,index)=>{
    const evidence=model.evidence;
    const reference=result.reference.models[index];
    const record=reference.evidence;
    const checks=evidence ? `<dl><dt>Reference implementation</dt><dd>${evidence.reference.status === "passed" && evidence.reference.failures === 0 && evidence.reference.errors === 0 && evidence.reference.skipped === 0 ? "Passed" : "Did not pass cleanly"} · ${number(evidence.reference.tests)} tests</dd><dt>Seeded faults detected</dt><dd>${number(model.detected_faults)} / ${number(model.total_faults)}</dd></dl><ul class="decision-checks">${Object.entries(evidence.mutations).map(([name,outcome])=>`<li>${escape(name)}: ${escape(outcome.status)} (${number(outcome.failures)} test failures; ${number(outcome.errors)} errors; ${number(outcome.skipped)} skipped)</li>`).join("")}</ul><p>A test failure against a deliberately buggy function counts as detection. Test errors, skips and timeouts do not.</p><dl><dt>Provider-reported input tokens</dt><dd>${number(evidence.input_tokens)}</dd><dt>Generated candidates + thinking</dt><dd>${number(evidence.candidate_tokens)} + ${number(evidence.thinking_tokens)}</dd><dt>Recorded-usage catalog cost</dt><dd>$${money(evidence.catalog_cost_usd)} USD</dd></dl><p><a class="decision-suite-link" download="${escape(result.task_id)}-${escape(model.model_id)}.txt" href="/api/decision/tasks/${escape(result.task_id)}/suite/${escape(model.model_id)}">Download checked suite as text ↓</a></p><details><summary>Response provenance <span>⌄</span></summary><p class="decision-hashes">Model version: ${escape(evidence.model_version)}<br>Suite SHA256: ${escape(evidence.suite_sha256)}<br>Runner image: ${escape(evidence.image_id)}</p></details>` : `<p>No saved response for this exact model/task. Quality and recorded usage are unknown. Another model's results are not substituted.</p>`;
    return `<article class="card research-model"><span class="micro-pill">${model.gate === "passed" ? "SAVED SUITE PASSED" : model.gate === "failed" ? "SAVED SUITE FAILED" : "NOT TESTED"}</span><h3>${escape(model.model_name)}</h3>${checks}<div class="decision-reference"><span class="eyebrow">SEPARATE CLEER SESSION REFERENCE</span><p>${escape(result.reference.request.workload)} · ${number(result.reference.request.grid_g_per_kwh)} gCO₂e/kWh assumed</p>${record ? `<dl><dt>Published facility energy / reference session</dt><dd>${number(record.energy_wh_mean)} Wh</dd><dt>Published energy SD · not a confidence interval</dt><dd>${record.energy_wh_sd === null ? "Not reported" : number(record.energy_wh_sd)+" Wh"}</dd><dt>Reference operational carbon / session</dt><dd>${number(reference.operational_carbon_g)} gCO₂e</dd></dl>` : "<p>No reference available.</p>"}<p>Not measured or calibrated to the generated suite above.</p></div></article>`;
  }).join("");
  const source=result.reference.source;
  get("decision-attribution").textContent=`${source.publisher}, ${source.title}; dataset ${source.dataset_generated_at}, engine ${source.dataset_engine}; related report ${source.related_report_version}; revision ${source.commit.slice(0,12)}. ${source.license}, non-commercial use with attribution. ${source.modifications}`;
  for (const [id,key] of [["report","report_url"],["data","source_url"],["license","license_url"]]) get("decision-"+id+"-link").href=source[key];
  get("decision-cost-note").textContent=`Saved response evidence dated ${result.evidence_observed_on}. ${result.cost_basis}`;
  get("decision-usage-note").textContent=result.usage_note;
  get("decision-carbon-note").textContent=result.reference.carbon_basis;
  get("decision-limitations").replaceChildren(...[...result.limitations,...source.limitations].map(text=>{const li=document.createElement("li");li.textContent=text;return li;}));
  get("decision-fingerprints").textContent=`Source report SHA256: ${result.evidence_source_report_sha256}\nBenchmark SHA256: ${result.benchmark_sha256}\nIdentical task prompt SHA256: ${result.prompt_sha256}`;
  get("decision-status").textContent="Read from saved evidence locally · zero new model calls. No actual energy or carbon saving is claimed.";
  get("decision-results").hidden=false;
  get("decision-export").disabled=false;
}

async function calculate(event) {
  event?.preventDefault();
  if (!get("decision-form").reportValidity()) return;
  invalidate();
  state.clearError();
  const sequence=++state.sequence;
  get("decision-calculate").disabled=true;
  get("decision-status").textContent="Reading saved checks and published references…";
  try {
    const task=get("decision-task").value;
    const [result,workflow]=await Promise.all([
      requestLocal("/api/decision",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({task_id:task,workload:get("decision-workload").value,grid_g_per_kwh:get("decision-grid").value})}),
      requestLocal(`/api/decision/tasks/${encodeURIComponent(task)}/workflow`),
    ]);
    if (workflow.run.source_report_sha256!==result.evidence_source_report_sha256) throw new Error("Workflow and task evidence refer to different saved runs.");
    if(sequence===state.sequence) render({...result,workflow});
  } catch(error) {
    if(sequence===state.sequence) { get("decision-status").textContent="Decision evidence unavailable. Check inputs or reconnect the local app."; state.error(error); }
  } finally {
    if(sequence===state.sequence) get("decision-calculate").disabled=false;
  }
}

export function wireDecision(onError,onClearError) {
  state.error=onError;
  state.clearError=onClearError;
  get("decision-form").addEventListener("submit",calculate);
  get("decision-form").addEventListener("input",invalidate);
  get("decision-export").addEventListener("click",()=>{
    if(!state.result) return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(state.result,null,2)],{type:"application/json"}));
    const link=document.createElement("a"); link.href=url; link.download="carbontrace-task-decision.json"; link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
}

export async function loadDecision() {
  if(state.loaded) return;
  const [tasks,research]=await Promise.all([requestLocal("/api/decision/tasks"),requestLocal("/api/research/catalog")]);
  get("decision-task").innerHTML=tasks.map(task=>`<option value="${escape(task.id)}">${escape(task.title)}</option>`).join("");
  get("decision-workload").innerHTML='<option value="">Choose a reference workload…</option>'+Object.keys(research.workloads).sort().map(key=>`<option value="${escape(key)}">${escape(key.replace("."," · "))}</option>`).join("");
  for(const id of ["decision-task","decision-workload","decision-calculate"]) get(id).disabled=false;
  get("decision-status").textContent="Choose a reference workload and review the saved task evidence. No model calls.";
  state.loaded=true;
}
