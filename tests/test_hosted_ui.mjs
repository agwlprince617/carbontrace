import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import { invalidateHosted, prepareHosted, runHosted, openHosted, wireHosted } from "../src/carbontrace/static/hosted-live.mjs";

let elements;
let calls;
const quote = (hash = "draft", paired = false) => ({signature: "signed", quote: {
  id: "run", prompt_sha256: hash, plan_sha256: "exact-plan", allowance_usd: paired ? "0.089293" : "0.067584",
  reservation_usd: paired ? "0.089293" : "0.067584", models: paired ? [{model_name: "Gemini 3.5 Flash-Lite"}, {model_name: "Gemini 3.7 Flash"}] : [{model_name: "Gemini 3.7 Flash"}],
  expires_at: new Date(Date.now() + 600000).toISOString(), exact_payload: "Write tests",
}});
const pool = {budget_usd: "4", remaining_usd: "3.9", expires_at: "2026-11-06T18:29:00+00:00"};
const reply = value => new Response(JSON.stringify(value));
beforeEach(() => {
  elements = new Map();
  globalThis.document = {body: {dataset: {deploymentMode: "hosted-live"}}, getElementById(id) {
    if (!elements.has(id)) elements.set(id, {hidden: false, disabled: false, textContent: "", scrollIntoView() {}, addEventListener(event, handler) {this[event] = handler;}});
    return elements.get(id);
  }};
  calls = [];
  mock.method(globalThis, "fetch", async (path, options) => {
    calls.push([path, options]);
    if (path === "/api/hosted/quote") return reply(quote("draft", JSON.parse(options.body).compare_models === true));
    if (path === "/api/hosted/status") return reply({...pool, expires_at: new Date(Date.now() + 86400000).toISOString()});
    return reply({status: "completed", response: null});
  });
  invalidateHosted();
});
afterEach(() => {mock.restoreAll(); delete globalThis.document;});

test("preview prepares a run but sends no execution; one click sends exactly once", async () => {
  await prepareHosted({prompt: "Write tests"}, "draft");
  assert.deepEqual(calls.map(row => row[0]), ["/api/hosted/quote", "/api/hosted/quote", "/api/hosted/status"]);
  assert.match(elements.get("hosted-prepare").textContent, /Run Gemini/);
  assert.match(elements.get("hosted-run-note").textContent, /\$0.067584/);
  await Promise.all([runHosted("draft"), runHosted("draft")]);
  const dispatched = calls.filter(row => row[0] === "/api/hosted/execute");
  assert.equal(dispatched.length, 1);
  assert.equal(JSON.parse(dispatched[0][1].body).approval_hash, "exact-plan");
  await runHosted("draft");
  assert.equal(calls.filter(row => row[0] === "/api/hosted/execute").length, 1);
});

test("paired action approves two models once and renders escaped output side by side", async () => {
  await prepareHosted({prompt: "Write tests"}, "draft");
  assert.match(elements.get("hosted-compare").textContent, /Compare Flash-Lite/);
  assert.match(elements.get("hosted-run-note").textContent, /0.089293/);
  const sent = [];
  mock.method(globalThis, "fetch", async (path, options) => {
    if (path.endsWith("status")) return reply(pool);
    sent.push(JSON.parse(options.body));
    return reply({status:"completed", comparison: {complete:true,lower_observed_cost_model:"Lite",cost_difference_usd:"0.0001",cost_reduction_percent:"50"}, responses:[
      {model_name:"Gemini 3.5 Flash-Lite",status:"completed",response:{text:"<img src=x onerror=alert(1)>",raw_usage:{input_tokens:10,candidate_tokens:20},elapsed_seconds:1,estimated_cost_usd:"0.0001",finish_reason:"STOP",complete_output:true}},
      {model_name:"Gemini 3.7 Flash",status:"not_started",response:null},
    ]});
  });
  await Promise.all([runHosted("draft",true), runHosted("draft",true)]);
  assert.equal(sent.length,1);
  assert.equal(sent[0].plan.quote.models.length,2);
  assert.equal(sent[0].allowance_usd,"0.089293");
  assert.match(elements.get("hosted-pair-results").innerHTML,/Gemini 3.5 Flash-Lite/);
  assert.match(elements.get("hosted-pair-results").innerHTML,/Gemini 3.7 Flash/);
  assert.match(elements.get("hosted-pair-results").innerHTML,/&lt;img/);
  assert.doesNotMatch(elements.get("hosted-pair-results").innerHTML,/<img/);
});

test("editing the draft invalidates the prepared action", async () => {
  await prepareHosted({prompt: "Write tests"}, "draft");
  invalidateHosted();
  await runHosted("draft");
  assert.ok(elements.get("hosted-prepare").disabled);
  assert.ok(!calls.some(row => row[0] === "/api/hosted/execute"));
});

test("changed hashes and exhausted budget never dispatch", async () => {
  await prepareHosted({prompt: "Write tests"}, "changed");
  await runHosted("changed");
  assert.ok(!calls.some(row => row[0] === "/api/hosted/execute"));
  mock.method(globalThis, "fetch", async path => reply(path.endsWith("quote") ? quote() : {...pool, remaining_usd: "0"}));
  await prepareHosted({prompt: "Write tests"}, "draft");
  assert.ok(elements.get("hosted-prepare").disabled);
  assert.match(elements.get("hosted-run-note").textContent, /budget unavailable/);
});

test("a lost execution response is never automatically repeated; refresh reads only", async () => {
  await prepareHosted({prompt: "Write tests"}, "draft");
  const sent = [];
  mock.method(globalThis, "fetch", async path => {
    sent.push(path);
    if (path.endsWith("execute")) throw new TypeError("Connection lost");
    return reply(path.endsWith("status") ? pool : {status: "reserved"});
  });
  await runHosted("draft");
  assert.match(elements.get("hosted-status").textContent, /saved receipt/);
  wireHosted();
  await elements.get("hosted-refresh").click();
  assert.deepEqual(sent, ["/api/hosted/execute", "/api/hosted/status", "/api/hosted/runs/run"]);
});

test("saved hosted links only read receipts and reject invalid IDs", async () => {
  const id = "a".repeat(32), requested = [];
  mock.method(globalThis, "fetch", async path => {
    requested.push(path);
    return reply(path.endsWith("status") ? pool : {status:"completed",quote:{...quote().quote,id},response:null});
  });
  await openHosted(id);
  assert.deepEqual(requested,[`/api/hosted/runs/${id}`,"/api/hosted/status"]);
  assert.equal(elements.get("hosted-reopen").href,`/?hosted=${id}`);
  assert.match(elements.get("hosted-mode").textContent,/NO NEW MODEL CALLS/);
  await assert.rejects(openHosted("../bad"),/Invalid hosted result/);
  assert.equal(requested.length,2);
});
