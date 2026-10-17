import {requestLocal} from "./api-client.mjs";

const get = id => document.getElementById(id);
const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);

export function renderWorkflow(result, isCurrent, onError) {
  const workflow=result.workflow;
  const run=workflow.run;
  const recorded=new Date(run.recorded_at).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",dateStyle:"medium",timeStyle:"short"});
  get("workflow-summary").textContent=`Completed ${recorded} IST · project ${run.project} · ${run.region}, API ${run.api_version}. Full experiment: ${run.generation_calls} generations, ${run.token_count_calls} token counts and ${run.metadata_reads} metadata reads across three tasks; catalog estimate US$${run.full_run_catalog_cost_usd} before tax/FX. The steps below show this selected task's two responses.`;
  const chosen=result.models.find(model=>model.model_id===result.recommended_model);
  const steps=[
    ["Exact prompt", "The same frozen source and requirements were sent to both models."],
    ["Cloud checks", "Google model identities and input-token counts were checked before generation."],
    ["Gemini generation", `Two saved pytest suites · ${run.thinking_level} thinking · ${run.maximum_generated_tokens}-token requested cap · ${run.automatic_retries} retries.`],
    ["Isolated quality gate", result.models.map(model=>`${model.model_name}: ${model.gate}, ${model.detected_faults ?? "?"}/${model.total_faults} faults detected.`).join(" ")],
    ["Model decision", chosen ? `${chosen.model_name} is the task-scoped candidate. Quality is checked before the CLEER reference is considered.` : "No candidate selected until the saved quality evidence supports a decision."],
  ];
  get("workflow-steps").innerHTML=steps.map(([title,description],index)=>`<li><span class="workflow-step-number">${index+1}</span><strong>${escape(title)}</strong><p>${escape(description)}</p></li>`).join("");
  get("workflow-prompt").textContent=workflow.exact_prompt;
  get("workflow-responses").innerHTML=workflow.requests.map((request,index)=>`<article class="workflow-response"><span class="micro-pill">RECORDED COMPLETED</span><h4>${escape(request.model_id)}</h4><p>Metadata identity: ${escape(request.metadata_name)}<br>Input count before generation: ${request.counted_input_tokens} tokens<br>Response model: ${escape(request.response_model_version)}<br>Finish reason: ${escape(request.finish_reason)}</p><button type="button" class="outline-button" id="workflow-view-${index}">View saved generated tests</button><div id="workflow-suite-${index}" hidden><p class="workflow-suite-note"></p><pre class="workflow-code"></pre></div></article>`).join("");
  get("workflow-boundary").textContent=`${workflow.note} Generated Python was evaluated only in the separate rootless container. CLEER figures are a published session reference, not energy measurements of this run.`;
  workflow.requests.forEach((request,index)=>{
    let loaded=false;
    get(`workflow-view-${index}`).addEventListener("click",async()=>{
      if (!isCurrent()) return;
      const button=get(`workflow-view-${index}`);
      const panel=get(`workflow-suite-${index}`);
      if (loaded) {
        panel.hidden=!panel.hidden;
        button.textContent=panel.hidden ? "View saved generated tests" : "Hide saved generated tests";
        return;
      }
      button.disabled=true;
      button.textContent="Reading saved suite…";
      try {
        const suite=await requestLocal(`/api/decision/tasks/${encodeURIComponent(result.task_id)}/suite/${encodeURIComponent(request.model_id)}/preview`);
        if (!isCurrent()) return;
        const evidence=result.models.find(model=>model.model_id===request.model_id)?.evidence;
        if (!evidence || suite.sha256!==evidence.suite_sha256) throw new Error("Saved suite does not match this task's checked evidence.");
        panel.querySelector("pre").textContent=suite.source_code;
        panel.querySelector("p").textContent=suite.note;
        panel.hidden=false;
        loaded=true;
        button.textContent="Hide saved generated tests";
      } catch(error) {
        if (isCurrent()) { onError(error); button.textContent="View saved generated tests"; }
      } finally {
        if (isCurrent()) button.disabled=false;
      }
    });
  });
}
