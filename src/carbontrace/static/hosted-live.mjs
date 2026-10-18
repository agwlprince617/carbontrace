import { requestLocal as api } from "./api-client.mjs";

const get = id => document.getElementById(id);
let plan = null;
let dispatched = false;
const post = value => ({method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value)});

async function poolStatus() {
  const pool = await api("/api/hosted/status");
  get("hosted-pool").textContent = `${pool.remaining} of ${pool.limit} shared runs remain · expires ${new Date(pool.expires_at).toLocaleDateString()}. Failed reservations also consume a run.`;
  get("hosted-execute").disabled = dispatched || !pool.remaining || new Date(pool.expires_at) <= new Date();
}

function renderReceipt(receipt) {
  get("hosted-status").textContent = `${receipt.status}${receipt.error ? " · " + receipt.error : ""}${receipt.billing_uncertain ? " · Billing may have occurred; do not resubmit." : ""}${receipt.persistence_warning ? " · " + receipt.persistence_warning : ""}`;
  const result = receipt.response;
  get("hosted-result").hidden = !result;
  if (!result) return;
  const usage = result.effective_usage || result.raw_usage;
  get("hosted-metrics").textContent = `${result.model_version || "Version unavailable"} · ${usage.input_tokens ?? "?"} input / ${usage.candidate_tokens ?? "?"} output / ${usage.thinking_tokens ?? 0} thinking tokens · ${Number(result.elapsed_seconds).toFixed(2)} s · conservative catalog estimate ${result.estimated_cost_usd ? "$" + Number(result.estimated_cost_usd).toFixed(6) : "unavailable"}. Finish: ${result.finish_reason || "unknown"}.`;
  get("hosted-output").textContent = result.text;
}

export async function prepareHosted(draft, expectedHash) {
  plan = await api("/api/hosted/quote", post(draft));
  if (plan.quote.prompt_sha256 !== expectedHash) throw new Error("The prepared request differs from the preview. Preview again.");
  dispatched = false;
  get("hosted-panel").hidden = false;
  get("live-plan").hidden = true;
  get("live-status").hidden = true;
  get("hosted-approval").hidden = false;
  get("hosted-consent").checked = false;
  get("hosted-result").hidden = true;
  get("hosted-refresh").hidden = true;
  get("hosted-status").textContent = "No generation sent. Quote expires in ten minutes.";
  get("hosted-title").textContent = plan.quote.models[0].model_name;
  get("hosted-cost").textContent = `One generation · up to $${Number(plan.quote.estimated_cost_usd).toFixed(5)} estimated; $${Number(plan.quote.stress_cost_usd).toFixed(5)} stress estimate, before tax/FX. Uses full catalog rates, excluding promotional credits.`;
  get("hosted-payload").textContent = plan.quote.exact_payload;
  get("hosted-hash").textContent = plan.quote.plan_sha256;
  await poolStatus();
  get("hosted-panel").scrollIntoView({block: "start"});
}

export function wireHosted() {
  if (!get("hosted-panel")) return;
  get("hosted-execute").addEventListener("click", async () => {
    if (!plan || dispatched) return;
    if (!get("hosted-consent").checked) {
      get("hosted-status").textContent = "Approve the priced request using the checkbox first.";
      return;
    }
    dispatched = true;
    get("hosted-execute").disabled = true;
    get("hosted-approval").hidden = true;
    get("hosted-refresh").hidden = false;
    get("hosted-status").textContent = "Reserving one shared run, then requesting Gemini…";
    try {
      renderReceipt(await api("/api/hosted/execute", post({plan, approval_hash: plan.quote.plan_sha256, allowance_usd: plan.quote.allowance_usd, agreed: true}), 180000));
    } catch {
      get("hosted-status").textContent = "The request may have been dispatched. Read its saved receipt; do not submit another run automatically.";
    }
    try { await poolStatus(); } catch { /* Keep the completed response visible. */ }
  });
  get("hosted-refresh").addEventListener("click", async () => {
    try { renderReceipt(await api(`/api/hosted/runs/${plan.quote.id}`)); }
    catch (error) { get("hosted-status").textContent = error.message; }
  });
}
