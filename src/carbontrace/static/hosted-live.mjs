import { requestLocal as api } from "./api-client.mjs";

const get = id => document.getElementById(id);
let plan = null;
let pairedPlan = null;
let receiptPlan = null;
let busy = false;
let sequence = 0;
const post = value => ({method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value)});
const dollars = value => "$" + Number(value).toFixed(6);
const escape = value => String(value).replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);

export function invalidateHosted() {
  plan = null;
  pairedPlan = null;
  sequence += 1;
  if (get("hosted-prepare")) get("hosted-prepare").disabled = true;
  if (get("hosted-compare")) get("hosted-compare").disabled = true;
}

async function poolStatus() {
  const pool = await api("/api/hosted/status");
  get("hosted-pool").textContent = `${dollars(pool.remaining_usd)} of $${Number(pool.budget_usd).toFixed(2)} sponsor model budget available · until ${new Date(pool.expires_at).toLocaleDateString()}.`;
  return pool;
}

function renderReceipt(receipt) {
  get("hosted-status").textContent = `${receipt.status}${receipt.error ? " · " + receipt.error : ""}${receipt.billing_uncertain ? " · Billing may have occurred; do not resubmit." : ""}${receipt.persistence_warning ? " · " + receipt.persistence_warning : ""}`;
  const paired = Array.isArray(receipt.responses);
  get("hosted-comparison").hidden = !paired;
  if (paired) {
    get("hosted-result").hidden = true;
    renderComparison(receipt);
    return;
  }
  const result = receipt.response;
  get("hosted-result").hidden = !result;
  if (!result) return;
  const usage = result.effective_usage || result.raw_usage;
  get("hosted-metrics").textContent = `${result.model_version || "Version unavailable"} · ${usage.input_tokens ?? "?"} input / ${usage.candidate_tokens ?? "?"} output / ${usage.thinking_tokens ?? 0} thinking tokens · ${Number(result.elapsed_seconds).toFixed(2)} s · catalog estimate ${result.estimated_cost_usd ? dollars(result.estimated_cost_usd) : "unavailable"}. Finish: ${result.finish_reason || "unknown"}.`;
  get("hosted-output").textContent = result.text;
}

function renderComparison(receipt) {
  const summary = receipt.comparison;
  get("hosted-pair-summary").textContent = summary?.complete
    ? (summary.lower_observed_cost_model ? `Lower observed API cost: ${summary.lower_observed_cost_model} · ${dollars(summary.cost_difference_usd)} difference (${Number(summary.cost_reduction_percent).toFixed(1)}%). Quality is not automatically checked.` : "Both responses have the same observed catalog cost. Quality is not automatically checked.")
    : "Comparison incomplete. Available output is preserved; no automatic retry.";
  const research = receipt.quote?.research;
  get("hosted-pair-results").innerHTML = receipt.responses.map(row => {
    const result = row.response, usage = result?.effective_usage || result?.raw_usage;
    const reference = research?.models.find(model => model.model_name === row.model_name);
    const metrics = result ? `${usage.input_tokens ?? "?"} input · ${usage.candidate_tokens ?? "?"} output · ${usage.thinking_tokens ?? 0} thinking tokens · ${Number(result.elapsed_seconds).toFixed(2)} s · ${result.estimated_cost_usd ? dollars(result.estimated_cost_usd) : "cost unavailable"}` : "No returned output";
    const note = reference?.available ? `Published ${research.request.workload} reference: mean ${Number(reference.total_energy_wh).toPrecision(3)} Wh/session; per-session SD ${Number(reference.evidence.energy_wh_sd).toPrecision(3)} Wh. Separate from this request.` : "No environmental workload reference selected.";
    return `<article class="workflow-response"><span class="eyebrow">${escape(row.status.replaceAll("_", " "))}</span><h3>${escape(row.model_name)}</h3><p>${escape(metrics)}</p><p>${escape(note)}</p><p>${escape(row.error || (result ? `Finish: ${result.finish_reason || "unknown"}${result.complete_output ? "" : " · output incomplete"}` : "Not sent"))}</p><pre class="workflow-code">${escape(result?.text || "No response available.")}</pre></article>`;
  }).join("");
  get("hosted-pair-method").hidden = !research;
  if (research) {
    get("hosted-pair-citation").textContent = `${research.source.publisher} · ${research.source.license}. ${research.uncertainty_note} These standardized sessions do not predict or measure this prompt's energy or carbon.`;
    get("hosted-pair-report").href = research.source.report_url;
  }
}

// Free preparation binds the visible button to this exact draft and selected model.
// No generation or provider token-count operation runs until the visitor clicks.
export async function prepareHosted(draft, expectedHash) {
  if (!get("hosted-prepare")) return;
  invalidateHosted();
  const version = sequence;
  const button = get("hosted-prepare");
  const compareButton = get("hosted-compare");
  button.textContent = "Preparing run option…";
  compareButton.textContent = "Preparing comparison…";
  try {
    const [prepared, comparison] = await Promise.all([
      api("/api/hosted/quote", post(draft)),
      api("/api/hosted/quote", post({...draft, compare_models: true})),
    ]);
    if (version !== sequence) return;
    if (prepared.quote.prompt_sha256 !== expectedHash || comparison.quote.prompt_sha256 !== expectedHash) throw new Error("Request changed; preview again.");
    const pool = await poolStatus();
    if (version !== sequence) return;
    plan = prepared;
    pairedPlan = comparison;
    const available = !pool.halted && Number(pool.remaining_usd) >= Number(plan.quote.reservation_usd) && new Date(pool.expires_at) > new Date();
    button.textContent = `Run ${plan.quote.models[0].model_name} →`;
    button.disabled = busy || !available;
    const pairAvailable = !pool.halted && Number(pool.remaining_usd) >= Number(pairedPlan.quote.reservation_usd) && new Date(pool.expires_at) > new Date();
    compareButton.textContent = "Compare Flash-Lite + Flash →";
    compareButton.disabled = busy || !pairAvailable;
    get("hosted-run-note").textContent = available
      ? `Sponsored · selected: ${dollars(plan.quote.reservation_usd)} reserved; both: ${dollars(pairedPlan.quote.reservation_usd)}. Clicking sends your text to Google Cloud, stored privately for 7 days. No automatic retries.`
      : "Live demo budget unavailable. Preview and recorded results still work.";
  } catch (error) {
    if (version !== sequence) return;
    button.textContent = "Live run unavailable";
    button.disabled = true;
    compareButton.textContent = "Comparison unavailable";
    compareButton.disabled = true;
    get("hosted-run-note").textContent = error.message;
  }
}

export async function runHosted(expectedHash, compareModels = false) {
  const selected = compareModels ? pairedPlan : plan;
  if (!selected || busy || selected.quote.prompt_sha256 !== expectedHash) return;
  if (new Date(selected.quote.expires_at) <= new Date()) {
    invalidateHosted();
    throw new Error("Run option expired. Preview again to refresh it for free.");
  }
  receiptPlan = selected;
  invalidateHosted();
  busy = true;
  get("hosted-panel").hidden = false;
  get("live-plan").hidden = true;
  get("live-status").hidden = true;
  get("hosted-result").hidden = true;
  get("hosted-comparison").hidden = true;
  get("hosted-refresh").hidden = false;
  get("hosted-mode").textContent = compareModels ? "LIVE GEMINI · SAME REQUEST · TWO MODELS" : "LIVE GEMINI · SELECTED MODEL";
  get("hosted-title").textContent = compareModels ? "Flash-Lite vs Flash" : selected.quote.models[0].model_name;
  get("hosted-cost").textContent = `Sponsor reservation ${dollars(selected.quote.reservation_usd)} · full-rate stress estimate, not an invoice or Google billing cap.`;
  get("hosted-payload").textContent = selected.quote.exact_payload;
  get("hosted-hash").textContent = selected.quote.plan_sha256;
  get("hosted-reopen").href = "/?hosted=" + selected.quote.id;
  get("hosted-status").textContent = compareModels ? "Requesting both models in sequence…" : "Requesting Gemini…";
  get("hosted-panel").scrollIntoView({block: "start"});
  try {
    renderReceipt(await api("/api/hosted/execute", post({plan: selected, approval_hash: selected.quote.plan_sha256, allowance_usd: selected.quote.allowance_usd, agreed: true}), 180000));
  } catch {
    get("hosted-status").textContent = "Response unavailable. Read the saved receipt before starting another run; no automatic retry was sent.";
  } finally {
    busy = false;
  }
  try { await poolStatus(); } catch { /* Keep the response visible. */ }
}

export async function openHosted(id) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error("Invalid hosted result ID.");
  const receipt = await api(`/api/hosted/runs/${id}`);
  receiptPlan = {quote: receipt.quote};
  const paired = Array.isArray(receipt.responses);
  get("hosted-panel").hidden = false;
  get("live-plan").hidden = true;
  get("live-status").hidden = true;
  get("hosted-refresh").hidden = false;
  get("hosted-mode").textContent = "SAVED HOSTED RESULT · NO NEW MODEL CALLS";
  get("hosted-title").textContent = paired ? "Flash-Lite vs Flash" : receipt.quote.models[0].model_name;
  get("hosted-cost").textContent = `Reserved ${dollars(receipt.quote.reservation_usd)} from the shared model allowance. Viewing this result sends no new model calls.`;
  get("hosted-payload").textContent = receipt.quote.exact_payload;
  get("hosted-hash").textContent = receipt.quote.plan_sha256;
  get("hosted-reopen").href = "/?hosted=" + id;
  renderReceipt(receipt);
  try { await poolStatus(); } catch { /* Preserve the saved response. */ }
}

export function wireHosted() {
  if (!get("hosted-panel")) return;
  get("hosted-refresh").addEventListener("click", async () => {
    if (!receiptPlan) return;
    try { renderReceipt(await api(`/api/hosted/runs/${receiptPlan.quote.id}`)); }
    catch (error) { get("hosted-status").textContent = error.message; }
  });
}
