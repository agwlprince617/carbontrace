import { requestLocal } from "./api-client.mjs";

const get = id => document.getElementById(id);
const escape = value => String(value).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const number = value => Number(value).toLocaleString("en-US",{maximumSignificantDigits:6});
const state = {result:null, sequence:0, error:null, clearError:null};

function invalidate() {
  state.sequence += 1;
  state.result = null;
  get("research-export").disabled = true;
  get("research-results").replaceChildren();
  get("research-status").textContent = "Settings changed · calculate to update the comparison.";
  get("research-calculate").disabled = false;
}

function render(result) {
  state.result = result;
  const {request, source} = result;
  const evidence = result.models.find(model=>model.evidence)?.evidence;
  get("research-workload-note").textContent = `${request.workload} · ${evidence?.description || "No source record available."} Session token counts are not published; this is not the pasted prompt.`;
  get("research-results").innerHTML = result.models.map(model=>{
    if (!model.available) return `<article class="card research-model"><span class="micro-pill">NO DATA IN SNAPSHOT</span><h3>${escape(model.model_name)}</h3><p>${escape(model.note)}</p><p>Energy and carbon: unavailable.</p></article>`;
    const record=model.evidence;
    return `<article class="card research-model"><span class="micro-pill">PUBLISHED WORKLOAD ESTIMATE</span><h3>${escape(model.model_name)}</h3><dl><dt>Facility energy per standardized session</dt><dd>${number(record.energy_wh_mean)} Wh</dd><dt>Reported per-session SD</dt><dd class="research-secondary">${record.energy_wh_sd === null ? "Not reported" : number(record.energy_wh_sd)+" Wh"}</dd><dt>Energy for ${number(request.sessions)} standardized sessions</dt><dd>${number(model.total_energy_wh)} Wh</dd><dt>Operational carbon under your electricity assumption</dt><dd>${number(model.operational_carbon_g)} gCO₂e</dd></dl><p>${number(record.energy_wh_mean)} × ${number(request.sessions)} = ${number(model.total_energy_wh)} Wh<br>${number(model.total_energy_wh)} ÷ 1,000 × ${number(request.grid_g_per_kwh)} = ${number(model.operational_carbon_g)} gCO₂e</p><p>Source accelerator evidence: ${escape(record.estimation_basis)}. Facility totals include modelled overheads.</p><p>${escape(model.note)}</p></article>`;
  }).join("");
  get("research-citation").textContent = `${source.publisher}, ${source.title}. Dataset dated ${source.dataset_generated_at}; declared engine ${source.dataset_engine}. Related technical report: ${source.related_report_version}. Pinned revision ${source.commit.slice(0,12)}. Data licence: ${source.license}; non-commercial use with attribution.`;
  for(const [id,key] of [["research-report-link","report_url"],["research-data-link","source_url"],["research-schema-link","schema_url"],["research-license-link","license_url"]]) get(id).href=source[key];
  get("research-uncertainty").textContent=result.uncertainty_note;
  get("research-limitations").replaceChildren(...source.limitations.map(text=>{ const li=document.createElement("li"); li.textContent=text; return li; }));
  get("research-status").textContent="Calculated locally from the pinned dataset · no model calls. No quality equivalence or provider-wide ranking is established.";
  get("research-export").disabled=false;
}

async function calculate(event) {
  event?.preventDefault();
  if (!get("research-form").reportValidity()) return;
  state.clearError();
  const sequence=++state.sequence;
  state.result=null;
  get("research-export").disabled=true;
  get("research-results").replaceChildren();
  get("research-calculate").disabled=true;
  get("research-status").textContent="Calculating from published session estimates…";
  try {
    const result=await requestLocal("/api/research/compare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model_a:get("research-model-a").value,model_b:get("research-model-b").value,workload:get("research-workload").value,sessions:Number(get("research-sessions").value),grid_g_per_kwh:get("research-grid").value})});
    if(sequence===state.sequence) render(result);
  } catch(error) {
    if(sequence===state.sequence) {
      get("research-status").textContent="Comparison unavailable. Check the inputs or reconnect the local app.";
      state.error(error);
    }
  } finally {
    if(sequence===state.sequence) get("research-calculate").disabled=false;
  }
}

export function wireResearch(onError, onClearError) {
  state.error=onError;
  state.clearError=onClearError;
  get("research-form").addEventListener("submit",calculate);
  get("research-form").addEventListener("input",invalidate);
  get("research-export").addEventListener("click",()=>{
    if(!state.result) return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(state.result,null,2)],{type:"application/json"}));
    const link=document.createElement("a");
    link.href=url;
    link.download="carbontrace-cleer-comparison.json";
    link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
}

export async function loadResearch() {
  const catalog=await requestLocal("/api/research/catalog");
  for(const id of ["research-model-a","research-model-b"]) {
    const previous=get(id).value;
    get(id).innerHTML=catalog.models.map(name=>`<option value="${escape(name)}">${escape(name)}${catalog.unavailable_models.includes(name) ? " · not in snapshot" : ""}</option>`).join("");
    get(id).value=previous || (id.endsWith("a") ? "Gemini 3.5 Flash-Lite" : "Gemini 3.7 Flash");
    get(id).disabled=false;
  }
  const previous=get("research-workload").value;
  get("research-workload").innerHTML=Object.keys(catalog.workloads).sort().map(key=>`<option value="${escape(key)}">${escape(key.replace("."," · "))}</option>`).join("");
  get("research-workload").value=previous || "chat.light";
  get("research-workload").disabled=false;
  get("research-calculate").disabled=false;
  await calculate();
}
