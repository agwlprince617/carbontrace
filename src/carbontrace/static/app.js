import { requestLocal as api } from "./api-client.mjs";
import { loadResearch, wireResearch } from "./research.mjs";
import { loadDecision, wireDecision } from "./decision.mjs";

const $ = (id) => document.getElementById(id);
const state = { tasks: [], task: "clamp", result: null, profile: "compact" };
const advisor = { examples: [], workloads: {}, result: null, sequence: 0, exportUrl: null, timer: null };
let dataReady = false;
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const integer = (value) => Number(value).toLocaleString("en-US");
const bounds = (interval, unit) => `${interval.low.toFixed(3)}–${interval.high.toFixed(3)} ${unit}`;

function showError(error) {
  $("error-message").textContent = error.message || String(error);
  $("reconnect-button").hidden = !error.reconnect;
  $("error").hidden = false;
}

function clearError() {
  $("error").hidden = true;
}

function renderTasks() {
  $("task-list").innerHTML = state.tasks.map((task, index) => `<button class="task-option ${task.id === state.task ? "active" : ""}" aria-pressed="${task.id === state.task}" data-task="${escapeHTML(task.id)}"><span class="radio-dot"></span><span><strong>${escapeHTML(task.title)}</strong><small>${escapeHTML(task.category)}</small></span><span class="task-index">${String(index + 1).padStart(2, "0")}</span></button>`).join("");
  const task = state.tasks.find((item) => item.id === state.task);
  $("source-code").textContent = task.source;
  $("download-source").href = `/api/tasks/${state.task}/source`;
  document.querySelectorAll("[data-task]").forEach((button) => button.addEventListener("click", () => {
    state.task = button.dataset.task;
    state.result = null;
    $("results").hidden = true;
    $("empty-state").hidden = false;
    $("export-button").hidden = true;
    clearError();
    renderTasks();
  }));
}

function scenarioFromForm() {
  if (!$("scenario-enabled").checked) return null;
  const number = (id) => {
    const input = $(id);
    if (!input.value.trim() || !input.checkValidity()) throw new Error(`Check the scenario value for ${input.parentElement.textContent.trim()}.`);
    return Number(input.value);
  };
  const scenario = {
    compact_power_w: { low: number("compact-low"), high: number("compact-high") },
    strong_power_w: { low: number("strong-low"), high: number("strong-high") },
    pue: number("pue"), grid_g_per_kwh: number("grid"),
  };
  if (scenario.compact_power_w.low > scenario.compact_power_w.high || scenario.strong_power_w.low > scenario.strong_power_w.high) throw new Error("Each scenario upper power bound must be at least its lower bound.");
  return scenario;
}

function renderEvidence() {
  const result = state.result;
  if (!result) return;
  const attempt = state.profile === "compact" ? result.carbontrace.attempts[0] : result.baseline.attempts[0];
  $("inspect-compact").classList.toggle("selected", state.profile === "compact");
  $("inspect-strong").classList.toggle("selected", state.profile === "strong");
  $("inspect-compact").setAttribute("aria-pressed", String(state.profile === "compact"));
  $("inspect-strong").setAttribute("aria-pressed", String(state.profile === "strong"));
  const quality = attempt.quality;
  $("evidence-status").textContent = `${quality.assertions.filter((item) => item.passed).length}/${quality.assertions.length} assertions pass on the correct function · ${quality.detected}/${quality.total_mutations} seeded faults detected · ${attempt.accepted ? "meets" : "below"} the selected quality bar`;
  $("mutation-list").innerHTML = quality.mutations.map((item) => `<div class="mutation ${item.detected ? "" : "missed"}"><span class="check" aria-label="${item.detected ? "Detected" : "Missed"}">${item.detected ? "✓" : "!"}</span><span>${escapeHTML(item.description)}</span></div>`).join("");
  $("suite-code").textContent = attempt.suite_code;
  $("download-suite").href = `/api/tasks/${result.task_id}/suite/${state.profile}`;
}

function renderResult(result) {
  state.result = result;
  state.profile = "compact";
  $("empty-state").hidden = true;
  $("results").hidden = false;
  $("export-button").hidden = false;
  $("export-button").href = `/api/runs/${result.id}/export`;
  const compactAccepted = result.outcome === "compact_accepted";
  const failed = result.outcome === "quality_failed";
  $("outcome-card").classList.toggle("warning", !compactAccepted);
  $("outcome-mark").textContent = compactAccepted ? "✓" : "↗";
  $("outcome-label").textContent = compactAccepted ? "QUALITY GATE PASSED" : failed ? "QUALITY REQUIREMENT NOT MET" : "ESCALATION REQUIRED";
  $("outcome-title").textContent = compactAccepted ? "The compact fixture is sufficient here." : failed ? "An acceptable suite was not found." : "A compact first attempt adds overhead here.";
  $("outcome-description").textContent = result.explanation;
  const baseline = result.baseline;
  const selected = result.carbontrace;
  const final = selected.attempts[selected.attempts.length - 1];
  $("metric-quality").textContent = `${final.quality.detected}/${final.quality.total_mutations}`;
  $("metric-attempts").textContent = `${selected.attempts.length} vs ${baseline.attempts.length}`;
  $("metric-impact").textContent = result.scenario ? "Scenario only" : "Uncalibrated";
  const scenarioNotes = { lower: "Lower GWP under these assumptions", higher: "Higher GWP under these assumptions", overlap: "Ranges overlap; no clear direction", unavailable: "Quality evidence is insufficient" };
  $("metric-impact-note").textContent = result.scenario ? scenarioNotes[result.impact_comparison] : "Provider energy data needed";
  const status = (policy) => policy.accepted ? '<span class="status-chip">Quality bar met</span>' : '<span class="status-chip">Quality bar missed</span>';
  const rows = [
    ["Final quality gate", status(baseline), status(selected), true],
    ["Seeded faults detected", `${baseline.attempts[0].quality.detected}/4`, `${final.quality.detected}/4`],
    ["Illustrative generations", baseline.attempts.length, selected.attempts.length],
    ["Illustrative total tokens", integer(baseline.total_tokens), integer(selected.total_tokens)],
    ["Assumed generation time", `${baseline.total_seconds.toFixed(1)} s`, `${selected.total_seconds.toFixed(1)} s`],
    ["Operational energy", baseline.impact ? bounds(baseline.impact.energy_wh, "Wh") : "Not estimated", selected.impact ? bounds(selected.impact.energy_wh, "Wh") : "Not estimated"],
    ["Operational GWP", baseline.impact ? bounds(baseline.impact.carbon_g, "gCO₂e") : "Not estimated", selected.impact ? bounds(selected.impact.carbon_g, "gCO₂e") : "Not estimated"],
  ];
  $("comparison-body").innerHTML = rows.map(([label, first, second, trusted]) => `<tr><td>${escapeHTML(label)}</td><td>${trusted ? first : escapeHTML(first)}</td><td>${trusted ? second : escapeHTML(second)}</td></tr>`).join("");
  const maximum = Math.max(baseline.total_tokens, selected.total_tokens, 1);
  $("baseline-bar").style.width = `${baseline.total_tokens / maximum * 100}%`;
  $("selected-bar").style.width = `${selected.total_tokens / maximum * 100}%`;
  $("baseline-tokens").textContent = integer(baseline.total_tokens);
  $("selected-tokens").textContent = integer(selected.total_tokens);
  const delta = selected.total_tokens - baseline.total_tokens;
  $("token-change").textContent = `${delta > 0 ? "+" : ""}${integer(delta)} illustrative tokens`;
  renderEvidence();
}

async function compare() {
  clearError();
  const button = $("compare-button");
  try {
    const request = { task_id: state.task, minimum_detection: Number($("quality").value), scenario: scenarioFromForm() };
    button.disabled = true;
    button.firstElementChild.textContent = "Checking local assertions…";
    const result = await api("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
    renderResult(result);
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Compare policies";
  }
}

function hideDecision() {
  $("decision-view").hidden = true;
  $("nav-decision").classList.remove("active");
}

async function showDecision() {
  hideResearch();
  clearError();
  for (const id of ["advisor-view", "lab-view", "history-view"]) $(id).hidden = true;
  for (const id of ["nav-advisor", "nav-lab", "nav-history"]) $(id).classList.remove("active");
  $("decision-view").hidden = false;
  $("nav-decision").classList.add("active");
  $("page-label").textContent = "Task decision";
  $("hero").hidden = false;
  $("hero").querySelector("h1").innerHTML = "Check the tests.<br><span>Then choose the model.</span>";
  $("hero").querySelector("p").textContent = "Saved task quality and recorded usage, alongside a separate published environmental reference.";
  try { await loadDecision(); } catch (error) { showError(error); }
}

function hideResearch() {
  hideDecision();
  $("research-view").hidden = true;
  $("nav-research").classList.remove("active");
  $("hero").querySelector("h1").innerHTML = "Right-size the model.<br><span>Before you send.</span>";
  $("hero").querySelector("p").textContent = "Explore cost, quality evidence, and published environmental references before choosing your next test-generation model.";
}

function showResearch() {
  hideDecision();
  clearError();
  ["advisor-view", "lab-view", "history-view"].forEach(id=>{ $(id).hidden = true; });
  ["nav-advisor", "nav-lab", "nav-history"].forEach(id=>$(id).classList.remove("active"));
  $("research-view").hidden = false;
  $("nav-research").classList.add("active");
  $("page-label").textContent = "Environmental comparison";
  $("hero").hidden = false;
  $("hero").querySelector("h1").innerHTML = "Compare AI impact.<br><span>With evidence.</span>";
  $("hero").querySelector("p").textContent = "Published workload energy, explicit electricity assumptions, and sources you can inspect.";
}

function showLab() {
  hideResearch();
  $("advisor-view").hidden = true;
  $("lab-view").hidden = false;
  $("history-view").hidden = true;
  $("hero").hidden = false;
  $("page-label").textContent = "Unit test lab";
  $("nav-lab").classList.add("active");
  $("nav-history").classList.remove("active");
  $("nav-advisor").classList.remove("active");
}

function showAdvisor() {
  hideResearch();
  clearError();
  $("advisor-view").hidden = false;
  $("lab-view").hidden = true;
  $("history-view").hidden = true;
  $("hero").hidden = false;
  $("page-label").textContent = "Before you send";
  $("nav-advisor").classList.add("active");
  $("nav-lab").classList.remove("active");
  $("nav-history").classList.remove("active");
}

function invalidatePreview() {
  clearTimeout(advisor.timer);
  advisor.timer = null;
  advisor.sequence += 1;
  advisor.result = null;
  $("advisor-output").hidden = true;
  $("advisor-pending").hidden = false;
  $("export-plan").disabled = true;
  $("generated-high").setCustomValidity("");
  if (advisor.exportUrl) URL.revokeObjectURL(advisor.exportUrl);
  advisor.exportUrl = null;
  setPreviewBusy(false);
}

function setPreviewBusy(busy) {
  $("preview-button").disabled = busy;
  $("preview-button").firstElementChild.textContent = busy ? "Building local preview…" : "Preview model trade-offs";
  $("advisor-output").setAttribute("aria-busy", String(busy));
}

function schedulePreview() {
  clearTimeout(advisor.timer);
  if (!$("advisor-auto-update").checked) {
    $("estimate-status").textContent = "Draft changed · click Preview model trade-offs to update.";
    return;
  }
  $("estimate-status").textContent = "Waiting for your edits · estimates update locally. No model call.";
  advisor.timer = setTimeout(() => {
    advisor.timer = null;
    previewDraft(undefined, true);
  }, 600);
}

function renderAssumptionReference(result) {
  const scenario = result.carbon_scenario;
  $("carbon-assumption-reference").hidden = !scenario;
  if (!scenario) return;
  const format = (value) => value.toLocaleString("en-US", {maximumSignificantDigits:6});
  const range = (value) => value.low === value.high ? format(value.low) : `${format(value.low)}–${format(value.high)}`;
  const compact = result.models.find((model) => model.role === "compact");
  const strong = result.models.find((model) => model.role === "strong");
  const shared = (label, value) => [label, value, value];
  const rows = [
    ["Visible input tokens", range(compact.input_tokens), range(strong.input_tokens)],
    shared("Generated tokens · assumed", `${integer(result.generated_low)}–${integer(result.generated_high)}`),
    ["Allocated power · assumed W", range(scenario.compact_power_w), range(scenario.strong_power_w)],
    shared("Input speed · assumed tokens/s", format(scenario.input_tokens_per_second)),
    shared("Generated speed · assumed tokens/s", format(scenario.generated_tokens_per_second)),
    shared("Facility overhead · assumed PUE", format(scenario.pue)),
    shared("Electricity · assumed gCO₂e/kWh", format(scenario.grid_g_per_kwh)),
  ];
  $("carbon-assumption-rows").innerHTML = rows.map(([label, ...values]) => `<tr><th scope="row">${escapeHTML(label)}</th>${values.map(value=>`<td>${escapeHTML(value)}</td>`).join("")}</tr>`).join("");
  const lower = compact.illustrative_impact;
  const lines = [
    "Worked example · Flash-Lite lower scenario (rounded)",
    `Time ≈ ${format(compact.input_tokens.low)} ÷ ${format(scenario.input_tokens_per_second)} + ${format(result.generated_low)} ÷ ${format(scenario.generated_tokens_per_second)} = ${format(lower.assumed_seconds.low)} s`,
    `Energy ≈ ${format(scenario.compact_power_w.low)} W × ${format(lower.assumed_seconds.low)} s ÷ 3,600 × ${format(scenario.pue)} = ${format(lower.impact.energy_wh.low)} Wh`,
    `Carbon ≈ ${format(lower.impact.energy_wh.low)} Wh ÷ 1,000 × ${format(scenario.grid_g_per_kwh)} = ${format(lower.impact.carbon_g.low)} gCO₂e`,
  ];
  $("carbon-worked-example").replaceChildren(...lines.map((text) => { const line=document.createElement("span"); line.textContent=text; return line; }));
}

function renderWorkloadReference(reference) {
  $("advisor-reference-method").hidden = !reference;
  $("advisor-reference-results").replaceChildren();
  if (!reference) {
    $("advisor-reference-status").textContent = "Choose a reference workload";
    $("advisor-reference-note").textContent = "Choose a CLEER workload in the composer to see published environmental context. No workload is inferred from your prompt or tokens.";
    return;
  }
  const format = value => Number(value).toLocaleString("en-US", {maximumSignificantDigits: 5});
  $("advisor-reference-status").textContent = `${reference.request.workload.replace(".", " · ")} · one standardized session`;
  $("advisor-reference-note").textContent = `Published benchmark context, not your prompt's footprint. Electricity assumption: ${format(reference.request.grid_g_per_kwh)} gCO₂e/kWh. Changing prompt text or token scenarios does not scale these reference values.`;
  $("advisor-reference-results").innerHTML = reference.models.map(model => {
    if (!model.available) return `<div class="scenario-model-impact"><span>${escapeHTML(model.model_name)}</span><strong class="reference-unavailable">No published estimate</strong><small>${escapeHTML(model.note)}</small></div>`;
    const evidence = model.evidence;
    return `<div class="scenario-model-impact"><span>${escapeHTML(model.model_name)}</span><strong>${format(model.operational_carbon_g)} gCO₂e</strong><small>Operational carbon / reference session · assumed electricity</small><p>${format(evidence.energy_wh_mean)} Wh / reference session</p><small>Published energy SD: ${evidence.energy_wh_sd === null ? "Not reported" : format(evidence.energy_wh_sd) + " Wh"}. Not a confidence interval.</small><p>${escapeHTML(evidence.description)}</p><small>Source accelerator evidence: ${escapeHTML(evidence.estimation_basis)}. Facility overheads are modelled. Quality for your task is not established.</small></div>`;
  }).join("");
  const source = reference.source;
  $("advisor-reference-citation").textContent = `${source.publisher}, ${source.title}, dataset ${source.dataset_generated_at}; engine ${source.dataset_engine}. Related report: ${source.related_report_version}. Revision ${source.commit.slice(0,12)}. ${source.license}, non-commercial use with attribution.`;
  for (const [id, key] of [["report", "report_url"], ["data", "source_url"], ["schema", "schema_url"], ["license", "license_url"]]) $("advisor-reference-" + id + "-link").href = source[key];
  $("advisor-reference-basis").textContent = `${reference.carbon_basis} ${reference.uncertainty_note}`;
  $("advisor-reference-limitations").replaceChildren(...source.limitations.map(text => { const li = document.createElement("li"); li.textContent = text; return li; }));
  $("advisor-reference-modifications").textContent = source.modifications;
}

function renderPreview(result) {
  $("advisor-output").classList.remove("assumptions-only");
  advisor.result = result;
  renderWorkloadReference(result.research_reference);
  const money = (value) => Number(value).toLocaleString("en-US", { minimumFractionDigits: 5, maximumFractionDigits: 7 });
  $("advisor-guidance").textContent = result.guidance;
  const matchedCount = result.models.filter((model) => model.quality.matched_observation).length;
  const matched = matchedCount > 0;
  const development = !$("advisor-context").value && advisor.examples.some((example) => example.prompt === $("advisor-prompt").value);
  $("advisor-evidence-label").textContent = matched ? (matchedCount === result.models.length ? "MATCHING PILOT PROMPT · 1 RESPONSE / MODEL" : "MATCHING PILOT PROMPT · FLASH-LITE ONLY") : `${development ? "DEVELOPMENT EXAMPLE" : "CUSTOM DRAFT"} · QUALITY NOT ESTABLISHED`;
  $("model-previews").innerHTML = result.models.map((model) => {
    const match = model.quality.matched_observation;
    const tokenLabel = model.input_tokens.low === model.input_tokens.high ? integer(model.input_tokens.low) : `${integer(model.input_tokens.low)}–${integer(model.input_tokens.high)}`;
    const qualityLabel = match ? `${match.detected}/${match.total_mutations} seeded faults detected` : "No matching quality evidence";
    return `<article class="card model-preview ${model.selected ? "model-selected" : ""}"><div class="model-topline"><span>${model.role === "compact" ? "LOWER-PRICE CANDIDATE" : "COMPARISON MODEL"}</span><span class="model-choice">${model.selected ? "Selected" : "Alternative"}</span></div><h3>${model.role === "compact" ? "Gemini 3.5" : "Gemini 3.7"}<br><strong>${model.role === "compact" ? "Flash-Lite" : "Flash"}</strong></h3><div class="cost-preview"><span>Estimated API cost · USD</span><strong>${money(model.cost_usd.low)}<span>–</span>${money(model.cost_usd.high)}</strong><small>Under your token scenarios</small></div><div class="preview-input"><span>Visible input tokens</span><b>${tokenLabel}</b></div><p class="token-basis">${match ? "Previously observed for this identical prompt" : "Rough local planning scenarios"}</p><div class="preview-quality"><span class="quality-label">SAVED QUALITY EVIDENCE</span><strong>${escapeHTML(qualityLabel)}</strong><p>${match ? `${match.tests} tests passed in one saved suite.` : (model.quality.pilot_samples ? `Pilot: ${model.quality.pilot_accepted}/${model.quality.pilot_samples} accepted suites on other prompts.` : "")} ${escapeHTML(model.quality.note)}</p></div><button type="button" class="choose-model" data-model-role="${model.role}" aria-pressed="${model.selected}" ${model.selected ? "disabled" : ""}>${model.selected ? "Selected for this plan ✓" : "Select for this plan →"}</button></article>`;
  }).join("");
  document.querySelectorAll("[data-model-role]").forEach((button) => button.addEventListener("click", () => {
    $("advisor-model").value = button.dataset.modelRole;
    invalidatePreview();
    previewDraft();
  }));
  $("carbon-note").textContent = result.carbon.note;
  $("carbon-status").textContent = result.carbon_scenario ? "Illustrative scenario · not measured" : "Hardware illustration off";
  $("carbon-scenario-note").textContent = result.carbon_scenario ? result.carbon_scenario_note : "The CLEER reference above is available without hardware guesses. Optionally enable this separate sensitivity illustration to explore draft-based arithmetic. It does not use CLEER factors or measure provider carbon.";
  $("carbon-scenario-results").innerHTML = result.models.map((model) => {
    const scenario = model.illustrative_impact;
    if (!scenario) return "";
    const interval = (range, unit) => `${range.low.toLocaleString("en-US", {maximumSignificantDigits:3})}–${range.high.toLocaleString("en-US", {maximumSignificantDigits:3})} ${unit}`;
    return `<div class="scenario-model-impact"><span>${model.role === "compact" ? "Gemini 3.5 Flash-Lite" : "Gemini 3.7 Flash"}</span><strong>${interval(scenario.impact.carbon_g, "gCO₂e")}</strong><small>${interval(scenario.impact.energy_wh, "Wh")} · ${interval(scenario.assumed_seconds, "assumed s")}</small></div>`;
  }).join("");
  renderAssumptionReference(result);
  $("token-method").textContent = result.models.map(model => `${model.model_id}: ${model.input_tokens.note}`).join(" ");
  $("generated-method").textContent = `${integer(result.generated_low)}–${integer(result.generated_high)} tokens. ${result.generated_note}`;
  $("price-method").textContent = `Rates captured ${result.pricing_as_of}. ${result.pricing_note} Not a billing quote or cap.`;
  $("scope-method").textContent = result.scope_note;
  $("advisor-output").hidden = false;
  $("advisor-pending").hidden = true;
  $("export-plan").disabled = false;
  $("estimate-status").textContent = matched ? (matchedCount === result.models.length ? "Updated locally · saved input counts reused for both models. No model call." : "Updated locally · one saved input count reused; the other is approximated. No model call.") : "Updated locally · input tokens approximated from text size. No model call.";
}

async function previewDraft(event, quiet = false) {
  if (event) event.preventDefault();
  clearTimeout(advisor.timer);
  advisor.timer = null;
  $("generated-high").setCustomValidity(Number($("generated-high").value) < Number($("generated-low").value) ? "Upper scenario must be at least the lower scenario." : "");
  if (!(quiet ? $("advisor-form").checkValidity() : $("advisor-form").reportValidity())) {
    $("estimate-status").textContent = "Enter a prompt, valid token scenarios, and an electricity factor between 0 and 2000 to preview.";
    return;
  }
  let carbonScenario;
  try {
    carbonScenario = advisorCarbonScenario();
  } catch (error) {
    if (!quiet) showError(error);
    invalidateCarbonPreview();
    $("advisor-output").classList.add("assumptions-only");
    $("advisor-output").hidden = false;
    $("advisor-pending").hidden = true;
    $("carbon-assumptions").open = true;
    $("carbon-status").textContent = "Check the scenario inputs";
    $("carbon-scenario-note").textContent = error.message;
    $("estimate-status").textContent = "Check the carbon assumptions, then preview again.";
    return;
  }
  const sequence = ++advisor.sequence;
  clearError();
  setPreviewBusy(true);
  try {
    const reference = $("advisor-workload").value ? {workload: $("advisor-workload").value, grid_g_per_kwh: $("advisor-reference-grid").value} : null;
    const result = await api("/api/preflight", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: $("advisor-prompt").value, context: $("advisor-context").value, selected_model: $("advisor-model").value, generated_low: Number($("generated-low").value), generated_high: Number($("generated-high").value), carbon_scenario: carbonScenario, research_reference: reference }) });
    if (sequence === advisor.sequence) renderPreview(result);
  } catch (error) {
    if (sequence === advisor.sequence) showError(error);
  } finally {
    if (sequence === advisor.sequence) setPreviewBusy(false);
  }
}

function loadAdvisorExample() {
  if ($("advisor-example").value === "custom") {
    $("load-example").textContent = "Clear draft";
    $("advisor-prompt").value = "";
    $("advisor-context").value = "";
    invalidatePreview();
    $("estimate-status").textContent = "Paste your prompt and code. Estimates update locally after you pause typing.";
    $("advisor-prompt").focus();
    return;
  }
  const example = advisor.examples.find((item) => item.id === $("advisor-example").value);
  if (!example) return;
  $("load-example").textContent = "Reset example";
  $("advisor-prompt").value = example.prompt;
  $("advisor-context").value = "";
  invalidatePreview();
  previewDraft();
}

function advisorCarbonScenario() {
  if (!$("advisor-carbon-enabled").checked) return null;
  const number = (id) => {
    const input = $(id);
    if (!input.value.trim() || !input.checkValidity()) throw new Error("Check the carbon assumptions: power must be 0–100000 W, token speeds 1–1000000 tokens/s, PUE 1–3, and electricity 0–2000 gCO₂e/kWh.");
    return Number(input.value);
  };
  const scenario = {
    compact_power_w: {low:number("advisor-compact-low"), high:number("advisor-compact-high")},
    strong_power_w: {low:number("advisor-strong-low"), high:number("advisor-strong-high")},
    input_tokens_per_second:number("advisor-prefill"),
    generated_tokens_per_second:number("advisor-decode"),
    pue:number("advisor-pue"), grid_g_per_kwh:number("advisor-grid"),
  };
  if (scenario.compact_power_w.high < scenario.compact_power_w.low || scenario.strong_power_w.high < scenario.strong_power_w.low) throw new Error("Each upper allocated-power assumption must be at least its lower assumption.");
  return scenario;
}

function invalidateCarbonPreview() {
  // Keep the assumption editor visible while hiding obsolete numeric results.
  clearTimeout(advisor.timer);
  advisor.timer = null;
  advisor.sequence += 1;
  advisor.result = null;
  $("export-plan").disabled = true;
  $("carbon-scenario-results").replaceChildren();
  $("carbon-assumption-reference").hidden = true;
  $("carbon-status").textContent = "Assumptions changed · apply to recalculate";
  $("carbon-scenario-note").textContent = "Apply your assumptions to update this illustrative scenario. The previous values are no longer current.";
  if (advisor.exportUrl) URL.revokeObjectURL(advisor.exportUrl);
  advisor.exportUrl = null;
  setPreviewBusy(false);
}

function wireAdvisor() {
  $("advisor-form").addEventListener("submit", previewDraft);
  ["advisor-prompt", "advisor-context", "generated-low", "generated-high", "advisor-model", "advisor-workload", "advisor-reference-grid"].forEach((id) => $(id).addEventListener("input", () => {
    if (id === "advisor-workload") $("advisor-workload-description").textContent = advisor.workloads[$("advisor-workload").value] || "";
    if (id === "advisor-prompt" || id === "advisor-context") {
      $("advisor-example").value = "custom";
      $("load-example").textContent = "Clear draft";
    }
    invalidatePreview();
    schedulePreview();
  }));
  $("advisor-auto-update").addEventListener("change", () => {
    clearTimeout(advisor.timer);
    advisor.timer = null;
    if ($("advisor-auto-update").checked) schedulePreview();
    else $("estimate-status").textContent = "Automatic updates paused · click Preview model trade-offs when ready.";
  });
  $("load-example").addEventListener("click", loadAdvisorExample);
  $("advisor-example").addEventListener("change", loadAdvisorExample);
  $("update-carbon").addEventListener("click", previewDraft);
  document.querySelectorAll("#carbon-assumptions input").forEach((input) => input.addEventListener("input", () => { invalidateCarbonPreview(); schedulePreview(); }));
  $("export-plan").addEventListener("click", () => {
    if (!advisor.result) return;
    if (advisor.exportUrl) URL.revokeObjectURL(advisor.exportUrl);
    advisor.exportUrl = URL.createObjectURL(new Blob([JSON.stringify(advisor.result, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = advisor.exportUrl;
    link.download = "carbontrace-pre-send-plan.json";
    link.click();
  });
}

async function loadData() {
  const [tasks, examples, research] = await Promise.all([api("/api/tasks"), api("/api/preflight/examples"), api("/api/research/catalog")]);
  state.tasks = tasks;
  advisor.examples = examples;
  advisor.workloads = research.workloads;
  const previousWorkload = $("advisor-workload").value;
  $("advisor-workload").innerHTML = '<option value="">Choose a reference workload…</option>' + Object.keys(advisor.workloads).sort().map(key => `<option value="${escapeHTML(key)}">${escapeHTML(key.replace(".", " · "))}</option>`).join("");
  $("advisor-workload").value = previousWorkload;
  renderTasks();
  $("advisor-example").innerHTML = '<option value="custom">Custom prompt + code</option>' + examples.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.title)}</option>`).join("");
  $("advisor-example").value = $("advisor-prompt").value.trim() ? "custom" : examples[0].id;
  ["advisor-example", "load-example", "compare-button"].forEach((id) => { $(id).disabled = false; });
  dataReady = true;
  // A reconnect must preserve a draft already entered by the user.
  if (!$("advisor-prompt").value.trim()) {
    $("advisor-prompt").value = examples[0].prompt;
    invalidatePreview();
  }
}

async function reconnect() {
  const button = $("reconnect-button");
  button.disabled = true;
  try {
    await api("/api/health");
    if (!$("research-view").hidden) await loadResearch();
    if (!$("decision-view").hidden) await loadDecision();
    if (!dataReady) await loadData();
    clearError();
    if (!$("advisor-view").hidden) await previewDraft();
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
}

function restoreScenario(scenario) {
  $("scenario-enabled").checked = Boolean(scenario);
  if (!scenario) return;
  $("compact-low").value = scenario.compact_power_w.low;
  $("compact-high").value = scenario.compact_power_w.high;
  $("strong-low").value = scenario.strong_power_w.low;
  $("strong-high").value = scenario.strong_power_w.high;
  $("pue").value = scenario.pue;
  $("grid").value = scenario.grid_g_per_kwh;
}

async function showHistory() {
  clearError();
  try {
    const records = await api("/api/history");
    hideResearch();
    $("advisor-view").hidden = true;
    $("lab-view").hidden = true;
    $("history-view").hidden = false;
    $("hero").hidden = true;
    $("page-label").textContent = "Saved comparisons";
    $("nav-lab").classList.remove("active");
    $("nav-history").classList.add("active");
    $("nav-advisor").classList.remove("active");
    $("history-list").innerHTML = records.length ? records.map((record) => `<div class="history-item"><div><strong>${escapeHTML(record.task_title)}</strong><small>${escapeHTML(new Date(record.created_at).toLocaleString())} · ${record.minimum_detection}% gate · offline fixture</small></div><span class="micro-pill">${record.outcome === "compact_accepted" ? "COMPACT ACCEPTED" : record.outcome === "escalated" ? "ESCALATED" : "QUALITY FAILED"}</span><button data-run="${escapeHTML(record.id)}">Open →</button></div>`).join("") : '<p class="history-empty">Your first comparison will appear here. Evidence stays on this computer.</p>';
    document.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", async () => {
      try {
        const record = await api(`/api/runs/${button.dataset.run}`);
        state.task = record.task_id;
        $("quality").value = record.minimum_detection;
        restoreScenario(record.scenario);
        renderTasks();
        showLab();
        renderResult(record);
      } catch (error) { showError(error); }
    }));
  } catch (error) { showError(error); }
}

async function boot() {
  wireResearch(showError, clearError);
  wireDecision(showError, clearError);
  wireAdvisor();
  $("reconnect-button").addEventListener("click", reconnect);
  $("compare-button").addEventListener("click", compare);
  $("nav-lab").addEventListener("click", showLab);
  $("nav-advisor").addEventListener("click", showAdvisor);
  $("nav-research").addEventListener("click", showResearch);
  $("nav-decision").addEventListener("click", showDecision);
  $("nav-history").addEventListener("click", showHistory);
  $("nav-method").addEventListener("click", () => {
    showLab();
    $("scenario-details").open = true;
    $("scenario-section").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("inspect-compact").addEventListener("click", () => { state.profile = "compact"; renderEvidence(); });
  $("inspect-strong").addEventListener("click", () => { state.profile = "strong"; renderEvidence(); });
  $("live-readiness").addEventListener("click", () => $("live-dialog").showModal());
  ["close-dialog", "dialog-done"].forEach((id) => $(id).addEventListener("click", () => $("live-dialog").close()));
  try {
    showResearch();
    await Promise.all([loadData(), loadResearch()]);
    await previewDraft();
  } catch (error) { showError(error); }
}

boot();
